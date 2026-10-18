"""Settings outside the source checkout's working directory (#102)."""

import os
import subprocess
import sys

from navigator.settings import PROJECT_ROOT, get_settings


def test_defaults_point_into_the_checkout():
    s = get_settings()
    assert s.eval_dir == PROJECT_ROOT / "eval"
    assert s.sources_file == PROJECT_ROOT / "config" / "sources.yaml"
    assert s.rerank_model == "BAAI/bge-reranker-v2-m3"


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
