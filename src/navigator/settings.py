"""Runtime settings, read from environment variables and `.env`."""

import os
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict



def _project_root() -> Path:
    """The source checkout when running from one, else the working directory (navigator installed as a package)."""
    root = Path(__file__).resolve().parents[2]
    return root if (root / "pyproject.toml").is_file() else Path.cwd()


PROJECT_ROOT = _project_root()
# 70B was slower and not better for extraction (plan 3, #16). The default lives here, not in docker-compose.yml,
# so host runs (`uv run navigator ingest`) extract with the same model as Docker.
EXTRACT_MODEL = "apertus-v1-5-8b"


class Settings(BaseSettings):
    # NAVIGATOR_ENV_FILE points at a .env outside the working directory
    model_config = SettingsConfigDict(env_file=os.environ.get("NAVIGATOR_ENV_FILE", ".env"), extra="ignore")

    keera_api_key: str = ""
    llm_base_url: str = "https://gateway.keera.ch/api/v1"
    llm_model: str = "apertus-v1-5-70b"
    extract_model: str = EXTRACT_MODEL  # model for extraction only; empty in .env = this default, not llm_model
    explain_model: str | None = None  # model for "why it matches" (plan 8.6); defaults to llm_model
    llm_concurrency: int = 8
    judge_enabled: bool = True
    judge_model: str | None = None  # model for the claim judge (plan 7.8); defaults to llm_model
    embed_model: str = "BAAI/bge-m3"
    rerank_model: str = "BAAI/bge-reranker-v2-m3"  # case need matching (analysis.py)
    database_url: str = "postgresql://navigator:navigator@localhost:5432/navigator"
    api_token: str = ""  # when set, /api requires `Authorization: Bearer <token>`
    sources_file: Path = PROJECT_ROOT / "config" / "sources.yaml"
    eval_dir: Path = PROJECT_ROOT / "eval"  # gold sets and the reports `navigator eval` / `case-eval` write

    @field_validator("extract_model", mode="before")
    @classmethod
    def _empty_extract_model(cls, value: str | None) -> str:
        return value or EXTRACT_MODEL  # .env.example ships `EXTRACT_MODEL=`


@lru_cache
def get_settings() -> Settings:
    return Settings()
