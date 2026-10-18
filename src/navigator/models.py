"""API data models (plan 8.8, 8.9). `frontend/src/api/types.ts` mirrors them: keep both in sync."""

from typing import Literal

from pydantic import BaseModel

EntityType = Literal["person", "unit", "project", "infrastructure"]
Rating = Literal["up", "down", "wrong_fact"]


class Evidence(BaseModel):
    claim_id: int               # needed for "wrong fact" feedback
    field: str
    value: str
    quote: str
    url: str
    judge_verdict: str | None   # [PoC] "supported" | "partial" | None
    judge_reason: str | None    # [PoC]


class Result(BaseModel):
    entity_id: int
    type: EntityType
    name: str
    role: list[str]
    contact: list[str]          # emails, phones
    affiliations: list[str]     # unit names via member_of / part_of
    expertise: list[str]
    projects: list[str]
    infrastructure: list[str]
    why: str
    score: float
    sources: list[str]          # distinct page URLs of the claims shown
    evidence: list[Evidence]    # one row per claim shown


class Expansion(BaseModel):
    en: list[str]
    de: list[str]


class SearchResponse(BaseModel):
    results: list[Result]
    expansion: Expansion | None  # None when query expansion did not run
    no_result: bool


class SourceStats(BaseModel):
    source: str
    pages: int
    chunks: int
    entities: int               # entities with at least one shown claim
    shown_claims: int


class FeedbackCounts(BaseModel):
    up: int
    down: int
    wrong_fact: int


class StatsResponse(BaseModel):
    sources: list[SourceStats]
    feedback: FeedbackCounts


class FeedbackRequest(BaseModel):
    session_id: str
    query: str | None = None
    entity_id: int
    claim_id: int | None = None
    rating: Rating
    comment: str | None = None


class FeedbackResponse(BaseModel):
    ok: bool = True
