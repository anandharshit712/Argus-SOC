import type { CaseStatus, Priority } from '../api/apiTypes.ts'
import './CaseBadges.css'

const STATUS_LABEL: Record<CaseStatus, string> = {
  new: 'New',
  triaged: 'Triaged',
  investigated: 'Investigated',
  awaiting_approval: 'Awaiting approval',
  closed: 'Closed',
  auto_closed: 'Auto-closed',
}

const PRIORITY_LABEL: Record<Priority, string> = {
  critical: 'Critical',
  high: 'High',
  medium: 'Medium',
  low: 'Low',
  info: 'Info',
}

// The text label always carries the meaning; colour only reinforces it.
export function PriorityBadge({ priority }: { priority: Priority }) {
  return <span className={`badge badge-priority-${priority}`}>{PRIORITY_LABEL[priority] ?? priority}</span>
}

export function StatusBadge({ status }: { status: CaseStatus }) {
  return <span className={`badge badge-status-${status}`}>{STATUS_LABEL[status] ?? status}</span>
}
