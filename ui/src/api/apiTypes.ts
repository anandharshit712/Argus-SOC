// Mirrors backend/src/argus_backend/api_models.py (LLD §7 + CONTRACT_GAPS GAP-1…6 + dashboard).
// Dates are ISO strings because that is how they arrive as JSON.

export type CaseStatus =
  | 'new'
  | 'triaged'
  | 'investigated'
  | 'awaiting_approval'
  | 'closed'
  | 'auto_closed'

export type Priority = 'critical' | 'high' | 'medium' | 'low' | 'info'

export const OPEN_STATUSES: CaseStatus[] = ['new', 'triaged', 'investigated', 'awaiting_approval']

// --- health, auth -------------------------------------------------------------

export type HealthOut = { status: 'ok' | 'degraded' | 'mock'; falkordb: boolean }

export type MeOut = { username: string; display_name: string; tenants: string[] }
export type SessionOut = MeOut & { token: string; expires_at: string }

// --- cases --------------------------------------------------------------------

export type CaseSummary = {
  id: number
  status: CaseStatus
  priority: Priority
  category: string | null
  alert_count: number
  opened_at: string | null
  updated_at: string | null
  needs_approval: boolean
  /** "<playbook name> v<version>" */
  auto_closed_by: string | null
  /** The case that playbook was learned from. */
  auto_closed_source_case: number | null
}

export type PathNode = { name: string; label: string }

export type AlertOut = {
  incident_id: string
  category: string | null
  severity: string | null
  confidence: number | null
  succeeded: boolean | null
  summary: string | null
  /** Attacker-controlled text from Talos: always rendered as plain text. */
  evidence: string[]
  /** Talos's own recommended actions ("Talos suggested"). */
  talos_actions: string[]
}

export type ToolCallOut = {
  tool: string
  args: Record<string, unknown>
  result: string | null
  why: string | null
}

export type DecisionOut = {
  id: string
  rule_id: string | null
  actions: string[]
  needs_approval: boolean
  reason: string | null
  explanation: string | null
  /** pending / approved / rejected / auto */
  outcome: string | null
  path: PathNode[]
  /** [host, score 0..1], highest first. */
  ranking: [string, number][]
  previous_priority: string | null
  target_hosts: string[]
  target_users: string[]
  target_iocs: string[]
  /** "<name> v<version>" when a playbook decided. */
  playbook: string | null
  agent: string | null
  created_at: string | null
}

export type RecallItem = { case_id: number; verdict: string | null; closed_at: string | null; note: string | null }

export type BlastRadiusItem = {
  host: string
  criticality: number
  accounts: string[]
  reached_hosts: string[]
  alerts: number
}

/** Keys written by Triage and the Investigator (GAP-6). Every key is optional. */
export type Findings = {
  recall?: RecallItem[] | null
  facts?: Record<string, Record<string, Record<string, unknown>>> | null
  linked?: string[] | null
  severity?: string | null
  memory_reasons?: string[] | null
  succeeded?: boolean | null
  path_to_crown_jewel?: boolean | null
  shortest_path?: string[] | null
  blast_radius?: BlastRadiusItem[] | null
  deep_dive?: ToolCallOut[] | null
  [extra: string]: unknown
}

export type FeedbackVerdict = 'approve' | 'reject' | 'benign'

export type FeedbackItemOut = {
  id: string
  verdict: FeedbackVerdict
  note: string
  analyst: string
  created_at: string | null
}

export type ActivityItem = {
  id: string | null
  at: string | null
  agent: string | null
  worker: string | null
  case_id: number | null
  summary: string | null
  handed_to: string | null
  tool_calls: ToolCallOut[] | null
}

export type CaseDetail = CaseSummary & {
  closed_at: string | null
  verdict: string | null
  closed_reason: string | null
  alerts: AlertOut[]
  findings: Findings
  decision: DecisionOut | null
  feedback: FeedbackItemOut[]
  agent_runs: ActivityItem[]
}

/** The analyst is not sent: the API takes it from the session (GAP-1). */
export type FeedbackIn = { verdict: FeedbackVerdict; note: string }
export type FeedbackOut = { feedback_id: string; playbook_created: string | null }

export type PlaybookOut = {
  name: string
  version: number
  active: boolean
  condition: Record<string, unknown>
  action: string | null
  source_case: number | null
  created_at: string | null
}

// --- dashboard ----------------------------------------------------------------

export type TimeWindow = '30m' | '1h' | '24h' | 'all'

export type Kpi = { value: number | null; previous: number | null }

export type DashboardOut = {
  tenant: string
  window: TimeWindow
  generated_at: string
  kpis: {
    open_cases: Kpi
    awaiting_approval: Kpi
    critical_high_open: Kpi
    auto_closed: Kpi
    auto_closed_pct: Kpi
    median_decision_seconds: Kpi
    active_playbooks: Kpi
  }
  pipeline: Record<string, number>
  buckets: { start: string; human: number; auto: number }[]
  playbook_markers: { at: string; playbook: string }[]
  needs_you: CaseSummary[]
  by_priority: Record<string, number>
  by_category: Record<string, number>
  agents: { agent: string; worker: string | null; steps: number; last_seen: string | null }[]
  recent_activity: ActivityItem[]
}
