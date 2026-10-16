// Mock data for the dashboard. Synthetic only. Replace with real calls in src/api/ later.
import { MOCK_PLAYBOOKS } from './mockPlaybooks.ts'
import { OPEN_STATUSES, type CaseSummary, type CaseStatus, type HealthOut, type Priority } from './apiTypes.ts'

export type TimeWindow = '30m' | '1h' | '24h' | 'all'

export const WINDOW_MINUTES: Record<TimeWindow, number> = {
  '30m': 30,
  '1h': 60,
  '24h': 1440,
  all: Infinity,
}

export const TENANTS = ['acme', 'globex'] as const
export type Tenant = (typeof TENANTS)[number]
export const TENANT_LABEL: Record<Tenant, string> = { acme: 'Acme', globex: 'Globex' }

export type DashboardMetrics = {
  open: number
  awaiting: number
  criticalHighOpen: number
  autoClosed: number
  autoClosedPct: number
  medianDecisionSeconds: number | null
}

export type DashboardData = {
  metrics: DashboardMetrics
  /** Same metrics for the window before this one. Null for "All". */
  previous: DashboardMetrics | null
  activePlaybooks: number
  recentCases: CaseSummary[]
}

export type MockCase = {
  id: number
  status: CaseStatus
  priority: Priority
  category: string
  alerts: number
  openedMinAgo: number
  updatedMinAgo: number
  /** Seconds from opened to the Responder's decision. Not in the contract yet (gap D1). */
  decisionSeconds?: number
}

export const MOCK_CASES: Record<Tenant, MockCase[]> = {
  acme: [
    { id: 1005, status: 'new', priority: 'low', category: 'port_scan', alerts: 1, openedMinAgo: 3, updatedMinAgo: 3 },
    { id: 1006, status: 'awaiting_approval', priority: 'high', category: 'sql_injection', alerts: 3, openedMinAgo: 20, updatedMinAgo: 8, decisionSeconds: 21 },
    { id: 1004, status: 'investigated', priority: 'high', category: 'ssh_bruteforce', alerts: 4, openedMinAgo: 25, updatedMinAgo: 10 },
    { id: 1003, status: 'awaiting_approval', priority: 'critical', category: 'malware_execution', alerts: 2, openedMinAgo: 40, updatedMinAgo: 18, decisionSeconds: 14 },
    { id: 1007, status: 'auto_closed', priority: 'low', category: 'port_scan', alerts: 1, openedMinAgo: 15, updatedMinAgo: 12, decisionSeconds: 6 },
    { id: 1002, status: 'triaged', priority: 'medium', category: 'unusual_network_traffic', alerts: 2, openedMinAgo: 55, updatedMinAgo: 32 },
    { id: 1008, status: 'auto_closed', priority: 'medium', category: 'credential_stuffing', alerts: 2, openedMinAgo: 50, updatedMinAgo: 45, decisionSeconds: 9 },
    { id: 1001, status: 'closed', priority: 'medium', category: 'phishing', alerts: 1, openedMinAgo: 90, updatedMinAgo: 60, decisionSeconds: 31 },
    { id: 1011, status: 'investigated', priority: 'critical', category: 'ransomware_behaviour', alerts: 6, openedMinAgo: 100, updatedMinAgo: 70 },
    { id: 1009, status: 'closed', priority: 'high', category: 'lateral_movement', alerts: 5, openedMinAgo: 300, updatedMinAgo: 250, decisionSeconds: 18 },
    { id: 1010, status: 'auto_closed', priority: 'low', category: 'port_scan', alerts: 1, openedMinAgo: 500, updatedMinAgo: 490, decisionSeconds: 7 },
    { id: 1012, status: 'closed', priority: 'medium', category: 'phishing', alerts: 1, openedMinAgo: 1500, updatedMinAgo: 1400, decisionSeconds: 26 },
  ],
  globex: [
    { id: 2003, status: 'awaiting_approval', priority: 'medium', category: 'credential_stuffing', alerts: 2, openedMinAgo: 12, updatedMinAgo: 5, decisionSeconds: 12 },
    { id: 2002, status: 'triaged', priority: 'low', category: 'port_scan', alerts: 1, openedMinAgo: 35, updatedMinAgo: 30 },
    { id: 2001, status: 'closed', priority: 'high', category: 'sql_injection', alerts: 3, openedMinAgo: 80, updatedMinAgo: 65, decisionSeconds: 22 },
  ],
}

const MOCK_DELAY_MS = 250

const pause = () => new Promise((resolve) => setTimeout(resolve, MOCK_DELAY_MS))

function median(values: number[]): number | null {
  if (values.length === 0) return null
  const sorted = [...values].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2
}

function computeMetrics(cases: MockCase[]): DashboardMetrics {
  const open = cases.filter((c) => OPEN_STATUSES.includes(c.status))
  const autoClosed = cases.filter((c) => c.status === 'auto_closed').length
  const closedTotal = cases.filter((c) => c.status === 'closed' || c.status === 'auto_closed').length
  return {
    open: open.length,
    awaiting: open.filter((c) => c.status === 'awaiting_approval').length,
    criticalHighOpen: open.filter((c) => c.priority === 'critical' || c.priority === 'high').length,
    autoClosed,
    autoClosedPct: closedTotal ? Math.round((autoClosed / closedTotal) * 100) : 0,
    medianDecisionSeconds: median(cases.flatMap((c) => (c.decisionSeconds ? [c.decisionSeconds] : []))),
  }
}

export function toSummary(c: MockCase): CaseSummary {
  const ago = (min: number) => new Date(Date.now() - min * 60_000).toISOString()
  return {
    id: c.id,
    status: c.status,
    priority: c.priority,
    category: c.category,
    alert_count: c.alerts,
    opened_at: ago(c.openedMinAgo),
    updated_at: ago(c.updatedMinAgo),
    needs_approval: c.status === 'awaiting_approval',
    auto_closed_by: c.status === 'auto_closed' ? 'playbook' : null,
  }
}

export async function fetchDashboard(tenant: Tenant, window: TimeWindow): Promise<DashboardData> {
  await pause()
  const cases = MOCK_CASES[tenant]
  const span = WINDOW_MINUTES[window]
  const current = cases.filter((c) => c.openedMinAgo <= span)
  const previous =
    span === Infinity ? null : cases.filter((c) => c.openedMinAgo > span && c.openedMinAgo <= span * 2)

  return {
    metrics: computeMetrics(current),
    previous: previous ? computeMetrics(previous) : null,
    activePlaybooks: MOCK_PLAYBOOKS[tenant].filter((p) => p.active).length,
    recentCases: [...cases].sort((a, b) => a.updatedMinAgo - b.updatedMinAgo).slice(0, 5).map(toSummary),
  }
}

export async function fetchCases(tenant: Tenant): Promise<CaseSummary[]> {
  await pause()
  return MOCK_CASES[tenant].map(toSummary)
}

export async function fetchHealth(): Promise<HealthOut> {
  await pause()
  return { status: 'ok', falkordb: true }
}
