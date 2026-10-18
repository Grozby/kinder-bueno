"""Runtime settings, read from environment variables and `.env`."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    keera_api_key: str = ""
    llm_base_url: str = "https://gateway.keera.ch/api/v1"
    llm_model: str = "apertus-v1-5-70b"
    llm_concurrency: int = 8
    embed_model: str = "BAAI/bge-m3"
    database_url: str = "postgresql://navigator:navigator@localhost:5432/navigator"
    sources_file: Path = PROJECT_ROOT / "config" / "sources.yaml"


@lru_cache
def get_settings() -> Settings:
    return Settings()
