// Mirrors the frozen UI contract in src/argus_soc/api/api_models.py (LLD §7).
// Dates are ISO strings because that is how they arrive as JSON.

export type CaseStatus =
  | 'new'
  | 'triaged'
  | 'investigated'
  | 'awaiting_approval'
  | 'closed'
  | 'auto_closed'

export type Priority = 'critical' | 'high' | 'medium' | 'low'

export type CaseSummary = {
  id: number
  status: CaseStatus
  priority: Priority
  category: string
  alert_count: number
  opened_at: string
  updated_at: string
  needs_approval: boolean
  auto_closed_by: string | null
}

// GET /api/health
export type HealthOut = { status: 'ok' | 'degraded'; falkordb: boolean }

export const OPEN_STATUSES: CaseStatus[] = ['new', 'triaged', 'investigated', 'awaiting_approval']

export type PathNode = { name: string; label: string }

export type AlertOut = {
  incident_id: string
  category: string
  severity: string
  confidence: number
  succeeded: boolean | null
  summary: string
  evidence: string[]
  talos_actions: string[]
}

export type DecisionOut = {
  id: string
  rule_id: string
  actions: string[]
  needs_approval: boolean
  reason: string
  explanation: string
  outcome: string
  path: PathNode[]
  /** [host, score 0..1], highest first. */
  ranking: [string, number][]
}

export type ActivityItem = {
  at: string
  agent: string
  case_id: number | null
  summary: string
  handed_to: string | null
}

export type PlaybookOut = {
  name: string
  version: number
  active: boolean
  condition: Record<string, string>
  source_case: number | null
  created_at: string
}

export type FeedbackVerdict ='approve' | 'reject' | 'benign'

export type FeedbackIn = { verdict: FeedbackVerdict; note: string; analyst: string }
export type FeedbackOut = { feedback_id: string; playbook_created: string | null }
export type FeedbackRecord = { feedback_id: string; verdict: FeedbackVerdict; note: string; analyst: string; at: string }

// The contract types `findings` as a free-form dict. This shape is what the UI mock assumes and
// still has to be agreed with A, who writes these fields.
export type Findings = {
  key_findings: string[]
  memory: string[]
  deep_dive_calls: { tool: string; result: string }[]
}

export type CaseDetail = CaseSummary & {
  alerts: AlertOut[]
  findings: Findings
  decision: DecisionOut | null
  feedback: FeedbackRecord[]
  agent_runs: ActivityItem[]
}
