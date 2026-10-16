// Mock playbooks, one list per tenant. Synthetic only.
import type { PlaybookOut } from './apiTypes.ts'
import type { Tenant } from './mockData.ts'

const MOCK_DELAY_MS = 250
const daysAgo = (days: number) => new Date(Date.now() - days * 86_400_000).toISOString()

export const MOCK_PLAYBOOKS: Record<Tenant, PlaybookOut[]> = {
  acme: [
    { name: 'benign-port-scan', version: 2, active: true, condition: { category: 'port_scan', source_host: 'scanner-01' }, source_case: 1007, created_at: daysAgo(1) },
    { name: 'benign-port-scan', version: 1, active: false, condition: { category: 'port_scan', source_host: 'scanner-01' }, source_case: 1010, created_at: daysAgo(3) },
    { name: 'auto-close-credential-stuffing', version: 1, active: true, condition: { category: 'credential_stuffing', source_range: '198.51.100.0/24' }, source_case: 1008, created_at: daysAgo(2) },
  ],
  globex: [
    { name: 'benign-sql-injection-test', version: 1, active: true, condition: { category: 'sql_injection', source_host: 'qa-scanner-02' }, source_case: 2001, created_at: daysAgo(2) },
  ],
}

export async function fetchPlaybooks(tenant: Tenant): Promise<PlaybookOut[]> {
  await new Promise((resolve) => setTimeout(resolve, MOCK_DELAY_MS))
  return MOCK_PLAYBOOKS[tenant]
}
