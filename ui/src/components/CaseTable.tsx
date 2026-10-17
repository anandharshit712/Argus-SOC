import { Link } from 'react-router-dom'
import type { CaseSummary } from '../api/apiTypes.ts'
import { caseTitle } from '../lib/caseTitle.ts'
import { timeAgo } from '../lib/formatTime.ts'
import { PriorityBadge, StatusBadge } from './CaseBadges.tsx'
import './CaseTable.css'

type CaseTableProps = {
  cases: CaseSummary[]
  emptyText?: string
  /** Fewer columns, for narrow panels. */
  compact?: boolean
}

function AutoClosedNote({ c }: { c: CaseSummary }) {
  if (!c.auto_closed_by) return null
  return (
    <small className="row-note">
      by {c.auto_closed_by}
      {c.auto_closed_source_case !== null && <> (Case {c.auto_closed_source_case})</>}
    </small>
  )
}

export function CaseTable({ cases, emptyText = 'No cases yet.', compact = false }: CaseTableProps) {
  if (cases.length === 0) return <p className="case-empty">{emptyText}</p>

  return (
    <div className="case-table-wrap">
      <table className="case-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>Title</th>
            <th>Priority</th>
            {!compact && <th>Status</th>}
            {!compact && <th>Alerts</th>}
            <th>Opened</th>
            {!compact && <th>Updated</th>}
          </tr>
        </thead>
        <tbody>
          {cases.map((c) => (
            // The key includes updated_at, so a new or changed row re-mounts and flashes once.
            <tr key={`${c.id}-${c.updated_at}`} className="row-flash">
              <td>
                <Link to={`/cases/${c.id}`}>#{c.id}</Link>
              </td>
              <td>
                <Link to={`/cases/${c.id}`}>{caseTitle(c.category)}</Link>
                {!compact && <AutoClosedNote c={c} />}
              </td>
              <td>
                <PriorityBadge priority={c.priority} />
              </td>
              {!compact && (
                <td>
                  <StatusBadge status={c.status} />
                  {c.needs_approval && <span className="needs-approval">Needs approval</span>}
                </td>
              )}
              {!compact && <td className="num">{c.alert_count}</td>}
              <td>{timeAgo(c.opened_at)}</td>
              {!compact && <td>{timeAgo(c.updated_at)}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
