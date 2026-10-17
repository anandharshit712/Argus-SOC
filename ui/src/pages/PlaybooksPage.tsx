import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { PlaybookOut } from '../api/apiTypes.ts'
import { fetchPlaybooks } from '../api/argusApi.ts'
import Icon from '../components/Icon.tsx'
import { usePoll } from '../hooks/usePoll.ts'
import { timeAgo } from '../lib/formatTime.ts'
import { useApp } from '../state/AppContext.tsx'
import './PlaybooksPage.css'

const POLL_MS = 10_000

/** A condition value as text: `ioc_in` is a list of IOCs. */
const conditionValue = (v: unknown) =>
  Array.isArray(v) ? v.join(', ') : typeof v === 'object' && v !== null ? JSON.stringify(v) : String(v)

const CONDITION_LABEL: Record<string, string> = { category: 'Talos category', ioc_in: 'Source IOC is one of' }

const day = (iso: string | null) => (iso ? iso.slice(0, 10) : '—')
const time = (p: PlaybookOut) => (p.created_at ? new Date(p.created_at).getTime() : 0)

type Group = { name: string; current: PlaybookOut; older: PlaybookOut[] }

/** One group per playbook name: the active version (or the newest) first, older ones after. */
function groupByName(playbooks: PlaybookOut[]): Group[] {
  const byName = new Map<string, PlaybookOut[]>()
  for (const p of playbooks) byName.set(p.name, [...(byName.get(p.name) ?? []), p])
  const groups = [...byName.entries()].map(([name, versions]) => {
    const sorted = [...versions].sort((a, b) => b.version - a.version)
    const current = sorted.find((p) => p.active) ?? sorted[0]
    return { name, current, older: sorted.filter((p) => p !== current) }
  })
  // Most recently learned first.
  return groups.sort((a, b) => time(b.current) - time(a.current))
}

function Condition({ condition }: { condition: Record<string, unknown> }) {
  const entries = Object.entries(condition)
  if (entries.length === 0) return <p className="muted small">No condition</p>
  return (
    <dl className="condition">
      {entries.map(([k, v]) => (
        <div key={k}>
          <dt>{CONDITION_LABEL[k] ?? k}</dt>
          <dd>{conditionValue(v)}</dd>
        </div>
      ))}
    </dl>
  )
}

function LearnedFrom({ p }: { p: PlaybookOut }) {
  return p.source_case !== null ? (
    <>
      Learned from <Link to={`/cases/${p.source_case}`}>Case {p.source_case}</Link>
    </>
  ) : (
    <>Seeded</>
  )
}

function PlaybookCard({ group }: { group: Group }) {
  const [showHistory, setShowHistory] = useState(false)
  const { current, older } = group
  return (
    <article className="playbook-card">
      <header>
        <h2>{group.name}</h2>
        <span className="version-tag">v{current.version}</span>
        <span className={`active-tag ${current.active ? 'is-active' : ''}`}>{current.active ? 'Active' : 'Inactive'}</span>
      </header>
      <p className="playbook-meta">
        <LearnedFrom p={current} /> · {day(current.created_at)} ({timeAgo(current.created_at)}) · action:{' '}
        {current.action ? current.action.replace(/_/g, ' ') : '—'}
      </p>
      <Condition condition={current.condition} />

      {older.length > 0 && (
        <>
          <button type="button" className="history-toggle" onClick={() => setShowHistory(!showHistory)} aria-expanded={showHistory}>
            <Icon name={showHistory ? 'chevronDown' : 'chevronRight'} size={16} /> Earlier versions ({older.length})
          </button>
          {showHistory && (
            <ol className="version-history">
              {older.map((p) => (
                <li key={p.version}>
                  <span className="version-tag">v{p.version}</span>
                  <span className="superseded-tag">{p.active ? 'Active' : 'Superseded'}</span>
                  <span className="muted">
                    <LearnedFrom p={p} /> · {day(p.created_at)}
                  </span>
                  <Condition condition={p.condition} />
                </li>
              ))}
            </ol>
          )}
        </>
      )}
    </article>
  )
}

export default function PlaybooksPage() {
  const { tenant, live } = useApp()
  const { data, error, loading } = usePoll(() => fetchPlaybooks(tenant), POLL_MS, live, [tenant])
  const groups = groupByName(data ?? [])

  return (
    <div className="playbooks">
      <section className="page-head">
        <h1>Playbooks</h1>
        <p>What the system has learned, version by version.</p>
      </section>

      {error && (
        <p className="page-error" role="alert">
          Could not refresh: {error} {data ? 'Showing the last data received.' : ''}
        </p>
      )}

      {loading && !data ? (
        <p className="muted">Loading playbooks…</p>
      ) : groups.length === 0 ? (
        <section className="panel">
          <p className="muted">Nothing learned yet. Playbooks appear after an analyst marks a case benign.</p>
        </section>
      ) : (
        <div className="playbook-grid">
          {groups.map((g) => (
            <PlaybookCard key={g.name} group={g} />
          ))}
        </div>
      )}
    </div>
  )
}
