"""`navigator extract` runs resolve afterwards unless --no-resolve. No DB or LLM: both are faked."""

from collections import Counter
from contextlib import contextmanager

import pytest
from typer.testing import CliRunner

from navigator import cli
from navigator.extract import PageResult

runner = CliRunner()


@pytest.fixture
def fakes(monkeypatch):
    calls = []

    @contextmanager
    def connect(_url):
        yield "conn"

    async def extract_pages(_llm, pages):
        calls.append("extract")
        return [PageResult(page_id=p[0]) for p in pages]

    monkeypatch.setattr(cli.db, "connect", connect)
    monkeypatch.setattr(cli.db, "pages_for_extraction", lambda *a: [(1, "https://t.test/", "T", "text")])
    monkeypatch.setattr(cli.db, "replace_raw_extractions", lambda conn, results: calls.append("store"))
    monkeypatch.setattr(cli, "extract_pages", extract_pages)
    monkeypatch.setattr(cli, "run_resolve", lambda conn: calls.append("resolve") or Counter(claims=3))
    return calls


def test_extract_runs_resolve_by_default(fakes):
    result = runner.invoke(cli.app, ["extract"])
    assert result.exit_code == 0, result.output
    assert fakes == ["extract", "store", "resolve"]
    assert "claims" in result.output


def test_extract_no_resolve(fakes):
    result = runner.invoke(cli.app, ["extract", "--no-resolve"])
    assert result.exit_code == 0, result.output
    assert fakes == ["extract", "store"]
