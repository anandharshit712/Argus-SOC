import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import type { ActivityItem } from '../api/apiTypes.ts'
import { fetchActivity } from '../api/argusApi.ts'
import { ToolCallList } from '../components/CasePanels.tsx'
import { usePoll } from '../hooks/usePoll.ts'
import { humanize } from '../lib/caseTitle.ts'
import { clockTime } from '../lib/formatTime.ts'
import { useApp } from '../state/AppContext.tsx'
import './ActivityPage.css'

const POLL_MS = 2000
const MAX_ITEMS = 200

// Agent names as the graph stores them on AgentRun.agent.
const AGENT_FILTERS: { key: string; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'triage', label: 'Triage' },
  { key: 'investigator', label: 'Investigator' },
  { key: 'responder', label: 'Responder' },
]

const time = (i: ActivityItem) => (i.at ? new Date(i.at).getTime() : 0)
const byNewest = (a: ActivityItem, b: ActivityItem) => time(b) - time(a)
const itemKey = (i: ActivityItem) => i.id ?? `${i.at}|${i.agent}|${i.case_id}|${i.summary}`

export default function ActivityPage() {
  const { tenant, live } = useApp()
  const [agent, setAgent] = useState('all')
  const [worker, setWorker] = useState('all')
  const [caseFilter, setCaseFilter] = useState('')
  const [openCalls, setOpenCalls] = useState<string | null>(null)
  // Steps that arrived while the user was scrolled down; the newest are at the top.
  const [unseen, setUnseen] = useState(0)
  // The feed is keyed by tenant, so switching tenant starts a fresh feed without any reset step.
  const [feed, setFeed] = useState<{ tenant: string; items: ActivityItem[] }>({ tenant, items: [] })
  const sinceRef = useRef<{ tenant: string; at: string } | null>(null)

  useEffect(() => {
    const onScroll = () => {
      if (window.scrollY < 60) setUnseen(0)
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  const { error, loading } = usePoll(
    async () => {
      const forTenant = tenant
      const since = sinceRef.current?.tenant === forTenant ? sinceRef.current.at : undefined
      const fresh = await fetchActivity(forTenant, since)
      // With `since`, everything returned is new; count it if the user can't see the top.
      if (since && fresh.length > 0 && window.scrollY >= 60) setUnseen((n) => n + fresh.length)
      const newest = [...fresh].sort(byNewest).find((i) => i.at)?.at
      if (newest) sinceRef.current = { tenant: forTenant, at: newest }
      setFeed((prev) => {
        const kept = prev.tenant === forTenant ? prev.items : []
        const known = new Set(kept.map(itemKey))
        const merged = [...fresh.filter((i) => !known.has(itemKey(i))), ...kept].sort(byNewest).slice(0, MAX_ITEMS)
        return { tenant: forTenant, items: merged }
      })
      return fresh.length
    },
    POLL_MS,
    live,
    [tenant],
  )

  const items = feed.tenant === tenant ? feed.items : []
  // G11: steps from more than one agent worker show the agents sharing the work.
  const workerSteps = new Map<string, number>()
  for (const i of items) if (i.worker) workerSteps.set(i.worker, (workerSteps.get(i.worker) ?? 0) + 1)
  const workers = [...workerSteps.keys()].sort()
  const caseId = caseFilter.trim().replace(/^#/, '')
  const shown = items.filter(
    (i) =>
      (agent === 'all' || i.agent === agent) &&
      (worker === 'all' || i.worker === worker) &&
      (caseId === '' || String(i.case_id) === caseId),
  )

  return (
    <div className="activity">
      <section className="page-head">
        <h1>Agent Activity</h1>
        <p>Live feed of agent steps, handoffs and workers.</p>
        <div className="activity-filters">
          <div role="group" aria-label="Filter by agent" className="activity-filter-group">
            {AGENT_FILTERS.map((f) => (
              <button
                key={f.key}
                type="button"
                className={f.key === agent ? 'is-active' : ''}
                aria-pressed={f.key === agent}
                onClick={() => setAgent(f.key)}
              >
                {f.label}
              </button>
            ))}
          </div>
          <select value={worker} onChange={(e) => setWorker(e.target.value)} aria-label="Filter by worker">
            <option value="all">All workers ({workers.length})</option>
            {workers.map((w) => (
              <option key={w} value={w}>
                {w} ({workerSteps.get(w)} steps)
              </option>
            ))}
          </select>
          <input
            className="case-filter"
            type="search"
            inputMode="numeric"
            placeholder="Case #"
            value={caseFilter}
            onChange={(e) => setCaseFilter(e.target.value)}
            aria-label="Filter by case number"
          />
        </div>
        {/* G11: more than one worker sharing the steps is the concurrency proof. */}
        {workers.length > 0 && (
          <ul className="worker-counters" aria-label="Steps per worker">
            {workers.map((w) => (
              <li key={w}>
                <button
                  type="button"
                  className={worker === w ? 'is-active' : ''}
                  aria-pressed={worker === w}
                  onClick={() => setWorker(worker === w ? 'all' : w)}
                >
                  {w} <strong>{workerSteps.get(w)}</strong>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {unseen > 0 && (
        <button
          type="button"
          className="new-pill"
          onClick={() => {
            window.scrollTo({ top: 0, behavior: 'smooth' })
            setUnseen(0)
          }}
        >
          ↑ {unseen} new
        </button>
      )}

      {error && (
        <p className="page-error" role="alert">
          Could not refresh: {error} Showing the last data received.
        </p>
      )}

      <section className="panel activity-feed" aria-live="polite" aria-label="Agent activity">
        {loading && items.length === 0 ? (
          <p className="muted">Loading activity…</p>
        ) : shown.length === 0 ? (
          <p className="muted">No activity for this filter yet.</p>
        ) : (
          <ol>
            {shown.map((item) => {
              const key = itemKey(item)
              const calls = item.tool_calls ?? []
              return (
                <li key={key}>
                  <time dateTime={item.at ?? undefined}>{clockTime(item.at)}</time>
                  <span className={`agent-badge agent-${item.agent ?? 'unknown'}`}>
                    {item.agent ? humanize(item.agent) : 'Agent'}
                  </span>
                  <div className="activity-text">
                    <span>
                      {item.summary}
                      {item.case_id !== null && (
                        <>
                          {' '}
                          <Link to={`/cases/${item.case_id}`}>#{item.case_id}</Link>
                        </>
                      )}
                    </span>
                    <small>
                      {item.handed_to ? `Handoff → ${humanize(item.handed_to)}` : ''}
                      {item.handed_to && item.worker ? ' · ' : ''}
                      {item.worker ? `worker ${item.worker}` : ''}
                    </small>
                    {calls.length > 0 && (
                      <>
                        <button
                          type="button"
                          className="mcp-chip"
                          aria-expanded={openCalls === key}
                          onClick={() => setOpenCalls(openCalls === key ? null : key)}
                        >
                          {calls.length} MCP call{calls.length === 1 ? '' : 's'}
                        </button>
                        {openCalls === key && <ToolCallList calls={calls} />}
                      </>
                    )}
                  </div>
                </li>
              )
            })}
          </ol>
        )}
      </section>
    </div>
  )
}
