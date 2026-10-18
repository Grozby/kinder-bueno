"""API data models (plan 8.8, 8.9). `frontend/src/api/types.ts` mirrors them: keep both in sync."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

EntityType = Literal["person", "unit", "project", "infrastructure"]
Rating = Literal["up", "down", "wrong_fact"]
JudgeVerdict = Literal["supported", "partial"]  # "unsupported" claims are never shown


class Evidence(BaseModel):
    claim_id: int               # needed for "wrong fact" feedback
    field: str
    value: str
    quote: str
    url: str
    judge_verdict: JudgeVerdict | None  # [PoC] None: not judged
    judge_reason: str | None    # [PoC]
    via_unit: str | None = None  # set when the row is a topic of the person's unit, not the person's own claim (#44)


class Result(BaseModel):
    entity_id: int
    type: EntityType
    name: str
    role: list[str]
    contact: list[str]          # emails, phones
    affiliations: list[str]     # unit names via member_of / part_of
    expertise: list[str]        # the entity's own expertise claims
    unit_topics: list[str] = []  # persons: expertise of their member_of / listed_in units, NOT personal (#44)
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
    expansion: Expansion | None  # None when query expansion failed or gave no terms
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


class ChatFilters(BaseModel):
    """Single values, unlike /api/search (docs/FRONTEND_API.md). None = all."""
    source: str | None = None
    type: EntityType | None = None


class ChatRequest(BaseModel):
    session_id: str
    message: str                # blank with new filters: re-run the last query
    filters: ChatFilters | None = None  # None: keep the session's filters


class ChatResponse(BaseModel):
    reply: str                  # a template, never free text about entities (plan 8.10, reply check)
    results: list[Result]
    filters: ChatFilters        # the filters the server used
    expansion: Expansion | None
    no_result: bool


SourceStatus = Literal["ready", "crawling", "failed"]
PageStatus = Literal["queued", "crawled", "skipped", "failed"]


class CrawledPage(BaseModel):
    url: str
    parent: str | None          # page that linked here; not stored yet (#55), so None
    depth: int                  # not stored yet (#55), so 0
    status: PageStatus


class Source(BaseModel):
    """A crawled website (docs/FRONTEND_API.md "Sources")."""
    id: str
    name: str
    root_url: str               # first seed in config/sources.yaml
    validated: bool             # listed in config/sources.yaml
    status: SourceStatus
    pages: int
    entities: int               # entities with at least one shown claim, as in /api/stats
    verified_claims: int        # shown claims, as SourceStats.shown_claims
    last_crawled_at: datetime | None
    discovered: list[CrawledPage]  # a sample of the stored pages, for the graph


CaseStatus = Literal["new", "in_review", "accepted", "rejected"]
AnalysisStatus = Literal["pending", "done", "failed"]


class ScoreItem(BaseModel):
    criterion: str
    score: int                  # 0-100
    rationale: str


class Case(BaseModel):
    """An uploaded business model PDF and its analysis (docs/FRONTEND_API.md "Cases")."""
    id: str
    company_name: str
    file_name: str
    uploaded_at: datetime
    status: CaseStatus
    analysis_status: AnalysisStatus
    industry: str | None
    score: int | None           # 0-100; None until analysed (#53)
    score_breakdown: list[ScoreItem]
    summary: str | None


class CaseStatusUpdate(BaseModel):
    status: CaseStatus
