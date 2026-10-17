// Every backend endpoint the UI uses (backend/README.md). Tenant ids go into the path encoded.
import { ApiError, apiRequest } from './apiClient.ts'
import type {
  ActivityItem,
  CaseDetail,
  CaseSummary,
  DashboardOut,
  FeedbackIn,
  FeedbackOut,
  HealthOut,
  MeOut,
  PlaybookOut,
  SessionOut,
  TimeWindow,
} from './apiTypes.ts'

const t = (tenant: string) => `/${encodeURIComponent(tenant)}`

// --- open -----------------------------------------------------------------------

export const fetchHealth = () => apiRequest<HealthOut>('/health', { auth: false })

export const login = (username: string, password: string) =>
  apiRequest<SessionOut>('/auth/login', { method: 'POST', body: { username, password }, auth: false })

// --- signed in --------------------------------------------------------------------

export const fetchMe = () => apiRequest<MeOut>('/auth/me')

export const logout = () => apiRequest<void>('/auth/logout', { method: 'POST' })

export const fetchCases = (tenant: string, limit = 500, status?: string) =>
  apiRequest<CaseSummary[]>(`${t(tenant)}/cases`, { query: { limit, status } })

/** The case, or null when it does not exist for this tenant. */
export async function fetchCaseDetail(tenant: string, caseId: number): Promise<CaseDetail | null> {
  try {
    return await apiRequest<CaseDetail>(`${t(tenant)}/cases/${caseId}`)
  } catch (err) {
    if (err instanceof ApiError && (err.status === 404 || err.status === 422)) return null
    throw err
  }
}

export const submitFeedback = (tenant: string, caseId: number, feedback: FeedbackIn) =>
  apiRequest<FeedbackOut>(`${t(tenant)}/cases/${caseId}/feedback`, { method: 'POST', body: feedback })

export const fetchPlaybooks = (tenant: string) => apiRequest<PlaybookOut[]>(`${t(tenant)}/playbooks`)

/** Agent steps after `since` (ISO), oldest first. */
export const fetchActivity = (tenant: string, since?: string) =>
  apiRequest<ActivityItem[]>(`${t(tenant)}/activity`, { query: { since } })

export const fetchDashboard = (tenant: string, window: TimeWindow) =>
  apiRequest<DashboardOut>(`${t(tenant)}/dashboard`, { query: { window } })
