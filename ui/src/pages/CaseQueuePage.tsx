import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { OPEN_STATUSES, type CaseStatus, type CaseSummary, type Priority } from '../api/apiTypes.ts'
import { fetchCases } from '../api/argusApi.ts'
import { CaseTable } from '../components/CaseTable.tsx'
import Icon from '../components/Icon.tsx'
import { usePoll } from '../hooks/usePoll.ts'
import { caseTitle } from '../lib/caseTitle.ts'
import { tenantLabel } from '../lib/tenantLabel.ts'
import { useApp } from '../state/AppContext.tsx'
import './CaseQueuePage.css'

const POLL_MS = 3000
const PAGE_SIZE = 5

type TabKey = 'all' | 'open' | 'in_progress' | 'resolved'

const TABS: { key: TabKey; label: string; statuses: CaseStatus[] | null }[] = [
  { key: 'all', label: 'All', statuses: null },
  { key: 'open', label: 'Open', statuses: ['new'] },
  { key: 'in_progress', label: 'In Progress', statuses: ['triaged', 'investigated', 'awaiting_approval'] },
  { key: 'resolved', label: 'Resolved', statuses: ['closed', 'auto_closed'] },
]

const STATUS_OPTIONS: { value: string; label: string }[] = [
  { value: 'all', label: 'All Statuses' },
  { value: 'open', label: 'All open' },
  { value: 'new', label: 'New' },
  { value: 'triaged', label: 'Triaged' },
  { value: 'investigated', label: 'Investigated' },
  { value: 'awaiting_approval', label: 'Awaiting approval' },
  { value: 'closed', label: 'Closed' },
  { value: 'auto_closed', label: 'Auto-closed' },
]

const PRIORITY_OPTIONS: { value: string; label: string }[] = [
  { value: 'all', label: 'All Priorities' },
  { value: 'critical', label: 'Critical' },
  { value: 'high', label: 'High' },
  { value: 'medium', label: 'Medium' },
  { value: 'low', label: 'Low' },
  { value: 'info', label: 'Info' },
]

const PRIORITY_RANK: Record<Priority, number> = { critical: 0, high: 1, medium: 2, low: 3, info: 4 }

function inTab(c: CaseSummary, tab: TabKey): boolean {
  const statuses = TABS.find((t) => t.key === tab)?.statuses
  return !statuses || statuses.includes(c.status)
}

function matchesStatus(c: CaseSummary, status: string): boolean {
  if (status === 'all') return true
  if (status === 'open') return OPEN_STATUSES.includes(c.status)
  return c.status === status
}

function matchesQuery(c: CaseSummary, query: string): boolean {
  const q = query.trim().toLowerCase().replace(/^#/, '')
  if (!q) return true
  return String(c.id).includes(q) || caseTitle(c.category).toLowerCase().includes(q)
}

export default function CaseQueuePage() {
  const { tenant, live } = useApp()
  const [params, setParams] = useSearchParams()
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(1)
  const { data, error, loading } = usePoll(() => fetchCases(tenant), POLL_MS, live, [tenant])

  const tabParam = params.get('tab')
  const tab: TabKey = TABS.some((t) => t.key === tabParam) ? (tabParam as TabKey) : 'all'
  const status = params.get('status') ?? 'all'
  const priority = params.get('priority') ?? 'all'
  const byPriority = params.get('sort') === 'priority'

  function setParam(changes: Record<string, string | null>) {
    const next = new URLSearchParams(params)
    for (const [key, value] of Object.entries(changes)) {
      if (value === null || value === 'all') next.delete(key)
      else next.set(key, value)
    }
    setParams(next, { replace: true })
    setPage(1)
  }

  const cases = data ?? []
  const filtered = cases
    .filter((c) => inTab(c, tab) && matchesStatus(c, status))
    .filter((c) => priority === 'all' || c.priority === priority)
    .filter((c) => matchesQuery(c, query))
    .sort((a, b) => {
      if (byPriority && a.priority !== b.priority) return (PRIORITY_RANK[a.priority] ?? 9) - (PRIORITY_RANK[b.priority] ?? 9)
      return new Date(b.opened_at ?? 0).getTime() - new Date(a.opened_at ?? 0).getTime()
    })

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const current = Math.min(page, pageCount)
  const start = (current - 1) * PAGE_SIZE
  const visible = filtered.slice(start, start + PAGE_SIZE)

  return (
    <div className="queue">
      <section className="queue-head">
        <h1>Case Queue</h1>
        <p>All cases for {tenantLabel(tenant)}, newest first.</p>
        <div className="queue-tabs" role="group" aria-label="Case groups">
          {TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              className={t.key === tab ? 'is-active' : ''}
              aria-pressed={t.key === tab}
              onClick={() => setParam({ tab: t.key, status: null })}
            >
              {t.label} ({cases.filter((c) => inTab(c, t.key)).length})
            </button>
          ))}
        </div>
      </section>

      <section className="queue-filters">
        <label className="queue-search">
          <Icon name="search" size={20} />
          <input
            type="search"
            placeholder="Search cases..."
            value={query}
            onChange={(e) => {
              setQuery(e.target.value)
              setPage(1)
            }}
            aria-label="Search cases"
          />
        </label>
        <select value={priority} onChange={(e) => setParam({ priority: e.target.value })} aria-label="Priority">
          {PRIORITY_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
        <select value={status} onChange={(e) => setParam({ status: e.target.value })} aria-label="Status">
          {STATUS_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      </section>

      {error && (
        <p className="queue-error" role="alert">
          Could not refresh: {error} {data ? 'Showing the last data received.' : ''}
        </p>
      )}

      <section className="panel queue-table">
        {loading && !data ? (
          <p className="case-empty">Loading cases…</p>
        ) : (
          <CaseTable cases={visible} emptyText="No cases match these filters." />
        )}
      </section>

      <footer className="queue-pager">
        <span>
          {filtered.length === 0 ? '0 of 0' : `${start + 1}–${start + visible.length} of ${filtered.length}`}
        </span>
        <nav aria-label="Pages">
          <button type="button" onClick={() => setPage(current - 1)} disabled={current <= 1} aria-label="Previous page">
            <Icon name="chevronLeft" size={16} />
          </button>
          {Array.from({ length: pageCount }, (_, i) => i + 1).map((n) => (
            <button
              key={n}
              type="button"
              className={n === current ? 'is-active' : ''}
              aria-current={n === current ? 'page' : undefined}
              onClick={() => setPage(n)}
            >
              {n}
            </button>
          ))}
          <button type="button" onClick={() => setPage(current + 1)} disabled={current >= pageCount} aria-label="Next page">
            <Icon name="chevronRight" size={16} />
          </button>
        </nav>
      </footer>
    </div>
  )
}
