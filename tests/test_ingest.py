"""Adding a source from the UI (#55): ids, URL checks, the background ingest with fakes, the routes."""

import socket

import pytest
from fastapi.testclient import TestClient

from navigator import ingest
from navigator.api import app, get_conn, get_ingest, get_seeds
from navigator.crawl import CrawledPage
from navigator.ingest import SourceError, add_source, check_url, run_ingest, source_config, source_id_for

TEXT = "Dr. Jane Doe leads the Sensor Lab and works on glucose sensors. " * 3


@pytest.fixture
def public_dns(monkeypatch):
    """Every host resolves to a public address, except *.intranet.test."""
    def fake(host, port, *args, **kwargs):
        ip = "10.0.0.5" if host.endswith("intranet.test") else "130.92.1.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]
    monkeypatch.setattr(socket, "getaddrinfo", fake)


@pytest.fixture
def slot():
    """The ingest slot is free before and after each test."""
    assert ingest.try_start()
    ingest.finish()
    yield
    assert ingest.try_start(), "a test left the ingest slot taken"
    ingest.finish()


@pytest.mark.parametrize(("host", "taken", "expected"), [
    ("www.example.unibe.ch", set(), "example_unibe"),
    ("artorg.unibe.ch", {"artorg_unibe"}, "artorg_unibe_2"),
    ("my-lab.org", {"my_lab", "my_lab_2"}, "my_lab_3"),
])
def test_source_id_for(host, taken, expected):
    assert source_id_for(host, taken) == expected


@pytest.mark.parametrize("url", ["ftp://lab.test/", "https://localhost:8000/", "http://127.0.0.1/",
                                 "https://10.1.2.3/", "https://wiki.intranet.test/", "https:///x"])
def test_check_url_rejects_non_public(public_dns, url):
    with pytest.raises(SourceError):
        check_url(url)


def test_check_url_accepts_public_host(public_dns):
    assert check_url("https://Lab.Example.ch/team/") == "lab.example.ch"


def test_source_config_caps_pages_and_host_rule():
    own = source_config("x", "X", "https://lab.test/", "lab.test", False, 500)
    assert own.max_pages == ingest.MAX_PAGES and own.allow_hosts == ["lab.test", "www.lab.test"]
    outbound = source_config("x", "X", "https://lab.test/", "lab.test", True, 10)
    assert outbound.allow_hosts_regex == ingest.PUBLIC_HOST and outbound.max_pages == 10


def test_add_source_marks_an_interrupted_ingest_failed(test_conn, public_dns):
    test_conn.execute("INSERT INTO source (id, name, config, status, stage) VALUES ('old', 'Old', '{}', 'crawling', 'extract')")
    add_source(test_conn, "https://lab.test/", None, 2, 50, False)
    assert test_conn.execute("SELECT status, stage, error FROM source WHERE id = 'old'").fetchone() == \
        ("failed", None, "interrupted: the API restarted")


def test_add_source_reuses_only_a_failed_ui_source(test_conn, public_dns):
    test_conn.execute("INSERT INTO source (id, name) VALUES ('lab', 'Lab from sources.yaml')")
    assert add_source(test_conn, "https://lab.test/", None, 9, 50, False) == "lab_2"  # yaml source kept
    row = test_conn.execute("SELECT name, status, stage, root_url, config FROM source WHERE id = 'lab_2'").fetchone()
    assert row[:4] == ("lab.test", "crawling", "crawl", "https://lab.test/")
    assert row[4]["max_depth"] == ingest.MAX_DEPTH and row[4]["source"]["seeds"] == ["https://lab.test/"]
    assert add_source(test_conn, "https://lab.test/", "Lab", 2, 50, False) == "lab_3"  # lab_2 is marked failed
    # only the base id is reused: lab_2 failed, but a new one is lab_4
    assert add_source(test_conn, "https://lab.test/", "Lab", 2, 50, False) == "lab_4"
    test_conn.execute("DELETE FROM source WHERE id = 'lab'")
    test_conn.execute("INSERT INTO source (id, name, config, status) VALUES ('lab', 'old', '{}', 'failed')")
    assert add_source(test_conn, "https://lab.test/", "Lab", 2, 50, False) == "lab"


def _fake_pipeline(monkeypatch, pages, fail_at=None):
    """Fake crawl (reports its URLs), embeddings, extraction, resolve and judge. Returns the steps run."""
    import numpy as np

    steps = []

    async def crawl(source, defaults, on_url=None, **kwargs):
        steps.append(("crawl", defaults.max_depth))
        on_url(source.seeds[0], None, 0, "queued")
        for p in pages:
            on_url(p.url, None if p.url == source.seeds[0] else source.seeds[0], 0 if p.url == source.seeds[0] else 1,
                   "crawled")
        on_url(source.seeds[0] + "never", source.seeds[0], 1, "queued")  # left in the queue at the page cap
        return pages

    async def extract(llm, rows):
        steps.append(("extract", len(rows)))
        if fail_at == "extract":
            raise RuntimeError("gateway down")
        return []

    def step(name, result=None):
        def run(*args, **kwargs):
            steps.append((name,))
            if fail_at == name:
                raise RuntimeError(f"{name} broke")
            return result
        return run

    monkeypatch.setattr("navigator.crawl.crawl_source", crawl)
    monkeypatch.setattr("navigator.embed.embed_documents", lambda texts: [np.zeros(1024) for _ in texts])
    monkeypatch.setattr("navigator.extract.extract_pages", extract)
    monkeypatch.setattr("navigator.resolve.resolve", step("resolve"))
    monkeypatch.setattr("navigator.judge.run_judge", step("judge"))
    return steps


def _ingest(test_conn, test_database_url, url="https://lab.test/"):
    test_conn.execute(
        """INSERT INTO source (id, name, config, root_url, status, stage) VALUES ('lab', 'Lab', %s, %s, 'crawling', 'crawl')""",
        (__import__("json").dumps({"source": source_config("lab", "Lab", url, "lab.test", False, 50).model_dump(),
                                   "max_depth": 2}), url),
    )
    test_conn.commit()
    assert ingest.try_start()
    run_ingest(test_database_url, "lab")
    return test_conn.execute("SELECT status, stage, error FROM source WHERE id = 'lab'").fetchone()


def test_ingest_runs_the_pipeline_and_records_the_crawl(test_conn, test_database_url, monkeypatch, slot):
    pages = [CrawledPage("https://lab.test/", "Lab", TEXT), CrawledPage("https://lab.test/team", "Team", TEXT)]
    steps = _fake_pipeline(monkeypatch, pages)
    assert _ingest(test_conn, test_database_url) == ("ready", None, None)
    assert steps == [("crawl", 2), ("extract", 2), ("resolve",), ("judge",)]
    assert test_conn.execute("SELECT count(*) FROM page WHERE source_id = 'lab'").fetchone()[0] == 2
    assert test_conn.execute("SELECT count(*) FROM chunk").fetchone()[0] >= 2
    tree = test_conn.execute("SELECT url, parent, depth, status FROM crawl_url ORDER BY id").fetchall()
    assert tree == [("https://lab.test/", None, 0, "crawled"),
                    ("https://lab.test/team", "https://lab.test/", 1, "crawled"),
                    ("https://lab.test/never", "https://lab.test/", 1, "skipped")]


@pytest.mark.parametrize("fail_at", ["extract", "resolve"])
def test_failed_ingest_leaves_no_pages(test_conn, test_database_url, monkeypatch, slot, fail_at):
    steps = _fake_pipeline(monkeypatch, [CrawledPage("https://lab.test/", "Lab", TEXT)], fail_at=fail_at)
    status, stage, error = _ingest(test_conn, test_database_url)
    assert (status, stage) == ("failed", None) and error.startswith(f"{fail_at}: ")
    assert ("judge",) not in steps
    assert test_conn.execute("SELECT count(*) FROM page WHERE source_id = 'lab'").fetchone()[0] == 0
    assert test_conn.execute("SELECT count(*) FROM crawl_url").fetchone()[0] == 2  # the graph stays


def test_no_pages_fails(test_conn, test_database_url, monkeypatch, slot):
    _fake_pipeline(monkeypatch, [])
    status, _, error = _ingest(test_conn, test_database_url)
    assert status == "failed" and error.startswith("crawl: No page")


def test_judge_error_still_ready(test_conn, test_database_url, monkeypatch, slot):
    _fake_pipeline(monkeypatch, [CrawledPage("https://lab.test/", "Lab", TEXT)], fail_at="judge")
    assert _ingest(test_conn, test_database_url) == ("ready", None, "judge: judge broke")


# --- routes ---

@pytest.fixture
def client(test_conn, public_dns, slot):
    started = []
    app.dependency_overrides[get_conn] = lambda: test_conn
    app.dependency_overrides[get_seeds] = lambda: {}
    app.dependency_overrides[get_ingest] = lambda: lambda source_id: (started.append(source_id), ingest.finish())
    yield TestClient(app), started
    app.dependency_overrides.clear()


def test_post_source_returns_crawling_and_starts_the_ingest(client):
    http, started = client
    res = http.post("/api/sources", json={"url": "https://www.lab.test/", "name": "Lab", "max_depth": 2,
                                          "max_pages": 50, "follow_outbound": False})
    assert res.status_code == 200
    body = res.json()
    assert (body["id"], body["name"], body["status"], body["stage"], body["validated"]) == \
        ("lab", "Lab", "crawling", "crawl", False)
    assert body["root_url"] == "https://www.lab.test/" and body["pages"] == 0
    assert started == ["lab"]
    assert http.get("/api/sources/lab").json()["status"] == "crawling"


def test_post_source_rejects_bad_urls_and_frees_the_slot(client):
    http, started = client
    res = http.post("/api/sources", json={"url": "http://192.168.1.1/admin", "max_depth": 1, "max_pages": 5,
                                          "follow_outbound": False})
    assert res.status_code == 422 and "public" in res.json()["detail"]
    assert http.post("/api/sources", json={"url": "x"}).status_code == 422
    assert started == []


def test_post_source_while_an_ingest_runs_is_409(client):
    http, started = client
    assert ingest.try_start()
    try:
        res = http.post("/api/sources", json={"url": "https://lab.test/"})
        assert res.status_code == 409
    finally:
        ingest.finish()
    assert started == []
