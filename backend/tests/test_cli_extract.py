"""`navigator extract` runs resolve, then the claim judge, unless turned off. No DB or LLM: both are faked."""

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
    monkeypatch.setattr(cli, "LLM", lambda *a, **k: "llm")  # no API key needed (CI, worktrees without .env)
    monkeypatch.setattr(cli, "run_resolve", lambda conn: calls.append("resolve") or Counter(claims=3))
    monkeypatch.setattr(cli, "_run_judge", lambda conn, settings, source: calls.append("judge"))
    return calls


def test_extract_runs_resolve_by_default(fakes):
    result = runner.invoke(cli.app, ["extract"])
    assert result.exit_code == 0, result.output
    assert fakes == ["extract", "store", "resolve", "judge"]  # resolve resets verdicts, so judge comes last
    assert "claims" in result.output


def test_extract_no_resolve(fakes):
    result = runner.invoke(cli.app, ["extract", "--no-resolve"])
    assert result.exit_code == 0, result.output
    assert fakes == ["extract", "store"]


def test_extract_no_judge(fakes):
    result = runner.invoke(cli.app, ["extract", "--no-judge"])
    assert result.exit_code == 0, result.output
    assert fakes == ["extract", "store", "resolve"]


def test_extract_judge_disabled_by_setting(fakes, monkeypatch):
    monkeypatch.setenv("JUDGE_ENABLED", "false")
    cli.get_settings.cache_clear()
    try:
        result = runner.invoke(cli.app, ["extract"])
    finally:
        monkeypatch.delenv("JUDGE_ENABLED")
        cli.get_settings.cache_clear()
    assert result.exit_code == 0, result.output
    assert fakes == ["extract", "store", "resolve"]


def test_llm_speed_reports_each_model(monkeypatch):
    from navigator.core import llm

    async def fake(settings, model, max_tokens=300):
        if model == "broken":
            raise RuntimeError("504 Gateway Time-out")
        return llm.Speed(model, 0.2, 100, 2.0)

    monkeypatch.setattr(llm, "measure_speed", fake)
    result = runner.invoke(cli.app, ["llm-speed", "--model", "m1", "--model", "broken"])
    assert result.exit_code == 0, result.output
    assert "m1" in result.output and "50.0 tokens/s" in result.output
    assert "broken" in result.output and "failed: 504" in result.output
