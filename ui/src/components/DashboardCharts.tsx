// Small hand-built charts for the dashboard. Plain SVG / HTML, no chart library.
// Series colours were checked with the dataviz palette validator against the panel surface
// (dark mode, both pass: lightness band, chroma, CVD and normal-vision separation, 3:1 contrast).
import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { ActivityItem, DashboardOut, TimeWindow } from '../api/apiTypes.ts'
import { humanize } from '../lib/caseTitle.ts'
import { clockTime, timeAgo } from '../lib/formatTime.ts'
import { PriorityBadge } from './CaseBadges.tsx'
import './DashboardCharts.css'

const SERIES = { human: '#4a86e0', auto: '#33a852' } as const

// ---------- case pipeline (G6: the handoffs) ----------

const PIPELINE: { status: string; label: string }[] = [
  { status: 'new', label: 'New' },
  { status: 'triaged', label: 'Triaged' },
  { status: 'investigated', label: 'Investigated' },
  { status: 'awaiting_approval', label: 'Awaiting' },
  { status: 'closed', label: 'Closed' },
]

export function PipelineStrip({ pipeline }: { pipeline: Record<string, number> }) {
  return (
    <div className="pipeline" aria-label="Cases per stage">
      <ol>
        {PIPELINE.map((step, i) => (
          <li key={step.status}>
            {i > 0 && <span className="pipeline-arrow" aria-hidden="true">→</span>}
            <Link to={`/cases?status=${step.status}`} className="pipeline-step">
              <span>{step.label}</span>
              <strong>{pipeline[step.status] ?? 0}</strong>
            </Link>
          </li>
        ))}
      </ol>
      <Link to="/cases?status=auto_closed" className="pipeline-step pipeline-auto" title="Closed by Triage with a learned playbook">
        <span>Auto-closed by playbook</span>
        <strong>{pipeline.auto_closed ?? 0}</strong>
      </Link>
    </div>
  )
}

// ---------- cases over time (G5: learning proof) ----------

const W = 640
const H = 220
const PAD = { top: 26, right: 12, bottom: 28, left: 34 }
const GAP = 2 // surface gap between stacked segments and between columns

function tickLabel(iso: string, window: TimeWindow): string {
  const d = new Date(iso)
  if (window === 'all') return d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false })
  return clockTime(iso)
}

/** Top-rounded bar path (4px data end), flat at the bottom. */
function columnPath(x: number, y: number, w: number, h: number, round: boolean): string {
  const r = round ? Math.min(4, w / 2, h) : 0
  return `M${x},${y + h} V${y + r} Q${x},${y} ${x + r},${y} H${x + w - r} Q${x + w},${y} ${x + w},${y + r} V${y + h} Z`
}

export function CasesOverTime({ data }: { data: DashboardOut }) {
  const [hover, setHover] = useState<number | null>(null)
  const { buckets, playbook_markers: markers, window, generated_at } = data
  if (buckets.length === 0) return <p className="muted">No cases in this window.</p>

  const innerW = W - PAD.left - PAD.right
  const innerH = H - PAD.top - PAD.bottom
  const maxTotal = Math.max(1, ...buckets.map((b) => b.human + b.auto))
  const slot = innerW / buckets.length
  const barW = Math.max(4, slot - 6)
  const y = (v: number) => (v / maxTotal) * innerH
  const start = new Date(buckets[0].start).getTime()
  const end = new Date(generated_at).getTime()
  const xOfTime = (iso: string) => PAD.left + ((new Date(iso).getTime() - start) / Math.max(1, end - start)) * innerW
  const ticks = [0, Math.floor(buckets.length / 2), buckets.length - 1]
  const hovered = hover !== null ? buckets[hover] : null

  return (
    <div className="chart">
      <div className="chart-legend" aria-hidden="true">
        <span><i style={{ background: SERIES.human }} /> Needed a human</span>
        <span><i style={{ background: SERIES.auto }} /> Auto-closed</span>
        {markers.length > 0 && <span><i className="legend-marker" /> Playbook learned</span>}
      </div>
      <div className="chart-plot">
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Cases opened over time, needed a human versus auto-closed">
          {/* recessive grid: baseline and the top value */}
          <line x1={PAD.left} x2={W - PAD.right} y1={PAD.top + innerH} y2={PAD.top + innerH} className="axis" />
          <line x1={PAD.left} x2={W - PAD.right} y1={PAD.top} y2={PAD.top} className="grid" />
          <text x={PAD.left - 6} y={PAD.top + 4} textAnchor="end" className="tick">{maxTotal}</text>
          <text x={PAD.left - 6} y={PAD.top + innerH + 4} textAnchor="end" className="tick">0</text>

          {buckets.map((b, i) => {
            const x = PAD.left + i * slot + (slot - barW) / 2
            const autoH = y(b.auto)
            const humanH = y(b.human)
            const base = PAD.top + innerH
            return (
              <g key={b.start} className={hover === i ? 'is-hover' : undefined}>
                {b.auto > 0 && (
                  <path d={columnPath(x, base - autoH, barW, autoH, b.human === 0)} fill={SERIES.auto} />
                )}
                {b.human > 0 && (
                  <path
                    d={columnPath(x, base - autoH - humanH - (b.auto > 0 ? GAP : 0), barW, humanH, true)}
                    fill={SERIES.human}
                  />
                )}
                {/* hit target: the whole column, bigger than the mark */}
                <rect
                  x={PAD.left + i * slot}
                  y={PAD.top}
                  width={slot}
                  height={innerH}
                  fill="transparent"
                  onMouseEnter={() => setHover(i)}
                  onMouseLeave={() => setHover(null)}
                />
              </g>
            )
          })}

          {markers.map((m) => {
            const x = xOfTime(m.at)
            // Keep the label inside the plot: left-aligned near the start, right-aligned near the end.
            const anchor = x < W * 0.3 ? 'start' : x > W * 0.7 ? 'end' : 'middle'
            return (
              <g key={`${m.playbook}-${m.at}`} className="marker">
                <line x1={x} x2={x} y1={PAD.top - 6} y2={PAD.top + innerH} />
                <text x={x} y={PAD.top - 10} textAnchor={anchor}>
                  ▲ {m.playbook}
                </text>
              </g>
            )
          })}

          {ticks.map((i) => (
            <text key={i} x={PAD.left + i * slot + slot / 2} y={H - 8} textAnchor="middle" className="tick">
              {tickLabel(buckets[i].start, window)}
            </text>
          ))}
        </svg>
        {hovered && hover !== null && (
          <div
            className="chart-tooltip"
            style={{ left: `${Math.min(80, Math.max(20, ((PAD.left + (hover + 0.5) * slot) / W) * 100))}%`, top: '40%' }}
          >
            <strong>{tickLabel(hovered.start, window)}</strong>
            <span><i style={{ background: SERIES.human }} /> Needed a human: {hovered.human}</span>
            <span><i style={{ background: SERIES.auto }} /> Auto-closed: {hovered.auto}</span>
          </div>
        )}
      </div>
      <details className="chart-table">
        <summary>View as table</summary>
        <table className="mini-table">
          <thead>
            <tr><th>From</th><th>Needed a human</th><th>Auto-closed</th></tr>
          </thead>
          <tbody>
            {buckets.map((b) => (
              <tr key={b.start}><td>{tickLabel(b.start, window)}</td><td>{b.human}</td><td>{b.auto}</td></tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  )
}

// ---------- single-series horizontal bars ----------

export type BarItem = { label: string; value: number; to?: string }

export function BarList({ items, empty }: { items: BarItem[]; empty: string }) {
  if (items.length === 0) return <p className="muted">{empty}</p>
  const max = Math.max(1, ...items.map((i) => i.value))
  return (
    <ul className="bar-list">
      {items.map((item) => {
        const label = item.to ? <Link to={item.to}>{item.label}</Link> : item.label
        return (
          <li key={item.label} title={`${item.label}: ${item.value}`}>
            <span className="bar-label">{label}</span>
            <span className="bar-track">
              <span className="bar-fill" style={{ width: `${(item.value / max) * 100}%`, background: SERIES.human }} />
            </span>
            <span className="bar-value">{item.value}</span>
          </li>
        )
      })}
    </ul>
  )
}

// ---------- agents & workers (G11) ----------

export function AgentsTable({ agents }: { agents: DashboardOut['agents'] }) {
  if (agents.length === 0) return <p className="muted">No agent steps in this window.</p>
  const max = Math.max(1, ...agents.map((a) => a.steps))
  const workers = new Set(agents.map((a) => a.worker).filter(Boolean))
  return (
    <>
      <p className="muted small">
        {workers.size} worker{workers.size === 1 ? '' : 's'} sharing the work
      </p>
      <ul className="agents-list">
        {agents.map((a) => (
          <li key={`${a.agent}-${a.worker}`} title={`${a.steps} steps, last ${timeAgo(a.last_seen)}`}>
            <span className="agents-name">
              {humanize(a.agent)} <small className="muted">· {a.worker ?? 'no worker'}</small>
            </span>
            <span className="bar-track">
              <span className="bar-fill" style={{ width: `${(a.steps / max) * 100}%`, background: SERIES.human }} />
            </span>
            <span className="bar-value">{a.steps}</span>
            <small className="muted agents-seen">{timeAgo(a.last_seen)}</small>
          </li>
        ))}
      </ul>
    </>
  )
}

// ---------- needs you ----------

export function NeedsYouList({ cases }: { cases: DashboardOut['needs_you'] }) {
  if (cases.length === 0) return <p className="muted">Nothing is waiting for an analyst.</p>
  return (
    <ul className="needs-you">
      {cases.map((c) => (
        <li key={c.id}>
          <Link to={`/cases/${c.id}`}>
            <strong>#{c.id}</strong> {humanize(c.category ?? 'case')}
          </Link>
          <span className="needs-you-meta">
            <PriorityBadge priority={c.priority} />
            <small className="muted">opened {timeAgo(c.opened_at)}</small>
          </span>
        </li>
      ))}
    </ul>
  )
}

// ---------- recent activity ----------

export function RecentActivity({ items }: { items: ActivityItem[] }) {
  if (items.length === 0) return <p className="muted">No agent activity yet.</p>
  return (
    <ol className="recent-activity">
      {items.map((r, i) => (
        <li key={r.id ?? i}>
          <time dateTime={r.at ?? undefined}>{clockTime(r.at)}</time>
          <span className={`agent-badge agent-${r.agent ?? 'unknown'}`}>{r.agent ? humanize(r.agent) : 'Agent'}</span>
          <span>
            {r.summary}
            {r.case_id !== null && (
              <>
                {' '}
                <Link to={`/cases/${r.case_id}`}>#{r.case_id}</Link>
              </>
            )}
            {r.handed_to && <small className="muted"> → {humanize(r.handed_to)}</small>}
          </span>
        </li>
      ))}
    </ol>
  )
}
