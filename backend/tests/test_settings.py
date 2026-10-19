"""Settings outside the source checkout's working directory (#102)."""

import os
import subprocess
import sys

from navigator.settings import BACKEND_ROOT, REPO_ROOT, Settings, get_settings


def test_defaults_point_into_the_checkout():
    s = get_settings()
    assert s.eval_dir == BACKEND_ROOT / "eval"
    assert s.sources_file == BACKEND_ROOT / "config" / "sources.yaml"
    assert s.rerank_model == "BAAI/bge-reranker-v2-m3"


def test_env_file_is_the_repo_roots():
    """Commands run in backend/ read the repo root's .env (#164); a .env in the working directory overrides it."""
    assert BACKEND_ROOT.name == "backend" and REPO_ROOT == BACKEND_ROOT.parent
    if "NAVIGATOR_ENV_FILE" not in os.environ:
        assert Settings.model_config["env_file"] == (REPO_ROOT / ".env", ".env")


def test_env_file_and_paths_from_another_directory(tmp_path):
    """NAVIGATOR_ENV_FILE is read from any working directory; its paths and models override the defaults."""
    env = tmp_path / "navigator.env"
    env.write_text(f"RERANK_MODEL=some/reranker\nEVAL_DIR={tmp_path / 'eval'}\nSOURCES_FILE={tmp_path / 's.yaml'}\n")
    code = "from navigator.settings import get_settings as g; s = g(); print(s.rerank_model, s.eval_dir, s.sources_file)"
    clean = {k: v for k, v in os.environ.items() if k not in {"RERANK_MODEL", "EVAL_DIR", "SOURCES_FILE"}}
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=tmp_path, env={**clean, "NAVIGATOR_ENV_FILE": str(env)},
        capture_output=True, text=True, check=True,
    ).stdout.split()
    assert out == ["some/reranker", str(tmp_path / "eval"), str(tmp_path / "s.yaml")]


def test_extract_model_is_8b_unless_set(tmp_path):
    """Host runs extract with the same model as Docker: unset or empty (as in .env.example) is 8B, not LLM_MODEL."""
    code = "from navigator.settings import get_settings as g; print(g().extract_model)"
    clean = {k: v for k, v in os.environ.items() if k not in {"EXTRACT_MODEL", "LLM_MODEL"}}
    out = []
    for text in ["LLM_MODEL=apertus-v1-5-70b\n", "LLM_MODEL=apertus-v1-5-70b\nEXTRACT_MODEL=\n", "EXTRACT_MODEL=other\n"]:
        env = tmp_path / "navigator.env"
        env.write_text(text)
        out.append(subprocess.run(
            [sys.executable, "-c", code], cwd=tmp_path, env={**clean, "NAVIGATOR_ENV_FILE": str(env)},
            capture_output=True, text=True, check=True,
        ).stdout.strip())
    assert out == ["apertus-v1-5-8b", "apertus-v1-5-8b", "other"]
