"""Crawl rules per source (#79): stored rules, blocks applied at once, the routes."""

import pytest
from fastapi.testclient import TestClient

from conftest import onehot
from navigator.api import app, get_conn, get_embed, get_expand, get_explain
from navigator.expand import Expansion
from navigator.models import CrawlRulesUpdate
from navigator.rules import RulesError, apply_blocks, get_rules, save_rules, validate, with_stored
from navigator.core.settings import BACKEND_ROOT
from navigator.sources import load_sources

SOURCES = load_sources(BACKEND_ROOT / "config" / "sources.yaml")
BLOCK_ALICE = {"allow_hosts": ["artorg.example"], "include_patterns": [], "exclude_patterns": [r"/alice$"],
               "priority_patterns": [r"/lab"]}


@pytest.fixture
def client(test_conn, graph):
    app.dependency_overrides[get_conn] = lambda: test_conn
    app.dependency_overrides[get_embed] = lambda: lambda q: onehot({3: 0.8, 1: 0.6})  # glucose: Bob, then Alice
    app.dependency_overrides[get_expand] = lambda: lambda q: Expansion()
    app.dependency_overrides[get_explain] = lambda: lambda q, results: {}
    yield TestClient(app)
    app.dependency_overrides.clear()


def _evidence(client, name: str) -> set[str]:
    results = client.get("/api/search", params={"q": "glucose"}).json()["results"]
    return {e["value"] for r in results if r["name"] == name for e in r["evidence"]}


def test_get_rules_defaults_to_sources_yaml(client):
    body = client.get("/api/sources/artorg/rules").json()
    artorg = SOURCES.get("artorg")
    assert body == {"allow_hosts": artorg.allow_hosts, "include_patterns": artorg.include_patterns,
                    "exclude_patterns": artorg.exclude_patterns, "priority_patterns": artorg.priority_patterns,
                    "changed_at": None}
    assert client.get("/api/sources/nope/rules").status_code == 404


def test_block_applies_at_once_and_unblock_restores(client, test_conn, graph):
    assert "continuous glucose monitoring" in _evidence(client, "Alice Muster")  # from her page p1
    res = client.put("/api/sources/artorg/rules", json=BLOCK_ALICE)
    assert res.status_code == 200 and res.json()["changed_at"]
    assert test_conn.execute("SELECT url FROM page WHERE blocked").fetchall() == [("https://artorg.example/alice",)]

    alice = _evidence(client, "Alice Muster")
    assert "continuous glucose monitoring" not in alice and "Professor" not in alice  # p1 claims hidden
    assert "diabetes technology" in alice  # her claim from the lab page stays
    stats = {s["source"]: s for s in client.get("/api/stats").json()["sources"]}
    assert stats["artorg"]["shown_claims"] == 6  # only the lab page's

    # The pages list still counts the blocked page and names the pattern
    pages = {p["url"]: p for p in client.get("/api/pages").json()}
    blocked = pages["https://artorg.example/alice"]
    assert blocked["blocked_by"] == r"/alice$" and blocked["verified_claims"] == 4
    assert pages["https://artorg.example/lab"]["prioritised_by"] == r"/lab"

    # Survives a restart (stored), and unblocking brings the facts back
    assert client.get("/api/sources/artorg/rules").json()["exclude_patterns"] == [r"/alice$"]
    client.put("/api/sources/artorg/rules", json={**BLOCK_ALICE, "exclude_patterns": []})
    assert "continuous glucose monitoring" in _evidence(client, "Alice Muster")
    assert test_conn.execute("SELECT count(*) FROM page WHERE blocked").fetchone()[0] == 0


def test_entity_with_no_claim_left_is_dropped(client, graph):
    client.put("/api/sources/dcb/rules", json={**BLOCK_ALICE, "allow_hosts": ["dcb.example"],
                                                 "exclude_patterns": [r"/bob$"]})
    names = [r["name"] for r in client.get("/api/search", params={"q": "glucose"}).json()["results"]]
    assert "Bob Beispiel" not in names and "Alice Muster" in names


@pytest.mark.parametrize(("change", "message"), [
    ({"exclude_patterns": ["(unclosed"]}, "exclude_patterns: invalid regex '(unclosed'"),
    ({"priority_patterns": ["ok", "[bad"]}, "priority_patterns: invalid regex '[bad'"),
    ({"allow_hosts": []}, "allow_hosts: at least one host is needed"),
])
def test_put_rejects_bad_rules(client, test_conn, change, message):
    res = client.put("/api/sources/artorg/rules", json={**BLOCK_ALICE, **change})
    assert res.status_code == 422 and res.json()["detail"].startswith(message)
    assert test_conn.execute("SELECT count(*) FROM source_rules").fetchone()[0] == 0


def test_put_unknown_source_is_404(client):
    assert client.put("/api/sources/nope/rules", json=BLOCK_ALICE).status_code == 404


def test_stored_rules_drive_the_crawler(test_conn, graph):
    artorg = SOURCES.get("artorg")
    assert with_stored(test_conn, artorg) == artorg
    save_rules(test_conn, SOURCES, "artorg", CrawlRulesUpdate(**BLOCK_ALICE))
    crawled = with_stored(test_conn, artorg)
    assert crawled.allow_hosts == ["artorg.example"] and crawled.exclude_patterns == [r"/alice$"]
    assert crawled.seeds == artorg.seeds and crawled.max_pages == artorg.max_pages  # only the rules change


def test_rules_of_a_source_added_from_the_ui(test_conn, graph):
    test_conn.execute(
        """INSERT INTO source (id, name, config) VALUES ('lab', 'Lab', '{"source": {"id": "lab", "name": "Lab",
           "seeds": ["https://lab.test/"], "allow_hosts": ["lab.test"], "max_pages": 50}, "max_depth": 2}')"""
    )
    rules = get_rules(test_conn, SOURCES, "lab")
    assert rules.allow_hosts == ["lab.test"] and rules.changed_at is None


def test_apply_blocks_after_a_crawl(test_conn, graph):
    save_rules(test_conn, SOURCES, "artorg", CrawlRulesUpdate(**BLOCK_ALICE))
    test_conn.execute("UPDATE page SET blocked = false")  # as after replace_pages
    crawled = with_stored(test_conn, SOURCES.get("artorg"))
    assert apply_blocks(test_conn, "artorg", crawled.exclude_patterns) == 1
    assert apply_blocks(test_conn, "artorg", []) == 0  # unblocked again


def test_follow_outbound_source_may_have_no_hosts():
    config = SOURCES.get("artorg").model_copy(update={"allow_hosts": [], "allow_hosts_regex": ".*"})
    validate(config, CrawlRulesUpdate(**{**BLOCK_ALICE, "allow_hosts": []}))  # no error
    with pytest.raises(RulesError):
        validate(SOURCES.get("artorg"), CrawlRulesUpdate(**{**BLOCK_ALICE, "allow_hosts": []}))
