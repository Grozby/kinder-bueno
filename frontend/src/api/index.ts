// Typed backend endpoints. Until the backend serves them, an in-memory mock answers instead:
// set VITE_USE_MOCK=false to talk to the real backend.
// /chat and /feedback follow docs/PLAN.md section 8.9; the rest is in docs/FRONTEND_API.md.
import { api } from './client'
import { mockBackend } from './mock'
import type {
  Case,
  CaseStatus,
  ChatRequest,
  ChatResponse,
  FeedbackRequest,
  NewSource,
  Pitch,
  Result,
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

  chat: (req: ChatRequest) =>
    api<ChatResponse>('/chat', { method: 'POST', body: JSON.stringify(req) }),
  feedback: (req: FeedbackRequest) =>
    api<{ ok: boolean }>('/feedback', { method: 'POST', body: JSON.stringify(req) }),

  listSources: () => api<Source[]>('/sources'),
  getSource: (id: string) => api<Source>(`/sources/${id}`),
  addSource: (source: NewSource) =>
    api<Source>('/sources', { method: 'POST', body: JSON.stringify(source) }),
}

export type Backend = typeof realBackend

export const backend: Backend = USE_MOCK ? mockBackend : realBackend

export * from './types'
