// Mock case detail and feedback. Synthetic only; external addresses use documentation ranges.
import type {
  ActivityItem,
  AlertOut,
  CaseDetail,
  DecisionOut,
  FeedbackIn,
  FeedbackOut,
  FeedbackRecord,
  Findings,
  PathNode,
} from './apiTypes.ts'
import { MOCK_CASES, toSummary, type MockCase, type Tenant } from './mockData.ts'
import { caseTitle } from '../lib/caseTitle.ts'

const MOCK_DELAY_MS = 250
const pause = () => new Promise((resolve) => setTimeout(resolve, MOCK_DELAY_MS))
const minutesAgo = (min: number) => new Date(Date.now() - min * 60_000).toISOString()

const DEFAULT_PATH: PathNode[] = [
  { name: 'jdoe', label: 'User' },
  { name: 'ws-14', label: 'Host' },
  { name: 'app-02', label: 'Host' },
  { name: 'db-prod-01', label: 'Host' },
]

const DEFAULT_RANKING: [string, number][] = [
  ['ws-14.acme.local', 0.82],
  ['app-02.acme.local', 0.55],
  ['db-prod-01.acme.local', 0.21],
]

// Hand-written detail for the demo cases; every other case gets generated detail below.
const RICH: Record<number, { alerts: AlertOut[]; findings: Findings; decision: DecisionOut }> = {
  1003: {
    alerts: [
      { incident_id: 'AL-4821', category: 'c2_beacon', severity: 'critical', confidence: 0.92, succeeded: true, summary: 'Periodic outbound beacon to a known C2 address', evidence: ['203.0.113.45:443 every 60 s', 'JA3 matches known family'], talos_actions: ['Isolate host'] },
      { incident_id: 'AL-4760', category: 'unusual_traffic', severity: 'high', confidence: 0.74, succeeded: null, summary: 'Unusual outbound traffic on TCP 443', evidence: ['2.1 GB sent in 10 min'], talos_actions: ['Monitor'] },
      { incident_id: 'AL-4729', category: 'dns_tunneling', severity: 'medium', confidence: 0.66, succeeded: null, summary: 'High-entropy DNS queries', evidence: ['412 TXT queries to one domain'], talos_actions: ['Block domain'] },
    ],
    findings: {
      key_findings: ['C2 beacon detected (known family)', 'Unusual outbound traffic (TCP 443)', 'Matches historical pattern (82% confidence)'],
      memory: ["Related to past campaign ('winter-rose')"],
      deep_dive_calls: [
        { tool: 'get_host_neighbours', result: 'ws-14 connects to app-02 and db-prod-01' },
        { tool: 'get_entity_facts', result: "ws-14 flagged in campaign 'winter-rose'" },
      ],
    },
    decision: {
      id: 'D-1003',
      rule_id: 'R3',
      actions: ['Contain Host', 'Block IOC', 'Increase Monitoring'],
      needs_approval: true,
      reason: 'Critical asset reachable from a compromised host',
      explanation:
        'This appears to be a C2 beacon using a known malware family. Recommend containment and further investigation.',
      outcome: 'awaiting_approval',
      path: [
        { name: 'jdoe', label: 'User' },
        { name: 'ws-14', label: 'Host' },
        { name: 'app-02', label: 'Host' },
        { name: 'db-prod-01', label: 'Host' },
      ],
      ranking: [
        ['web-12.acme.local', 0.86],
        ['192.168.1.45', 0.55],
        ['db-03.acme.local', 0.2],
      ],
    },
  },
}

function generatedAlerts(c: MockCase): AlertOut[] {
  return Array.from({ length: c.alerts }, (_, i) => ({
    incident_id: `AL-${c.id * 4 + i}`,
    category: c.category,
    severity: c.priority,
    confidence: 0.8,
    succeeded: null,
    summary: `${caseTitle(c.category)} observed`,
    evidence: ['synthetic evidence line'],
    talos_actions: ['Investigate'],
  }))
}

function generatedDecision(c: MockCase): DecisionOut {
  const awaiting = c.status === 'awaiting_approval'
  return {
    id: `D-${c.id}`,
    rule_id: awaiting ? 'R3' : 'R2',
    actions: awaiting ? ['Contain Host', 'Block IOC'] : ['Increase Monitoring'],
    needs_approval: awaiting,
    reason: 'Matched the decision table',
    explanation: `${caseTitle(c.category)}: decision taken from graph evidence.`,
    outcome: c.status,
    path: DEFAULT_PATH,
    ranking: DEFAULT_RANKING,
  }
}

function generatedRuns(c: MockCase): ActivityItem[] {
  const runs: ActivityItem[] = [
    { at: minutesAgo(c.openedMinAgo), agent: 'Triage', case_id: c.id, summary: 'Picked up case', handed_to: 'Investigator' },
  ]
  if (c.status !== 'new' && c.status !== 'triaged') {
    runs.push({ at: minutesAgo(Math.max(c.openedMinAgo - 2, c.updatedMinAgo)), agent: 'Investigator', case_id: c.id, summary: 'Built the case path', handed_to: 'Responder' })
    runs.push({ at: minutesAgo(c.updatedMinAgo), agent: 'Responder', case_id: c.id, summary: 'Recorded decision', handed_to: null })
  }
  return runs
}

const FEEDBACK: Record<string, FeedbackRecord[]> = {}
const feedbackKey = (tenant: Tenant, id: number) => `${tenant}:${id}`

export async function fetchCaseDetail(tenant: Tenant, id: number): Promise<CaseDetail | null> {
  await pause()
  const c = MOCK_CASES[tenant].find((x) => x.id === id)
  if (!c) return null

  const rich = RICH[c.id]
  const hasDecision = c.status !== 'new' && c.status !== 'triaged'
  return {
    ...toSummary(c),
    alerts: rich?.alerts ?? generatedAlerts(c),
    findings: rich?.findings ?? {
      key_findings: [`${caseTitle(c.category)} detected`],
      memory: [],
      deep_dive_calls: [],
    },
    decision: rich?.decision ?? (hasDecision ? generatedDecision(c) : null),
    feedback: FEEDBACK[feedbackKey(tenant, id)] ?? [],
    agent_runs: generatedRuns(c),
  }
}

export async function submitFeedback(tenant: Tenant, id: number, input: FeedbackIn): Promise<FeedbackOut> {
  await pause()
  const c = MOCK_CASES[tenant].find((x) => x.id === id)
  if (!c) throw new Error('Case not found.')

  const awaiting = c.status === 'awaiting_approval'
  const closed = c.status === 'closed' || c.status === 'auto_closed'
  const allowed = input.verdict === 'benign' ? awaiting || closed : awaiting
  if (!allowed) throw new Error('This case is not awaiting approval.')

  const record: FeedbackRecord = {
    feedback_id: `F-${Date.now()}`,
    verdict: input.verdict,
    note: input.note,
    analyst: input.analyst,
    at: new Date().toISOString(),
  }
  const key = feedbackKey(tenant, id)
  FEEDBACK[key] = [...(FEEDBACK[key] ?? []), record]
  if (awaiting) c.status = 'closed'

  return {
    feedback_id: record.feedback_id,
    playbook_created: input.verdict === 'benign' ? `benign-${c.category} v1` : null,
  }
}
