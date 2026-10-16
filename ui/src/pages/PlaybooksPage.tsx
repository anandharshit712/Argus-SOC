import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { PlaybookOut } from '../api/apiTypes.ts'
import { fetchPlaybooks } from '../api/argusApi.ts'
import Icon from '../components/Icon.tsx'
import { usePoll } from '../hooks/usePoll.ts'
import { useApp } from '../state/AppContext.tsx'
import './PlaybooksPage.css'

const POLL_MS = 10_000

type SortKey = 'name' | 'version' | 'updated'
type Sort = { key: SortKey; dir: 'asc' | 'desc' }

const COLUMNS: { key: SortKey; label: string }[] = [
  { key: 'name', label: 'Name' },
  { key: 'version', label: 'Version' },
  { key: 'updated', label: 'Updated' },
]

function compare(a: PlaybookOut, b: PlaybookOut, key: SortKey): number {
  if (key === 'name') return a.name.localeCompare(b.name) || b.version - a.version
  if (key === 'version') return a.version - b.version || a.name.localeCompare(b.name)
  return new Date(a.created_at ?? 0).getTime() - new Date(b.created_at ?? 0).getTime()
}

/** A condition value as text: `ioc_in` is a list of IOCs. */
const conditionValue = (v: unknown) => (Array.isArray(v) ? v.join(', ') : typeof v === 'object' ? JSON.stringify(v) : String(v))

const describe = (condition: Record<string, unknown>) => {
  const parts = Object.entries(condition).map(([k, v]) => `${k} = ${conditionValue(v)}`)
  return parts.length ? `Matches ${parts.join('; ')}` : 'No condition'
}

const day = (iso: string | null) => (iso ? iso.slice(0, 10) : '—')

const rowKey = (p: PlaybookOut) => `${p.name}@${p.version}`

export default function PlaybooksPage() {
  const { tenant, live } = useApp()
  const [sort, setSort] = useState<Sort>({ key: 'updated', dir: 'desc' })
  const [openRow, setOpenRow] = useState<string | null>(null)
  const { data, error, loading } = usePoll(() => fetchPlaybooks(tenant), POLL_MS, live, [tenant])

  const rows = [...(data ?? [])].sort((a, b) => (sort.dir === 'asc' ? 1 : -1) * compare(a, b, sort.key))

  function toggleSort(key: SortKey) {
    setSort((s) => (s.key === key ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: key === 'name' ? 'asc' : 'desc' }))
  }

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

      <section className="panel playbook-panel">
        {loading && !data ? (
          <p className="muted">Loading playbooks…</p>
        ) : rows.length === 0 ? (
          <p className="muted">Nothing learned yet. Playbooks appear after an analyst marks a case benign.</p>
        ) : (
          <table className="playbook-table">
            <thead>
              <tr>
                {COLUMNS.map((c) => (
                  <th key={c.key} aria-sort={sort.key === c.key ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
                    <button type="button" onClick={() => toggleSort(c.key)}>
                      {c.label}
                      {sort.key === c.key && <Icon name={sort.dir === 'asc' ? 'chevronUp' : 'chevronDown'} size={14} />}
                    </button>
                  </th>
                ))}
                <th><span className="visually-hidden">Details</span></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => {
                const key = rowKey(p)
                const open = openRow === key
                return (
                  <PlaybookRow key={key} playbook={p} open={open} onToggle={() => setOpenRow(open ? null : key)} />
                )
              })}
            </tbody>
          </table>
        )}
      </section>
    </div>
  )
}

type PlaybookRowProps = { playbook: PlaybookOut; open: boolean; onToggle: () => void }

function PlaybookRow({ playbook: p, open, onToggle }: PlaybookRowProps) {
  return (
    <>
      <tr className={open ? 'is-open' : ''}>
        <td>
          <strong>{p.name}</strong>
          <small>{describe(p.condition)}</small>
        </td>
        <td>
          v{p.version}
          <span className={`active-tag ${p.active ? 'is-active' : ''}`}>{p.active ? 'Active' : 'Inactive'}</span>
        </td>
        <td>{day(p.created_at)}</td>
        <td className="row-toggle">
          <button type="button" onClick={onToggle} aria-expanded={open} aria-label={`Details for ${p.name} v${p.version}`}>
            <Icon name={open ? 'chevronDown' : 'chevronRight'} size={18} />
          </button>
        </td>
      </tr>
      {open && (
        <tr className="detail-row">
          <td colSpan={4}>
            <dl>
              {Object.entries(p.condition).map(([k, v]) => (
                <div key={k}>
                  <dt>{k}</dt>
                  <dd>{conditionValue(v)}</dd>
                </div>
              ))}
              <div>
                <dt>Learned from</dt>
                <dd>{p.source_case !== null ? <Link to={`/cases/${p.source_case}`}>Case #{p.source_case}</Link> : 'Seeded'}</dd>
              </div>
              <div>
                <dt>Created</dt>
                <dd>{day(p.created_at)}</dd>
              </div>
              <div>
                <dt>Action</dt>
                <dd>{p.action ? p.action.replace(/_/g, ' ') : '—'}</dd>
              </div>
            </dl>
          </td>
        </tr>
      )}
    </>
  )
}
