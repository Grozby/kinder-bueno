"""Load and validate `config/sources.yaml`."""

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


def _compile(pattern: str) -> None:
    try:
        re.compile(pattern)
    except re.error as e:
        raise ValueError(f"invalid regex {pattern!r}: {e}") from e


class CrawlDefaults(BaseModel):
    user_agent: str = "HackApertus-ExpertiseNavigator/0.1"
    delay_seconds: float = 1.0
    timeout_seconds: float = 20.0
    max_depth: int = 3


class SourceConfig(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    name: str
    seeds: list[str] = Field(min_length=1)
    allow_hosts: list[str] = []
    allow_hosts_regex: str | None = None
    deny_hosts: list[str] = []
    include_patterns: list[str] = []
    exclude_patterns: list[str] = []
    priority_patterns: list[str] = []
    max_pages: int = Field(gt=0)

    @field_validator("include_patterns", "exclude_patterns", "priority_patterns")
    @classmethod
    def _valid_regexes(cls, patterns: list[str]) -> list[str]:
        for p in patterns:
            _compile(p)
        return patterns

    @model_validator(mode="after")
    def _has_host_rule(self) -> "SourceConfig":
        if not self.allow_hosts and not self.allow_hosts_regex:
            raise ValueError(f"source {self.id!r} needs allow_hosts or allow_hosts_regex")
        if self.allow_hosts_regex:
            _compile(self.allow_hosts_regex)
        return self


class SourcesFile(BaseModel):
    defaults: CrawlDefaults = CrawlDefaults()
    sources: list[SourceConfig] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_ids(self) -> "SourcesFile":
        ids = [s.id for s in self.sources]
        if len(ids) != len(set(ids)):
            raise ValueError("source ids must be unique")
        return self

    def get(self, source_id: str) -> SourceConfig:
        for s in self.sources:
            if s.id == source_id:
                return s
        raise KeyError(f"unknown source {source_id!r}")


def load_sources(path: Path) -> SourcesFile:
    with open(path) as f:
        return SourcesFile.model_validate(yaml.safe_load(f))
