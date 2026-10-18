// All backend calls go through here. In dev, Vite proxies /api to the backend (see vite.config.ts).
// In production, set VITE_API_BASE_URL if the backend runs on a different origin.
const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

// A URL for the browser itself (download links): same base as the fetch calls
export function apiUrl(path: string): string {
  return `${BASE_URL}/api${path}`
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  // FormData bodies (file uploads) need the browser to set the multipart boundary itself
  const isForm = init?.body instanceof FormData
  const res = await fetch(`${BASE_URL}/api${path}`, {
    ...init,
    headers: isForm ? init?.headers : { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!res.ok) {
    // FastAPI says why in `detail` (e.g. 409 "Another source is being ingested", 422 "include_patterns: ...")
    const body = await res.json().catch(() => null)
    const detail = typeof body?.detail === 'string' ? body.detail : res.statusText
    throw new Error(`${res.status} ${detail}`)
  }
  return res.json() as Promise<T>
}
