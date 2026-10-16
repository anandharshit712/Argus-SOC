import { Link } from 'react-router-dom'
import type { CaseSummary } from '../api/apiTypes.ts'
import { caseTitle } from '../lib/caseTitle.ts'
import { timeAgo } from '../lib/formatTime.ts'
import { PriorityBadge, StatusBadge } from './CaseBadges.tsx'
import './CaseTable.css'

type CaseTableProps = { cases: CaseSummary[]; emptyText?: string }

export function CaseTable({ cases, emptyText = 'No cases yet.' }: CaseTableProps) {
  if (cases.length === 0) return <p className="case-empty">{emptyText}</p>

  return (
    <div className="case-table-wrap">
      <table className="case-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>Title</th>
            <th>Priority</th>
            <th>Status</th>
            <th>Updated</th>
          </tr>
        </thead>
        <tbody>
          {cases.map((c) => (
            <tr key={c.id}>
              <td>
                <Link to={`/cases/${c.id}`}>#{c.id}</Link>
              </td>
              <td>
                <Link to={`/cases/${c.id}`}>{caseTitle(c.category)}</Link>
              </td>
              <td><PriorityBadge priority={c.priority} /></td>
              <td><StatusBadge status={c.status} /></td>
              <td>{timeAgo(c.updated_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
