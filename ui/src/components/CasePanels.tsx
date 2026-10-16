import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { ActivityItem, AlertOut, Findings, ToolCallOut } from '../api/apiTypes.ts'
import { humanize } from '../lib/caseTitle.ts'
import { timeAgo } from '../lib/formatTime.ts'

// Everything below that comes from Talos or the agents is rendered as text, never as HTML.

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
                <span className={`badge ${risk.className}`} title={`score ${score.toFixed(2)}`}>
                  {risk.label}
                </span>
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

// ---------- key findings (GAP-6 keys) ----------

function keyFindings(f: Findings): string[] {
  const out: string[] = []
  if (f.succeeded === true) out.push('The attack succeeded')
  if (f.succeeded === false) out.push('The attack did not succeed')
  if (f.path_to_crown_jewel === true) {
    out.push(f.shortest_path?.length ? `Path to a crown jewel: ${f.shortest_path.join(' → ')}` : 'A crown jewel is reachable')
  }
  if (f.path_to_crown_jewel === false) out.push('No path to a crown jewel')
  if (f.severity) out.push(`Most severe alert: ${f.severity}`)
  if (f.linked?.length) out.push(`${f.linked.length} linked alert${f.linked.length === 1 ? '' : 's'} correlated`)
  for (const b of f.blast_radius ?? []) {
    const accounts = b.accounts.length ? ` via ${b.accounts.join(', ')}` : ''
    out.push(`Blast radius from ${b.host}${accounts}: reaches ${b.reached_hosts.length} host(s)`)
  }
  return out
}

export function KeyFindingsList({ findings }: { findings: Findings }) {
  const items = keyFindings(findings)
  if (items.length === 0) return <p className="muted">No findings recorded yet.</p>
  return (
    <ul className="finding-list">
      {items.map((f) => (
        <li key={f}>{f}</li>
      ))}
    </ul>
  )
}

// ---------- memory and deep dive ----------

function factLine(name: string, facts: Record<string, unknown>): string | null {
  const parts = Object.entries(facts)
    .filter(([, v]) => v !== null && v !== false && !(Array.isArray(v) && v.length === 0))
    .map(([k, v]) => `${humanize(k).toLowerCase()}: ${Array.isArray(v) ? v.join(', ') : String(v)}`)
  return parts.length ? `${name} — ${parts.join('; ')}` : null
}

export function MemoryPanel({ findings }: { findings: Findings }) {
  const [open, setOpen] = useState(false)
  const reasons = findings.memory_reasons ?? []
  const recall = findings.recall ?? []
  const facts = Object.values(findings.facts ?? {}).flatMap((group) =>
    Object.entries(group ?? {}).flatMap(([name, f]) => factLine(name, f ?? {}) ?? []),
  )
  const calls: ToolCallOut[] = findings.deep_dive ?? []

  return (
    <>
      {reasons.length > 0 && (
        <p className="small">
          <strong>Priority raised one step because of:</strong> {reasons.join('; ')}
        </p>
      )}
      {recall.length === 0 && facts.length === 0 && reasons.length === 0 ? (
        <p className="muted">No earlier cases or facts about these hosts, accounts or IOCs.</p>
      ) : (
        <ul className="finding-list plain">
          {recall.map((r) => (
            <li key={`case-${r.case_id}`}>
              <Link to={`/cases/${r.case_id}`}>Case #{r.case_id}</Link> closed{r.verdict ? ` as ${r.verdict}` : ''}
              {r.note ? `: “${r.note}”` : ''}
            </li>
          ))}
          {facts.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      )}

      <h3>Deep Dive</h3>
      {calls.length === 0 ? (
        <p className="muted small">No MCP tool calls (the LLM deep dive is off or was not needed).</p>
      ) : (
        <>
          <button type="button" className="btn-outline" onClick={() => setOpen(!open)} aria-expanded={open}>
            {open ? 'Hide MCP tool calls' : `Show ${calls.length} MCP tool call${calls.length === 1 ? '' : 's'}`}
          </button>
          {open && <ToolCallList calls={calls} />}
        </>
      )}
    </>
  )
}

export function ToolCallList({ calls }: { calls: ToolCallOut[] }) {
  return (
    <ul className="mcp-calls">
      {calls.map((call, i) => (
        <li key={`${call.tool}-${i}`}>
          <code>
            {call.tool}({Object.entries(call.args).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(', ')})
          </code>
          {call.why && <span className="muted">Why: {call.why}</span>}
          {call.result && <span>{call.result}</span>}
        </li>
      ))}
    </ul>
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
            <span>{a.category ? humanize(a.category) : '—'}</span>
          </div>
          {expanded && (
            <div className="alert-more">
              {a.summary && <p>{a.summary}</p>}
              <p className="muted small">
                Severity {a.severity ?? '—'}
                {a.confidence !== null && ` · confidence ${Math.round(a.confidence * 100)}%`} ·{' '}
                {a.succeeded === null ? 'outcome unknown' : a.succeeded ? 'attack succeeded' : 'attack failed'}
              </p>
              {a.evidence.length > 0 && (
                <ul className="evidence">
                  {a.evidence.map((e, i) => (
                    <li key={i}>{e}</li>
                  ))}
                </ul>
              )}
              {a.talos_actions.length > 0 && (
                <p className="muted small">Talos suggested: {a.talos_actions.join('; ')}</p>
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
      {runs.map((r, i) => (
        <li key={r.id ?? i}>
          <time dateTime={r.at ?? undefined}>{timeAgo(r.at)}</time>
          <strong>
            {r.agent ? humanize(r.agent) : '—'}
            {r.worker && <small className="muted"> · {r.worker}</small>}
          </strong>
          <span>
            {r.summary}
            {r.handed_to ? ` → handed to ${humanize(r.handed_to)}` : ''}
            {r.tool_calls?.length ? ` (${r.tool_calls.length} MCP calls)` : ''}
          </span>
        </li>
      ))}
    </ol>
  )
}
