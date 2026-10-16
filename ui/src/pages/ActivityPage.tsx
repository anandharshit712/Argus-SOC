import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import type { ActivityItem } from '../api/apiTypes.ts'
import { fetchActivity } from '../api/mockActivity.ts'
import type { Tenant } from '../api/mockData.ts'
import { usePoll } from '../hooks/usePoll.ts'
import { useApp } from '../state/AppContext.tsx'
import './ActivityPage.css'

const POLL_MS = 2000
const MAX_ITEMS = 200

type AgentFilter = 'all' | 'Triage' | 'Investigator' | 'Responder' | 'Worker'

const FILTERS: { key: AgentFilter; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'Triage', label: 'Triage' },
  { key: 'Investigator', label: 'Investigator' },
  { key: 'Responder', label: 'Responder' },
  { key: 'Worker', label: 'Workers' },
]

const clock = (iso: string) =>
  new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })

const byNewest = (a: ActivityItem, b: ActivityItem) => new Date(b.at).getTime() - new Date(a.at).getTime()
const itemKey = (i: ActivityItem) => `${i.at}|${i.agent}|${i.case_id}|${i.summary}`

export default function ActivityPage() {
  const { tenant, live } = useApp()
  const [filter, setFilter] = useState<AgentFilter>('all')
  // The feed is keyed by tenant, so switching tenant starts a fresh feed without any reset step.
  const [feed, setFeed] = useState<{ tenant: Tenant; items: ActivityItem[] }>({ tenant, items: [] })
  const sinceRef = useRef<{ tenant: Tenant; at: string } | null>(null)

  const { error, loading } = usePoll(
    async () => {
      const forTenant = tenant
      const since = sinceRef.current?.tenant === forTenant ? sinceRef.current.at : undefined
      const fresh = await fetchActivity(forTenant, since)
      if (fresh.length === 0) return 0
      sinceRef.current = { tenant: forTenant, at: [...fresh].sort(byNewest)[0].at }
      setFeed((prev) => {
        const known = new Set(prev.tenant === forTenant ? prev.items.map(itemKey) : [])
        const kept = prev.tenant === forTenant ? prev.items : []
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

  const shown = items.filter((i) => filter === 'all' || i.agent === filter)

  return (
    <div className="activity">
      <section className="page-head">
        <h1>Agent Activity</h1>
        <p>Live feed of agent steps, handoffs and workers.</p>
        <div className="activity-filters" role="group" aria-label="Filter by agent">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              type="button"
              className={f.key === filter ? 'is-active' : ''}
              aria-pressed={f.key === filter}
              onClick={() => setFilter(f.key)}
            >
              {f.label}
            </button>
          ))}
        </div>
      </section>

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
            {shown.map((item) => (
              <li key={itemKey(item)}>
                <time dateTime={item.at}>{clock(item.at)}</time>
                <span className={`agent-badge agent-${item.agent.toLowerCase()}`}>{item.agent}</span>
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
                  {item.handed_to && <small>Handoff → {item.handed_to}</small>}
                </div>
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  )
}
