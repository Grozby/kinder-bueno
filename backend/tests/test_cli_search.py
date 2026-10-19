"""`navigator search` runs the /api/search pipeline on the fixture graph (tests/conftest.py). Needs Postgres;
embeddings and Apertus are faked."""

import json
import re

import pytest
from conftest import onehot
from typer.testing import CliRunner

from navigator import cli, embed, expand, explain
from navigator.expand import Expansion

runner = CliRunner()


def fake_embed(query: str):
    """Same as tests/test_api.py: 'glucose' finds Bob, then Alice; 'insulin' the lab page."""
    if "glucose" in query:
        return onehot({3: 0.8, 1: 0.6})
    if "insulin" in query:
        return onehot({2: 1.0})
    return onehot({10: 1.0})


@pytest.fixture
def calls(test_conn, graph, test_database_url, monkeypatch):
    test_conn.commit()  # the command reads on its own connection
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    cli.get_settings.cache_clear()
    calls = []

    async def fake_expand(_llm, q):
        calls.append("expand")
        return Expansion(en=["insulin"], de=["Insulinpumpe"])

    async def fake_explain(_llm, q, results):
        calls.append(("explain", len(results)))
        first = results[0]
        return {first.entity_id: f"Works on glucose [{first.evidence[0].claim_id}]."}

    monkeypatch.setattr(embed, "embed_query", fake_embed)
    monkeypatch.setattr(expand, "expand_query", fake_expand)
    monkeypatch.setattr(explain, "explain", fake_explain)
    monkeypatch.setattr(cli, "LLM", lambda *a, **k: "llm")  # no API key needed
    yield calls
    cli.get_settings.cache_clear()


def test_search_prints_ranked_results_with_evidence(calls):
    result = runner.invoke(cli.app, ["search", "glucose"])
    assert result.exit_code == 0, result.output
    assert "en: insulin\nde: Insulinpumpe" in result.output
    ranked = re.findall(r"^ *\d+\. (.+?) \(", result.output, re.MULTILINE)
    assert set(ranked[:2]) == {"Alice Muster", "Bob Beispiel"}
    assert "Carol Hidden" not in result.output  # only unverified claims
    assert "why: Works on glucose [" in result.output
    assert re.search(r"^    - \w+: .+  https?://", result.output, re.MULTILINE)  # evidence rows with their page URL
    assert calls[0] == "expand"


def test_search_json_limit_and_filters(calls):
    result = runner.invoke(cli.app, ["search", "glucose", "--json", "--limit", "1", "--source", "dcb"])
    assert result.exit_code == 0, result.output
    body = json.loads(result.output)
    assert [r["name"] for r in body["results"]] == ["Bob Beispiel"]
    assert body["expansion"] == {"en": ["insulin"], "de": ["Insulinpumpe"]}
    assert ("explain", 1) in calls  # only the shown results are explained


def test_search_no_explain_keeps_the_template(calls):
    result = runner.invoke(cli.app, ["search", "glucose", "--no-explain", "--json"])
    assert result.exit_code == 0, result.output
    assert all(r["why"].startswith("Matches on: ") for r in json.loads(result.output)["results"])
    assert not any(isinstance(c, tuple) for c in calls)


def test_search_type_filter_and_unknown_type(calls):
    result = runner.invoke(cli.app, ["search", "insulin", "--type", "unit", "--json"])
    assert {r["name"] for r in json.loads(result.output)["results"]} == {"Diabetes Lab", "ARTORG Center"}
    result = runner.invoke(cli.app, ["search", "insulin", "--type", "lab"])
    assert result.exit_code != 0
    assert "unknown type lab" in result.output
