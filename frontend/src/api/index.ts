// Typed backend endpoints. Until the backend serves them, an in-memory mock answers instead:
// set VITE_USE_MOCK=false to talk to the real backend.
// /chat and /feedback follow docs/PLAN.md section 8.9; the rest is in docs/FRONTEND_API.md.
import { api } from './client'
import { mockBackend } from './mock'
import type {
  Case,
  CaseChatTurn,
  CaseFeedback,
  CaseNote,
  CaseStatus,
  ChatRequest,
  ChatResponse,
  CrawlRules,
  FeedbackRequest,
  NewSource,
  PageDetail,
  Pitch,
  ResourcePage,
  Result,
  ReviewInput,
  RuleKind,
  Selection,
  Source,
} from './types'

export const USE_MOCK = import.meta.env.VITE_USE_MOCK !== 'false'

const realBackend = {
  listCases: () => api<Case[]>('/cases'),
  getCase: (id: string) => api<Case>(`/cases/${id}`),
  uploadCase: (file: File) => {
    const body = new FormData()
    body.append('file', file)
    return api<Case>('/cases', { method: 'POST', body })
  },
  setCaseStatus: (id: string, status: CaseStatus) =>
    api<Case>(`/cases/${id}`, { method: 'PATCH', body: JSON.stringify({ status }) }),
  listReferences: (id: string, limit: number) =>
    api<Result[]>(`/cases/${id}/references?limit=${limit}`),
  generatePitch: (id: string, entityIds: number[]) =>
    api<Pitch>(`/cases/${id}/pitch`, {
      method: 'POST',
      body: JSON.stringify({ entity_ids: entityIds }),
    }),
  // The last pitch stored on the case; null if none was generated yet
  getPitch: (id: string) =>
    api<Pitch>(`/cases/${id}/pitch`).catch((e: Error) => {
      if (e.message.startsWith('404')) return null
      throw e
    }),
  getSelection: (id: string) => api<Selection>(`/cases/${id}/selection`),
  setSelection: (id: string, entityIds: number[]) =>
    api<Selection>(`/cases/${id}/selection`, {
      method: 'PUT',
      body: JSON.stringify({ entity_ids: entityIds }),
    }),
  // A chat result kept as a reference of the case; returns it with `added: true`
  addReference: (id: string, entityId: number) =>
    api<Result>(`/cases/${id}/references`, {
      method: 'POST',
      body: JSON.stringify({ entity_id: entityId }),
    }),
  // Also deselects it; returns the selection
  removeReference: (id: string, entityId: number) =>
    api<Selection>(`/cases/${id}/references/${entityId}`, { method: 'DELETE' }),
  getCaseChat: (id: string) => api<CaseChatTurn[]>(`/cases/${id}/chat`),
  getCaseFeedback: (id: string) => api<CaseFeedback>(`/cases/${id}/feedback`),

  setReview: (id: string, review: ReviewInput) =>
    api<Case>(`/cases/${id}/review`, { method: 'PUT', body: JSON.stringify(review) }),
  clearReview: (id: string) => api<Case>(`/cases/${id}/review`, { method: 'DELETE' }),
  listNotes: (id: string) => api<CaseNote[]>(`/cases/${id}/notes`),
  addNote: (id: string, note: { author: string; text: string }) =>
    api<CaseNote>(`/cases/${id}/notes`, { method: 'POST', body: JSON.stringify(note) }),
  deleteNote: (id: string, noteId: string) =>
    api<{ ok: boolean }>(`/cases/${id}/notes/${noteId}`, { method: 'DELETE' }),

  chat: (req: ChatRequest) =>
    api<ChatResponse>('/chat', { method: 'POST', body: JSON.stringify(req) }),
  feedback: (req: FeedbackRequest) =>
    api<{ ok: boolean }>('/feedback', { method: 'POST', body: JSON.stringify(req) }),

  listSources: () => api<Source[]>('/sources'),
  getSource: (id: string) => api<Source>(`/sources/${id}`),
  addSource: (source: NewSource) =>
    api<Source>('/sources', { method: 'POST', body: JSON.stringify(source) }),
  recrawlSource: (id: string) => api<Source>(`/sources/${id}/crawl`, { method: 'POST' }),
  getRules: (id: string) => api<CrawlRules>(`/sources/${id}/rules`),
  setRules: (id: string, rules: Record<RuleKind, string[]>) =>
    api<CrawlRules>(`/sources/${id}/rules`, { method: 'PUT', body: JSON.stringify(rules) }),

  listPages: () => api<ResourcePage[]>('/pages'),
  getPage: (id: number) => api<PageDetail>(`/pages/${id}`),
}

export type Backend = typeof realBackend

export const backend: Backend = USE_MOCK ? mockBackend : realBackend

export * from './types'
