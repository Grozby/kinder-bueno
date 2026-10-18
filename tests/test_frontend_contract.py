"""Every call the UI makes to the real backend (frontend/src/api/index.ts) is a route the API serves.
Without this, a route the UI waits for (like the review and notes ones, #108) only fails on the real backend."""

import re

from navigator.api import app
from navigator.settings import PROJECT_ROOT

CLIENT = PROJECT_ROOT / "frontend" / "src" / "api" / "index.ts"
CALL = re.compile(r"(?:api<[^>]+>|apiUrl)\(\s*[`']([^`']+)[`'](?:\s*,\s*\{[^}]*?method:\s*'([A-Z]+)')?", re.DOTALL)


def _template(path: str) -> str:
    """'/cases/${id}/references?limit=${limit}' and '/api/cases/{case_id}/references' -> '/cases/{}/references'"""
    path = re.sub(r"\?.*$", "", path.removeprefix("/api"))
    return re.sub(r"\$\{[^}]+\}|\{[^}]+\}", "{}", path)


def ui_calls() -> set[tuple[str, str]]:
    text = CLIENT.read_text()
    block = text[text.index("const realBackend = {"):text.index("export type Backend")]
    return {(m.group(2) or "GET", _template(m.group(1))) for m in CALL.finditer(block)}


def served() -> set[tuple[str, str]]:
    return {(method.upper(), _template(path)) for path, ops in app.openapi()["paths"].items() for method in ops}


def test_the_parser_finds_the_calls():
    calls = ui_calls()
    assert ("POST", "/cases") in calls and ("PATCH", "/cases/{}") in calls  # multipart upload, method in options
    assert ("GET", "/cases/{}/documents/{}") in calls  # a download link (apiUrl), not a fetch
    assert len(calls) >= 30


def test_every_ui_call_is_served():
    missing = sorted(ui_calls() - served())
    assert not missing, f"the UI calls routes the API does not serve: {missing}"
