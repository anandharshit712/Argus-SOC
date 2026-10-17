import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { ActivityItem, AlertOut, Findings, ToolCallOut } from '../api/apiTypes.ts'
import { humanize } from '../lib/caseTitle.ts'
import { timeAgo } from '../lib/formatTime.ts'

// Everything below that comes from Talos or the agents is rendered as text, never as HTML.

// ---------- host ranking (UI_PAGES §4.5) ----------

type HostRankingProps = { ranking: [string, number][]; isolates: boolean }

export function HostRankingList({ ranking, isolates }: HostRankingProps) {
  if (ranking.length === 0) return <p className="muted">No hosts ranked yet.</p>
  return (
    <ul className="ranking-list" title="Centrality in the case subgraph × criticality">
      {ranking.map(([host, score], i) => (
        <li key={host}>
          <span className="ranking-host">
            {host}
            {i === 0 && isolates && <span className="target-tag">isolation target</span>}
          </span>
          <span className="ranking-bar" aria-hidden="true">
            <span style={{ width: `${Math.max(2, Math.min(1, score) * 100)}%` }} />
          </span>
          <span className="ranking-score">{score.toFixed(2)}</span>
        </li>
      ))}
    </ul>
  )
}

// ---------- findings (UI_PAGES §4.6, GAP-6 keys) ----------

const SHOWN_KEYS = new Set([
  'recall', 'facts', 'linked', 'severity', 'memory_reasons', 'succeeded',
  'path_to_crown_jewel', 'shortest_path', 'blast_radius', 'deep_dive',
])

const yesNo = (v: boolean | null | undefined) => (v === true ? 'Yes' : v === false ? 'No' : '—')

export function FindingsPanel({ findings: f }: { findings: Findings }) {
  const other = Object.entries(f).filter(([k, v]) => !SHOWN_KEYS.has(k) && v !== null && v !== undefined)
  const nothing = f.succeeded == null && f.path_to_crown_jewel == null && !f.severity && !f.blast_radius?.length
  if (nothing && other.length === 0) return <p className="muted">No findings recorded yet.</p>

  return (
    <div className="findings">
      <dl className="finding-facts">
        <div>
          <dt>Attack succeeded</dt>
          <dd className={f.succeeded ? 'is-bad' : undefined}>
            <strong>{yesNo(f.succeeded)}</strong>
          </dd>
        </div>
        <div>
          <dt>Path to crown jewel</dt>
          <dd>{yesNo(f.path_to_crown_jewel)}</dd>
        </div>
        {f.shortest_path?.length ? (
          <div>
            <dt>Shortest path</dt>
            <dd>{f.shortest_path.join(' → ')}</dd>
          </div>
        ) : null}
        {f.severity && (
          <div>
            <dt>Most severe alert</dt>
            <dd>{f.severity}</dd>
          </div>
        )}
      </dl>

      {f.blast_radius?.length ? (
        <>
          <h3>Blast radius</h3>
          {/* A list, not a table: this panel is narrow on the overview. */}
          <ul className="blast-list">
            {f.blast_radius.map((b) => (
              <li key={b.host}>
                <strong>{b.host}</strong> <span className="muted">criticality {b.criticality}</span>
                <span>Accounts: {b.accounts.join(', ') || '—'}</span>
                <span>Reaches: {b.reached_hosts.join(', ') || '—'}</span>
                <span className="muted">
                  {b.alerts} alert{b.alerts === 1 ? '' : 's'}
                </span>
              </li>
            ))}
          </ul>
        </>
      ) : null}

      {other.length > 0 && (
        <details className="raw-findings">
          <summary>Other findings ({other.length})</summary>
          <pre>{JSON.stringify(Object.fromEntries(other), null, 2)}</pre>
        </details>
      )}
    </div>
  )
}

// ---------- memory (UI_PAGES §4.7, G4 / G10) ----------

const caseList = (ids: unknown) => (Array.isArray(ids) ? ids.map((id) => `#${id}`).join(', ') : '')

/** "svc_deploy — suspected compromised (Case 31)", "10.0.5.20 — owner: internal pentest scanner". */
function factLine(kind: string, name: string, facts: Record<string, unknown>): string | null {
  const parts: string[] = []
  for (const [key, value] of Object.entries(facts)) {
    if (value === null || value === false || value === 'unknown' || (Array.isArray(value) && value.length === 0)) continue
    if (key === 'targeted_case_ids' && Array.isArray(value)) {
      parts.push(`targeted in ${value.length} ${value.length === 1 ? 'case' : 'cases'} (${caseList(value)})`)
    } else if (key === 'seen_case_ids' && Array.isArray(value)) {
      parts.push(`seen in ${value.length} ${value.length === 1 ? 'case' : 'cases'} (${caseList(value)})`)
    } else if (key === 'suspected_compromised') {
      parts.push(`suspected compromised${facts.suspect_case_id != null ? ` (Case ${facts.suspect_case_id})` : ''}`)
    } else if (key === 'owner') {
      parts.push(`owner: ${String(value)}`)
    } else if (key === 'verdict') {
      parts.push(`verdict: ${String(value)}`)
    } else if (key.endsWith('_at') || key === 'suspect_case_id' || key === 'first_seen' || key === 'last_seen') {
      continue // timestamps and ids already folded into the phrases above
    } else {
      parts.push(`${humanize(key).toLowerCase()}: ${Array.isArray(value) ? value.join(', ') : String(value)}`)
    }
  }
  return parts.length ? `${kind === 'iocs' ? 'IOC ' : ''}${name} — ${parts.join('; ')}` : null
}

export function MemoryPanel({ findings }: { findings: Findings }) {
  const reasons = findings.memory_reasons ?? []
  const recall = findings.recall ?? []
  const facts = Object.entries(findings.facts ?? {}).flatMap(([kind, group]) =>
    Object.entries(group ?? {}).flatMap(([name, f]) => factLine(kind, name, f ?? {}) ?? []),
  )

  return (
    <div className="memory">
      {reasons.length > 0 && (
        <p className="memory-raise">
          <strong>Priority raised one step because of:</strong> {reasons.join('; ')}
        </p>
      )}

      <h3>Past cases</h3>
      {recall.length === 0 ? (
        // In Globex this is the tenant isolation proof (G7): keep the wording exact and visible.
        <p className="memory-empty">No earlier cases with these hosts, users or IOCs</p>
      ) : (
        <ul className="finding-list plain">
          {recall.map((r) => (
            <li key={`case-${r.case_id}`}>
              <Link to={`/cases/${r.case_id}`}>Case #{r.case_id}</Link> closed{r.verdict ? ` as ${r.verdict}` : ''}
              {r.closed_at ? ` ${timeAgo(r.closed_at)}` : ''}
              {r.note ? `: “${r.note}”` : ''}
            </li>
          ))}
        </ul>
      )}

      <h3>Known facts</h3>
      {facts.length === 0 ? (
        <p className="muted small">Nothing remembered about these hosts, users or IOCs.</p>
      ) : (
        <ul className="finding-list plain">
          {facts.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

// ---------- deep dive (UI_PAGES §4.9, G9) ----------

export function DeepDivePanel({ calls }: { calls: ToolCallOut[] | null | undefined }) {
  // The Investigator writes [] when the LLM is off or it needed no extra calls; null = not run yet.
  if (!calls || calls.length === 0) {
    return (
      <p className="muted small">
        {calls ? 'No extra tool calls (deep dive off or not needed)' : 'Not investigated yet'}
      </p>
    )
  }
  return (
    <>
      <p className="muted small">Evidence only — the decision table does not read this.</p>
      <ToolCallList calls={calls} numbered />
    </>
  )
}

function ToolResult({ text }: { text: string }) {
  const [open, setOpen] = useState(false)
  const long = text.length > 200
  return (
    <span className="tool-result">
      {open || !long ? text : `${text.slice(0, 200)}…`}
      {long && (
        <button type="button" className="link-button" onClick={() => setOpen(!open)}>
          {open ? 'less' : 'more'}
        </button>
      )}
    </span>
  )
}

export function ToolCallList({ calls, numbered = false }: { calls: ToolCallOut[]; numbered?: boolean }) {
  return (
    <ol className={`mcp-calls${numbered ? ' is-numbered' : ''}`}>
      {calls.map((call, i) => (
        <li key={`${call.tool}-${i}`}>
          <code>
            {call.tool}({Object.entries(call.args).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(', ')})
          </code>
          {call.why && <span className="muted">Why: {call.why}</span>}
          {call.result && <ToolResult text={call.result} />}
        </li>
      ))}
    </ol>
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
              {a.talos_actions.length > 0 && <p className="muted small">Talos suggested: {a.talos_actions.join('; ')}</p>}
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
