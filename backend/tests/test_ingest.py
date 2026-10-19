"""Adding a source from the UI (#55): ids, URL checks, the background ingest with fakes, the routes."""

import socket

import pytest
from fastapi.testclient import TestClient

from navigator import ingest
from navigator.api import app, get_conn, get_ingest, get_ingest_slot, get_seeds
from navigator.crawl import CrawledPage
from navigator.ingest import SourceError, add_source, check_url, run_ingest, source_config, source_id_for

TEXT = "Dr. Jane Doe leads the Sensor Lab and works on glucose sensors. " * 3


@pytest.fixture
def public_dns(monkeypatch):
    """Every *.test host resolves to a public address, except *.intranet.test. Other hosts resolve for real:
    the ingest slot opens a connection to the test database."""
    real = socket.getaddrinfo

    def fake(host, port, *args, **kwargs):
        if not str(host).endswith(".test"):
            return real(host, port, *args, **kwargs)
        ip = "10.0.0.5" if host.endswith("intranet.test") else "130.92.1.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]
    monkeypatch.setattr(socket, "getaddrinfo", fake)


@pytest.fixture
def slot(test_database_url):
    """The ingest slot is free before and after each test; yields a function that takes it."""
    def take():
        taken = ingest.try_start(test_database_url)
        assert taken is not None, "the ingest slot is taken"
        return taken

    ingest.finish(take())
    yield take
    ingest.finish(take())


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
        from types import SimpleNamespace

        from navigator.extract import Checked, PageResult

        steps.append(("extract", len(rows)))
        if fail_at == "extract":
            raise RuntimeError("gateway down")
        if fail_at == "extract_errors":  # the gateway fails per page: extract_pages does not raise
            return [PageResult(page_id=i, error="timeout") for i, *_ in rows]
        claim = SimpleNamespace(entity_type="person", entity_name="Jane Doe", field="role", value="Head")
        return [PageResult(page_id=i, claims=[Checked(claim, True, "Jane Doe, Head", None)]) for i, *_ in rows]

    def step(name, result=None):
        def run(*args, **kwargs):
            steps.append((name,))
            if fail_at == name:
                raise RuntimeError(f"{name} broke")
            return result
        return run

    monkeypatch.setattr("navigator.llm.LLM", lambda *args, **kwargs: object())  # no gateway key needed (CI)
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
    run_ingest(ingest.try_start(test_database_url), "lab")
    return test_conn.execute("SELECT status, stage, error FROM source WHERE id = 'lab'").fetchone()


def test_ingest_runs_the_pipeline_and_records_the_crawl(test_conn, test_database_url, monkeypatch, slot):
    pages = [CrawledPage("https://lab.test/", "Lab", TEXT), CrawledPage("https://lab.test/team", "Team", TEXT)]
    steps = _fake_pipeline(monkeypatch, pages)
    assert _ingest(test_conn, test_database_url) == ("ready", None, None)
    assert steps == [("crawl", 2), ("extract", 2), ("resolve",), ("judge",)]
    assert test_conn.execute("SELECT count(*) FROM page WHERE source_id = 'lab'").fetchone()[0] == 2
    assert test_conn.execute("SELECT count(*) FROM chunk").fetchone()[0] >= 2
    # Raw rows point at the stored pages (extraction ran on page indexes before the pages existed)
    raw = test_conn.execute("SELECT p.url FROM raw_claim r JOIN page p ON p.id = r.page_id ORDER BY p.url").fetchall()
    assert raw == [("https://lab.test/",), ("https://lab.test/team",)]
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
def client(test_conn, test_database_url, public_dns, slot):
    started = []
    app.dependency_overrides[get_conn] = lambda: test_conn
    app.dependency_overrides[get_seeds] = lambda: {}
    app.dependency_overrides[get_ingest_slot] = lambda: lambda: ingest.try_start(test_database_url)
    app.dependency_overrides[get_ingest] = lambda: lambda taken, source_id: (started.append(source_id), ingest.finish(taken))
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


def test_post_source_while_an_ingest_runs_is_409(client, slot):
    http, started = client
    running = slot()  # held on its own connection, as by another API worker
    try:
        res = http.post("/api/sources", json={"url": "https://lab.test/"})
        assert res.status_code == 409
    finally:
        ingest.finish(running)
    assert started == []


def test_slot_is_one_per_database_and_freed_when_its_connection_closes(test_database_url, slot):
    first = slot()
    assert ingest.try_start(test_database_url) is None  # any other connection: another worker or replica
    first.close()  # the worker died: Postgres ends the session and frees the lock
    second = slot()
    ingest.finish(second)


# --- re-crawl (#80) ---

def _old_page(test_conn) -> None:
    """The source as a previous crawl left it: one page with a chunk."""
    import numpy as np

    pid = test_conn.execute("INSERT INTO page (source_id, url, title, text) VALUES ('lab', 'https://lab.test/old', "
                            "'Old', 'old text') RETURNING id").fetchone()[0]
    test_conn.execute("INSERT INTO chunk (page_id, ord, text, embedding) VALUES (%s, 0, 'old', %s)",
                      (pid, np.zeros(1024)))
    test_conn.commit()


@pytest.mark.parametrize("fail_at", ["extract", "extract_errors", "resolve"])
def test_failed_recrawl_keeps_the_previous_data(test_conn, test_database_url, monkeypatch, slot, fail_at):
    test_conn.execute(
        """INSERT INTO source (id, name, config, root_url) VALUES ('lab', 'Lab', %s, 'https://lab.test/')""",
        (__import__("json").dumps({"source": source_config("lab", "Lab", "https://lab.test/", "lab.test", False,
                                                           50).model_dump(), "max_depth": 2}),),
    )
    _old_page(test_conn)
    _fake_pipeline(monkeypatch, [CrawledPage("https://lab.test/", "Lab", TEXT)], fail_at=fail_at)
    run_ingest(slot(), "lab")
    status, error = test_conn.execute("SELECT status, error FROM source WHERE id = 'lab'").fetchone()
    assert status == "failed" and error.startswith(fail_at.split("_")[0])
    assert test_conn.execute("SELECT url FROM page WHERE source_id = 'lab'").fetchall() == [("https://lab.test/old",)]
    assert test_conn.execute("SELECT count(*) FROM chunk").fetchone()[0] == 1


def test_recrawl_of_a_sources_yaml_source_uses_its_stored_rules(test_conn, test_database_url, monkeypatch, slot):
    from navigator.models import CrawlRulesUpdate
    from navigator.rules import save_rules
    from navigator.sources import load_sources
    from navigator.settings import BACKEND_ROOT

    sources = load_sources(BACKEND_ROOT / "config" / "sources.yaml")
    test_conn.execute("INSERT INTO source (id, name) VALUES ('artorg', 'ARTORG')")
    save_rules(test_conn, sources, "artorg", CrawlRulesUpdate(
        allow_hosts=["www.artorg.unibe.ch"], include_patterns=[], exclude_patterns=[r"/team$"], priority_patterns=[]))
    test_conn.commit()
    seen = {}

    async def crawl(source, defaults, on_url=None, **kwargs):
        seen.update(exclude=source.exclude_patterns, depth=defaults.max_depth, seeds=source.seeds)
        return [CrawledPage(source.seeds[0], "ARTORG", TEXT), CrawledPage("https://www.artorg.unibe.ch/team", "T", TEXT)]

    _fake_pipeline(monkeypatch, [])
    monkeypatch.setattr("navigator.crawl.crawl_source", crawl)
    assert ingest.start_recrawl(test_conn, sources, "artorg")
    test_conn.commit()
    assert test_conn.execute("SELECT status, stage FROM source WHERE id = 'artorg'").fetchone() == ("crawling", "crawl")
    run_ingest(slot(), "artorg")
    assert seen == {"exclude": [r"/team$"], "depth": sources.defaults.max_depth, "seeds": sources.get("artorg").seeds}
    assert test_conn.execute("SELECT status FROM source WHERE id = 'artorg'").fetchone() == ("ready",)
    # A page matching the stored exclude pattern (here: a seed-like page the fake crawler returned) is blocked
    assert test_conn.execute("SELECT url FROM page WHERE blocked").fetchall() == [("https://www.artorg.unibe.ch/team",)]


def test_start_recrawl_unknown_source(test_conn):
    from navigator.sources import load_sources
    from navigator.settings import BACKEND_ROOT

    sources = load_sources(BACKEND_ROOT / "config" / "sources.yaml")
    assert not ingest.start_recrawl(test_conn, sources, "nope")
    test_conn.execute("INSERT INTO source (id, name) VALUES ('gone', 'Removed from sources.yaml')")
    assert not ingest.start_recrawl(test_conn, sources, "gone")


def test_recrawl_route(client, test_conn, test_database_url):
    http, started = client
    test_conn.execute("INSERT INTO source (id, name) VALUES ('artorg', 'ARTORG')")
    res = http.post("/api/sources/artorg/crawl")
    assert res.status_code == 200 and (res.json()["status"], res.json()["stage"]) == ("crawling", "crawl")
    assert started == ["artorg"]
    assert http.post("/api/sources/nope/crawl").status_code == 404
    running = ingest.try_start(test_database_url)
    try:
        assert http.post("/api/sources/artorg/crawl").status_code == 409
    finally:
        ingest.finish(running)
    assert started == ["artorg"]

