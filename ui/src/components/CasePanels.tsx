import { useState } from 'react'
import type { ActivityItem, AlertOut, Findings } from '../api/apiTypes.ts'
import { timeAgo } from '../lib/formatTime.ts'

// ---------- host ranking ----------

function riskOf(score: number): { label: string; className: string } {
  if (score >= 0.7) return { label: 'High', className: 'badge-priority-high' }
  if (score >= 0.4) return { label: 'Medium', className: 'badge-priority-medium' }
  return { label: 'Low', className: 'badge-risk-low' }
}

export function HostRankingList({ ranking }: { ranking: [string, number][] }) {
  if (ranking.length === 0) return <p className="muted">No hosts ranked yet.</p>
  return (
    <table className="mini-table">
      <thead>
        <tr>
          <th>Host</th>
          <th>Risk</th>
        </tr>
      </thead>
      <tbody>
        {ranking.map(([host, score]) => {
          const risk = riskOf(score)
          return (
            <tr key={host}>
              <td>{host}</td>
              <td>
                <span className={`badge ${risk.className}`} title={`score ${score.toFixed(2)}`}>{risk.label}</span>
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

// ---------- key findings ----------

export function KeyFindingsList({ findings }: { findings: string[] }) {
  if (findings.length === 0) return <p className="muted">No findings recorded.</p>
  return (
    <ul className="finding-list">
      {findings.map((f) => (
        <li key={f}>{f}</li>
      ))}
    </ul>
  )
}

// ---------- memory and deep dive ----------

export function MemoryPanel({ findings }: { findings: Findings }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      {findings.memory.length === 0 ? (
        <p className="muted">Nothing related in memory.</p>
      ) : (
        <ul className="finding-list plain">
          {findings.memory.map((m) => (
            <li key={m}>{m}</li>
          ))}
        </ul>
      )}

      <h3>Deep Dive</h3>
      <button
        type="button"
        className="btn-outline"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        disabled={findings.deep_dive_calls.length === 0}
      >
        {open ? 'Hide MCP Tool calls' : 'Open MCP Tool'}
      </button>
      {open && (
        <ul className="mcp-calls">
          {findings.deep_dive_calls.map((call) => (
            <li key={call.tool}>
              <code>{call.tool}</code>
              <span>{call.result}</span>
            </li>
          ))}
        </ul>
      )}
    </>
  )
}

// ---------- linked alerts ----------

export function LinkedAlertsList({ alerts, expanded = false }: { alerts: AlertOut[]; expanded?: boolean }) {
  if (alerts.length === 0) return <p className="muted">No alerts linked.</p>
  return (
    <ul className="alert-list">
      {alerts.map((a) => (
        <li key={a.incident_id}>
          <div className="alert-row">
            <strong>{a.incident_id}</strong>
            <span>{a.category.replace(/_/g, ' ')}</span>
          </div>
          {expanded && (
            <div className="alert-more">
              <p>{a.summary}</p>
              <p className="muted small">
                Severity {a.severity} · confidence {Math.round(a.confidence * 100)}% ·{' '}
                {a.succeeded === null ? 'outcome unknown' : a.succeeded ? 'attack succeeded' : 'attack failed'}
              </p>
              {a.evidence.length > 0 && (
                <ul className="evidence">
                  {a.evidence.map((e) => (
                    <li key={e}>{e}</li>
                  ))}
                </ul>
              )}
              {a.talos_actions.length > 0 && (
                <p className="muted small">Talos suggested: {a.talos_actions.join(', ')}</p>
              )}
            </div>
          )}
        </li>
      ))}
    </ul>
  )
}

// ---------- timeline ----------

export function TimelineList({ runs }: { runs: ActivityItem[] }) {
  if (runs.length === 0) return <p className="muted">No agent activity yet.</p>
  return (
    <ol className="timeline">
      {runs.map((r) => (
        <li key={`${r.at}-${r.agent}`}>
          <time dateTime={r.at}>{timeAgo(r.at)}</time>
          <strong>{r.agent}</strong>
          <span>
            {r.summary}
            {r.handed_to ? ` → handed to ${r.handed_to}` : ''}
          </span>
        </li>
      ))}
    </ol>
  )
}
