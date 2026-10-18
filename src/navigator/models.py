"""API data models (plan 8.8, 8.9). `frontend/src/api/types.ts` mirrors them: keep both in sync."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

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
    added: bool = False         # case references only: added from the chat, not found by the analysis (#81)


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
    parent: str | None          # page that linked here; None for a seed, or a source crawled before #55
    depth: int
    status: PageStatus


class Source(BaseModel):
    """A crawled website (docs/FRONTEND_API.md "Sources")."""
    id: str
    name: str
    root_url: str               # first seed in config/sources.yaml, or the URL it was added with
    validated: bool             # listed in config/sources.yaml
    status: SourceStatus
    stage: str | None = None    # while crawling: crawl, embed, extract, resolve or judge
    error: str | None = None    # why the ingest failed
    pages: int
    entities: int               # entities with at least one shown claim, as in /api/stats
    verified_claims: int        # shown claims, as SourceStats.shown_claims
    last_crawled_at: datetime | None
    discovered: list[CrawledPage]  # a sample of the crawl tree, for the graph


class NewSource(BaseModel):
    """POST /api/sources: a website to crawl and ingest in the background (#55)."""
    url: str = Field(min_length=8, max_length=2000)
    name: str | None = Field(None, max_length=200)
    max_depth: int = Field(2, ge=0, le=5)
    max_pages: int = Field(50, ge=1)    # capped on the server
    follow_outbound: bool = False       # also follow links to other hosts


PageKind = Literal["team", "lab", "project", "infrastructure", "other"]


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


class PitchRequest(BaseModel):
    entity_ids: list[int] = Field(min_length=1)  # the selected references; may include chat results


class Pitch(BaseModel):
    """A sales pitch for a case (#54). Every sentence about a reference cites claim ids, e.g. [12]."""
    text: str
    entity_ids: list[int]
    generated_at: datetime


class ResourcePage(BaseModel):
    """A crawled page and what it gives the search (FRONTEND_API "Resources", #78)."""
    id: int
    source_id: str
    url: str
    title: str
    kind: PageKind              # a guess from the URL, else from the entity types on the page
    status: PageStatus          # always "crawled": failed fetches are not stored
    score: int                  # 0-100: yield 40 %, precision 30 %, verification 20 %, feedback 10 %
    score_breakdown: list[ScoreItem]  # the four parts, in that order
    entities: int               # entities with a shown claim from the page
    verified_claims: int        # shown claims from the page
    judge_supported: float | None  # share of judged claims marked "supported", 0-1; None: none judged
    drop_rate: float | None     # share of raw claims that failed quote verification, 0-1; None: none extracted
    feedback_up: int            # on entities whose results cite the page
    feedback_down: int
    crawled_at: datetime | None
    blocked_by: str | None      # first exclude pattern of the source that matches the URL
    prioritised_by: str | None  # first priority pattern of the source that matches the URL


class PageFact(BaseModel):
    claim_id: int
    entity_id: int
    entity_name: str
    entity_type: EntityType
    field: str
    value: str
    quote: str
    judge_verdict: JudgeVerdict | None


class PageDetail(ResourcePage):
    facts: list[PageFact]       # the shown claims from the page


class Selection(BaseModel):
    """The references chosen for the pitch (#81)."""
    entity_ids: list[int]


class AddReference(BaseModel):
    entity_id: int              # a chat result of the case's session


class CaseChatTurn(BaseModel):
    """A stored chat turn of the case drawer (#81); `response` is rebuilt from the current claims."""
    message: str
    response: ChatResponse
    created_at: datetime


class CaseFeedback(BaseModel):
    """The feedback given in the case's chat session (#81): the last 👍/👎 per entity and the flagged claims."""
    ratings: dict[int, Literal["up", "down"]]
    flagged: list[int]          # claim ids rated "wrong_fact"
