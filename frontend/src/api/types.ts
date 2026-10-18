// Contract between the frontend and the backend. See docs/FRONTEND_API.md for the endpoints.

export type CaseStatus = 'new' | 'in_review' | 'accepted' | 'rejected'
export type AnalysisStatus = 'pending' | 'done' | 'failed'
export type EntityType = 'person' | 'unit' | 'project' | 'infrastructure'

export interface ScoreItem {
  criterion: string // e.g. "Research fit", "Talent pool", "Infrastructure"
  score: number // 0-100
  rationale: string
}

// A business model PDF uploaded by a user, and the backend's analysis of it.
export interface Case {
  id: string
  company_name: string
  file_name: string
  uploaded_at: string // ISO 8601
  status: CaseStatus
  analysis_status: AnalysisStatus
  industry: string | null
  score: number | null // 0-100 overall fit of Canton Bern; null while pending
  score_breakdown: ScoreItem[]
  summary: string | null // short summary for the person using the app
}

// --- Search results: mirror the Pydantic models in docs/PLAN.md section 8.8 ---

export interface Evidence {
  claim_id: number
  field: string
  value: string
  quote: string
  url: string
  judge_verdict: 'supported' | 'partial' | null
  judge_reason: string | null
}

// An expert, unit, project or infrastructure in Bern. Used both as a case reference
// (supports the score and the pitch) and as a search or chat result.
export interface Result {
  entity_id: number
  type: EntityType
  name: string
  role: string[]
  contact: string[]
  affiliations: string[]
  expertise: string[]
  projects: string[]
  infrastructure: string[]
  why: string
  score: number
  sources: string[] // public pages backing this result
  evidence: Evidence[]
}

// --- Chat and feedback: docs/PLAN.md section 8.9 ---

export interface ChatFilters {
  source: string | null
  type: EntityType | null
}

export interface ChatRequest {
  session_id: string
  message: string
  filters?: ChatFilters
}

export interface ChatResponse {
  reply: string
  results: Result[]
  filters: ChatFilters
  expansion: { en: string[]; de: string[] } | null
  no_result: boolean
}

// 'wrong_fact' flags one evidence row: send it with claim_id (plan 9, "wrong fact" button). Not in the UI yet.
export type Rating = 'up' | 'down' | 'wrong_fact'

export interface FeedbackRequest {
  session_id: string
  query: string
  entity_id: number
  claim_id?: number
  rating: Rating
  comment?: string
}

export interface Pitch {
  text: string
  entity_ids: number[]
  generated_at: string
}

export type SourceStatus = 'ready' | 'crawling' | 'failed'
export type PageStatus = 'queued' | 'crawled' | 'skipped' | 'failed'

export interface CrawledPage {
  url: string
  parent: string | null // page that linked here; null for a seed
  depth: number
  status: PageStatus
}

export interface Source {
  id: string
  name: string
  root_url: string
  validated: boolean
  status: SourceStatus
  pages: number
  entities: number
  verified_claims: number
  last_crawled_at: string | null
  discovered: CrawledPage[] // a sample of the crawl tree, for the graph
}

export interface NewSource {
  url: string
  name?: string
  max_depth: number
  max_pages: number
  follow_outbound: boolean // also explore links that leave the start host
}

// --- Search and stats: mirror src/navigator/models.py (plan 8.9) ---

export interface Expansion {
  en: string[]
  de: string[]
}

export interface SearchResponse {
  results: Result[]
  expansion: Expansion | null
  no_result: boolean
}

export interface SourceStats {
  source: string
  pages: number
  chunks: number
  entities: number // entities with at least one shown claim
  shown_claims: number
}

export interface FeedbackCounts {
  up: number
  down: number
  wrong_fact: number
}

export interface StatsResponse {
  sources: SourceStats[]
  feedback: FeedbackCounts
}

export interface FeedbackResponse {
  ok: boolean
}
