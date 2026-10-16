// Mock agent activity feed (AgentRun entries). Synthetic only.
import type { ActivityItem } from './apiTypes.ts'
import type { Tenant } from './mockData.ts'

const MOCK_DELAY_MS = 250

type MockItem = Omit<ActivityItem, 'at'> & { minAgo: number }

const RAW: Record<Tenant, MockItem[]> = {
  acme: [
    { minAgo: 2, agent: 'Triage', case_id: 1005, summary: 'Picked up case', handed_to: 'Investigator' },
    { minAgo: 5, agent: 'Responder', case_id: 1006, summary: 'Proposed Contain Host, awaiting approval', handed_to: null },
    { minAgo: 8, agent: 'Investigator', case_id: 1006, summary: 'Built the case path (3 hosts)', handed_to: 'Responder' },
    { minAgo: 12, agent: 'Triage', case_id: 1007, summary: 'Auto-closed by playbook benign-port-scan v2', handed_to: null },
    { minAgo: 15, agent: 'Worker', case_id: 1003, summary: 'Scanning host ws-14: found 1 suspicious process', handed_to: null },
    { minAgo: 18, agent: 'Responder', case_id: 1003, summary: 'Containment action proposed (simulated)', handed_to: 'Worker' },
    { minAgo: 20, agent: 'Investigator', case_id: 1003, summary: 'Collected indicators (3 new)', handed_to: 'Responder' },
    { minAgo: 24, agent: 'Investigator', case_id: 1003, summary: 'Enriched with threat intel', handed_to: 'Triage' },
    { minAgo: 30, agent: 'Triage', case_id: 1004, summary: 'New alert from sensor-7', handed_to: 'Investigator' },
    { minAgo: 45, agent: 'Triage', case_id: 1008, summary: 'Auto-closed by playbook auto-close-credential-stuffing v1', handed_to: null },
  ],
  globex: [
    { minAgo: 5, agent: 'Responder', case_id: 2003, summary: 'Proposed Block IOC, awaiting approval', handed_to: null },
    { minAgo: 10, agent: 'Investigator', case_id: 2003, summary: 'Built the case path (2 hosts)', handed_to: 'Responder' },
    { minAgo: 12, agent: 'Triage', case_id: 2003, summary: 'Picked up case', handed_to: 'Investigator' },
  ],
}

// Timestamps are fixed once at load so `since` behaves like it will against the real API.
const LOADED_AT = Date.now()
const MOCK_ACTIVITY: Record<Tenant, ActivityItem[]> = {
  acme: RAW.acme.map(({ minAgo, ...rest }) => ({ ...rest, at: new Date(LOADED_AT - minAgo * 60_000).toISOString() })),
  globex: RAW.globex.map(({ minAgo, ...rest }) => ({ ...rest, at: new Date(LOADED_AT - minAgo * 60_000).toISOString() })),
}

/** GET /activity?since= : entries newer than `since` (ISO), newest first. */
export async function fetchActivity(tenant: Tenant, since?: string): Promise<ActivityItem[]> {
  await new Promise((resolve) => setTimeout(resolve, MOCK_DELAY_MS))
  const cutoff = since ? new Date(since).getTime() : -Infinity
  return MOCK_ACTIVITY[tenant].filter((i) => new Date(i.at).getTime() > cutoff)
}
