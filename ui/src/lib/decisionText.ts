import type { CaseDetail, DecisionOut } from '../api/apiTypes.ts'
import { humanize } from './caseTitle.ts'

const list = (values: string[]) => values.join(', ')
const plural = (n: number, one: string, many: string) => (n === 1 ? one : many)

/** One line per decision-table action, naming what it acts on (UI_PAGES §4.3). */
export function actionLine(action: string, d: DecisionOut, path: string[]): string {
  switch (action) {
    case 'isolate_top_host':
      return d.target_hosts.length ? `Isolate host ${list(d.target_hosts)}` : 'Isolate the top-ranked host'
    case 'disable_accounts':
      return d.target_users.length
        ? `Disable ${plural(d.target_users.length, 'account', 'accounts')} ${list(d.target_users)}`
        : 'Disable the compromised accounts'
    case 'block_ips':
      return d.target_iocs.length
        ? `Block ${plural(d.target_iocs.length, 'IP', 'IPs')} ${list(d.target_iocs)}`
        : 'Block the source IPs'
    case 'block_or_rate_limit_ips':
      return d.target_iocs.length ? `Block or rate-limit ${list(d.target_iocs)}` : 'Block or rate-limit the source IPs'
    case 'watch_path_hosts':
      return path.length ? `Watch the path hosts ${list(path)}` : 'Watch the hosts on the path'
    case 'open_hunt_ticket':
      return 'Open a threat-hunt ticket'
    case 'open_ticket':
      return 'Open a ticket'
    default:
      return humanize(action)
  }
}

/** Talos's own recommendations, deduplicated across the case's alerts. */
export function talosSuggestions(detail: CaseDetail): string[] {
  return [...new Set(detail.alerts.flatMap((a) => a.talos_actions))]
}
