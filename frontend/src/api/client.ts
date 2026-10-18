// All backend calls go through here. In dev, Vite proxies /api to the backend (see vite.config.ts).
// In production, set VITE_API_BASE_URL if the backend runs on a different origin.
const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  // FormData bodies (file uploads) need the browser to set the multipart boundary itself
  const isForm = init?.body instanceof FormData
  const res = await fetch(`${BASE_URL}/api${path}`, {
    ...init,
    headers: isForm ? init?.headers : { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText}`)
  }
  return res.json() as Promise<T>
}
