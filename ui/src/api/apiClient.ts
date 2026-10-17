// One place that calls the backend API. Same origin in every environment: Vite's dev proxy
// (vite.config.ts) or nginx in Compose forwards /api to the backend, so there is no base URL.
import type { SessionOut } from './apiTypes.ts'

const SESSION_KEY = 'argus.session'
const UNAUTHORIZED_EVENT = 'argus:unauthorized'

export class ApiError extends Error {
  /** HTTP status, or 0 when the server could not be reached. */
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

// --- session (sessionStorage: closing the tab signs out, UI_PAGES §1.4) -------------

export function loadSession(): SessionOut | null {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY)
    if (!raw) return null
    const session = JSON.parse(raw) as SessionOut
    return new Date(session.expires_at).getTime() > Date.now() ? session : null
  } catch {
    return null
  }
}

export function saveSession(session: SessionOut | null): void {
  try {
    if (session) sessionStorage.setItem(SESSION_KEY, JSON.stringify(session))
    else sessionStorage.removeItem(SESSION_KEY)
  } catch {
    // Storage blocked (private mode): the session then lasts until the page reloads.
  }
}

/** Called whenever the API answers 401; the app goes back to the sign-in page. */
export function onUnauthorized(handler: () => void): () => void {
  window.addEventListener(UNAUTHORIZED_EVENT, handler)
  return () => window.removeEventListener(UNAUTHORIZED_EVENT, handler)
}

// --- requests -----------------------------------------------------------------------

type RequestOptions = {
  method?: 'GET' | 'POST'
  body?: unknown
  query?: Record<string, string | number | undefined>
  /** Send the session token (every call except health and login). */
  auth?: boolean
}

function errorMessage(status: number, payload: unknown): string {
  const detail = (payload as { detail?: unknown } | null)?.detail
  if (typeof detail === 'string') return detail
  // 422: FastAPI sends a list of {loc, msg}.
  if (Array.isArray(detail)) return detail.map((d) => (d as { msg?: string }).msg ?? 'Invalid value').join('; ')
  return status >= 500 ? 'The server had a problem; try again shortly.' : `Request failed (${status}).`
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, query, auth = true } = options
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined) params.set(key, String(value))
  }
  const url = `/api${path}${params.size ? `?${params}` : ''}`

  const headers: Record<string, string> = { Accept: 'application/json' }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  const token = auth ? loadSession()?.token : undefined
  if (token) headers.Authorization = `Bearer ${token}`

  let response: Response
  try {
    response = await fetch(url, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) })
  } catch {
    throw new ApiError(0, 'Can’t reach the server.')
  }

  if (response.status === 204) return undefined as T
  const payload: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    if (response.status === 401 && auth) {
      saveSession(null)
      window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
    }
    throw new ApiError(response.status, errorMessage(response.status, payload))
  }
  return payload as T
}
