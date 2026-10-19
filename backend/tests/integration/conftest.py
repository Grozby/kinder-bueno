"""The whole stack in Docker (db, app, frontend) on a checkpoint of the current database.

Run: `uv run pytest -m integration` (about 10–15 min; the real Apertus gateway and bge-m3 are used).
- The stack is its own compose project (`navigator-it`) with its own ports and database volume:
  the tests write cases, chats and feedback there, never to the source database.
- The checkpoint is a `pg_dump` of the source database (IT_SOURCE_DATABASE_URL, default DATABASE_URL), taken once
  into `checkpoints/it.dump` and reused. Delete the file (or set IT_CHECKPOINT to another dump) for a new one.
- IT_KEEP=1 leaves the stack running after the tests (`docker compose -p navigator-it down -v` removes it).
- The app's log is saved to `checkpoints/it-app.log` before the stack is removed, for slow or failed requests.
"""

import os
import secrets
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from navigator.settings import REPO_ROOT, get_settings

PROJECT = "navigator-it"
DB_PORT = int(os.environ.get("IT_DB_PORT", "55432"))
API_PORT = int(os.environ.get("IT_API_PORT", "18000"))
UI_PORT = int(os.environ.get("IT_UI_PORT", "15173"))
CHECKPOINT = Path(os.environ.get("IT_CHECKPOINT", REPO_ROOT / "checkpoints" / "it.dump"))
APP_LOG = CHECKPOINT.parent / "it-app.log"
API_TIMEOUT = 120.0  # one request; search and chat call the gateway (expansion, explanations)


@dataclass
class Stack:
    api: httpx.Client         # the API with the token
    ui: str                   # the frontend's base URL (Vite, proxying /api)
    token: str
    database_url: str         # the stack's own database, for checking what the API returns

    def compose(self, *args: str, **kwargs) -> subprocess.CompletedProcess:
        return compose(self.token, *args, **kwargs)


def compose(token: str, *args: str, check: bool = True, **kwargs) -> subprocess.CompletedProcess:
    env = {
        **os.environ, "API_TOKEN": token, "DB_PORT": str(DB_PORT), "API_PORT": str(API_PORT), "UI_PORT": str(UI_PORT),
    }
    files = ["-f", str(REPO_ROOT / "docker-compose.yml"), "-f", str(Path(__file__).parent / "compose.yml")]
    return subprocess.run(
        ["docker", "compose", "-p", PROJECT, *files, *args], cwd=REPO_ROOT, env=env, check=check, **kwargs
    )


def source_url_for_docker() -> str:
    """The source database as seen from a container: localhost is the host, not the container."""
    url = conninfo_to_dict(os.environ.get("IT_SOURCE_DATABASE_URL", get_settings().database_url))
    if url.get("host") in (None, "localhost", "127.0.0.1"):
        url["host"] = "host.docker.internal"
    return make_conninfo(**url)


def take_checkpoint(token: str) -> None:
    """pg_dump of the source database, run in the stack's db image (same Postgres version). Read-only on the source."""
    CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)
    partial = CHECKPOINT.with_suffix(".partial")
    with partial.open("wb") as out:
        compose(token, "run", "--rm", "--no-deps", "-T", "db", "pg_dump", "-Fc", "--no-owner", source_url_for_docker(),
                stdout=out)
    partial.rename(CHECKPOINT)


def wait_for(url: str, timeout: float, headers: dict | None = None) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            if httpx.get(url, headers=headers, timeout=10).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        if time.monotonic() > deadline:
            raise TimeoutError(f"{url} not ready after {timeout:.0f} s")
        time.sleep(3)


@pytest.fixture(scope="session")
def stack() -> Stack:
    if shutil.which("docker") is None or subprocess.run(["docker", "info"], capture_output=True, check=False).returncode:
        pytest.skip("Docker is not running")
    if not (REPO_ROOT / ".env").exists():
        pytest.skip(".env is missing (the app needs KEERA_API_KEY)")
    token = secrets.token_urlsafe(16)
    compose(token, "down", "-v", "--remove-orphans", capture_output=True)  # leftovers of an aborted run
    subprocess.run(["docker", "volume", "create", os.environ.get("IT_HF_VOLUME", "kinder-bueno_hf_cache")],
                   check=True, capture_output=True)
    if not CHECKPOINT.exists():
        take_checkpoint(token)
    try:
        compose(token, "up", "-d", "--wait", "db")
        with CHECKPOINT.open("rb") as dump:
            compose(token, "exec", "-T", "db", "pg_restore", "-U", "navigator", "-d", "navigator", "--no-owner",
                    stdin=dump)
        compose(token, "build", "app")
        compose(token, "run", "--rm", "app", "uv", "run", "navigator", "init-db")  # schema changes since the dump
        compose(token, "up", "-d", "--wait", "--wait-timeout", "900", "app", "frontend")
        ui = f"http://localhost:{UI_PORT}"
        wait_for(ui, timeout=300)  # npm ci runs in the container first
        api = httpx.Client(
            base_url=f"http://localhost:{API_PORT}", headers={"Authorization": f"Bearer {token}"}, timeout=API_TIMEOUT
        )
        yield Stack(api=api, ui=ui, token=token,
                    database_url=f"postgresql://navigator:navigator@localhost:{DB_PORT}/navigator")
    except subprocess.CalledProcessError:
        compose(token, "logs", "--tail", "50", check=False)
        raise
    finally:
        with APP_LOG.open("w") as log:
            compose(token, "logs", "--timestamps", "app", check=False, stdout=log, stderr=subprocess.STDOUT)
        if not os.environ.get("IT_KEEP"):
            compose(token, "down", "-v", check=False, capture_output=True)


@pytest.fixture
def api(stack: Stack) -> httpx.Client:
    return stack.api


@pytest.fixture
def db(stack: Stack):
    with psycopg.connect(stack.database_url) as conn:
        yield conn
