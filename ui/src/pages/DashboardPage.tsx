import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import type { DashboardOut, Kpi, TimeWindow } from '../api/apiTypes.ts'
import { fetchDashboard } from '../api/argusApi.ts'
import {
  AgentsTable,
  BarList,
  CasesOverTime,
  EmptyState,
  NeedsYouList,
  PipelineStrip,
  RecentActivity,
} from '../components/DashboardCharts.tsx'
import Dock, { type DockItem } from '../components/Dock.tsx'
import GlowFrame from '../components/GlowFrame.tsx'
import Icon, { type IconName } from '../components/Icon.tsx'
import StatTile from '../components/StatTile.tsx'
import { usePoll } from '../hooks/usePoll.ts'
import { humanize } from '../lib/caseTitle.ts'
import { formatSeconds } from '../lib/formatTime.ts'
import { tenantLabel } from '../lib/tenantLabel.ts'
import { useApp } from '../state/AppContext.tsx'
import './DashboardPage.css'

const POLL_MS = 5000

const count = (kpi: Kpi) => (kpi.value === null ? '—' : String(kpi.value))
/** Change vs the previous window, when the API has both numbers (windowed KPIs only). */
const delta = (kpi: Kpi) =>
  kpi.value !== null && kpi.previous !== null ? Math.round((kpi.value - kpi.previous) * 10) / 10 : null

const WINDOWS: { value: TimeWindow; label: string; title: string }[] = [
  { value: '30m', label: '30m', title: 'Last 30 minutes' },
  { value: '1h', label: '1h', title: 'Last hour' },
  { value: '24h', label: '24h', title: 'Last 24 hours' },
  { value: 'all', label: 'All', title: 'All time' },
]

const QUICK_ACTIONS: { to: string; label: string; icon: IconName }[] = [
  { to: '/cases', label: 'View All Cases', icon: 'cases' },
  { to: '/playbooks', label: 'Open Playbooks', icon: 'playbooks' },
  { to: '/activity', label: 'Check Activity', icon: 'activity' },
]

const PRIORITY_ORDER = ['critical', 'high', 'medium', 'low', 'info']

type KpiKey = keyof DashboardOut['kpis']
const TREND_POINTS = 24 // readings kept per tile (one per poll)

/** Wider windows to offer when the current one is empty. */
const WIDER: Record<TimeWindow, TimeWindow[]> = { '30m': ['24h', 'all'], '1h': ['24h', 'all'], '24h': ['all'], all: [] }

function agoText(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000))
  if (s < 5) return 'just now'
  if (s < 60) return `${s}s ago`
  return `${Math.round(s / 60)}m ago`
}

/** Grey placeholders in the dashboard's layout, shown until the first data arrives. */
function DashboardSkeleton({ label }: { label: string }) {
  return (
    <>
      <p className="visually-hidden" role="status">
        Loading {label}…
      </p>
      <div className="dash-skeleton" aria-hidden="true">
        <div className="tile-grid">
          {Array.from({ length: 6 }, (_, i) => (
            <div key={i} className="skeleton skeleton-tile">
              <span className="skeleton-line" style={{ width: '65%' }} />
              <span className="skeleton-line skeleton-value" />
              <span className="skeleton-line" style={{ width: '45%' }} />
            </div>
          ))}
        </div>
        <div className="skeleton" style={{ height: 112 }} />
        <div className="dash-row dash-row-wide">
          <div className="skeleton" style={{ height: 300 }} />
          <div className="skeleton" style={{ height: 300 }} />
        </div>
      </div>
    </>
  )
}

export default function DashboardPage() {
  const { tenant, live, displayName } = useApp()
  const [window, setWindow] = useState<TimeWindow>('1h')
  const { data, error, loading } = usePoll(() => fetchDashboard(tenant, window), POLL_MS, live, [tenant, window])

  const label = tenantLabel(tenant)
  const k = data?.kpis

  // Each poll adds a reading per KPI (for the tile sparklines) and stamps "updated … ago".
  const [trends, setTrends] = useState<{ key: string; points: Partial<Record<KpiKey, number[]>> }>({
    key: '',
    points: {},
  })
  const [updatedAt, setUpdatedAt] = useState<number | null>(null)
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [])
  useEffect(() => {
    if (!data) return
    setUpdatedAt(Date.now())
    const key = `${data.tenant}|${data.window}`
    setTrends((prev) => {
      const points = prev.key === key ? { ...prev.points } : {}
      for (const [name, kpi] of Object.entries(data.kpis) as [KpiKey, Kpi][]) {
        if (kpi.value !== null) points[name] = [...(points[name] ?? []), kpi.value].slice(-TREND_POINTS)
      }
      return { key, points }
    })
  }, [data])
  const trend = (name: KpiKey) => trends.points[name]

  // Empty windowed panels offer a wider window in one click.
  const widen =
    WIDER[window].length > 0
      ? WIDER[window].map((w) => (
          <button key={w} type="button" onClick={() => setWindow(w)}>
            Show {w === 'all' ? 'all time' : `last ${w}`}
          </button>
        ))
      : undefined
  const windowEmpty = (title: string) => (
    <EmptyState icon="clock" title={title} hint={widen ? 'Try a longer time window.' : undefined} actions={widen} />
  )

  return (
    <div className="dashboard">
      <section className="welcome">
        <div>
          <h1>Welcome back, {displayName}</h1>
          <p>Here’s what’s happening in {label}’s SOC.</p>
          <p className="updated-line">
            <span className={`updated-dot${live ? '' : ' is-paused'}`} aria-hidden="true" />
            {live ? 'Live' : 'Paused'}
            {updatedAt !== null && ` · updated ${agoText(now - updatedAt)}`}
          </p>
        </div>
        <Dock
          className="window-dock"
          ariaLabel="Time window"
          items={WINDOWS.flatMap((w): DockItem[] => {
            const item: DockItem = {
              icon: w.label,
              label: w.label,
              title: w.title,
              active: w.value === window,
              onClick: () => setWindow(w.value),
            }
            // "All" sits after a separator: it is not a rolling window like the others.
            return w.value === 'all' ? [{ separator: true }, item] : [item]
          })}
          baseItemSize={36}
          magnification={46}
          panelHeight={50}
          accentColor="#4ade6a"
          position="bottom"
          distance={120}
          gap={6}
          roundness={0.24}
          bounce
          tiles
          showLabels
          showIndicators
          showBadges={false}
        />
      </section>

      {error && (
        <p className="dash-error" role="alert">
          Could not refresh: {error} {data ? 'Showing the last data received.' : ''}
        </p>
      )}

      {loading && !data ? (
        <DashboardSkeleton label={label} />
      ) : (
        data &&
        k && (
          <>
            <section className="tile-grid" aria-label={`${label} summary`}>
              <GlowFrame>
                <StatTile
                  label="Open cases"
                  value={count(k.open_cases)}
                  delta={delta(k.open_cases)}
                  to="/cases?status=open"
                  trend={trend('open_cases')}
                />
              </GlowFrame>
              <GlowFrame warn={(k.awaiting_approval.value ?? 0) > 0}>
                <StatTile
                  label="Awaiting approval"
                  value={count(k.awaiting_approval)}
                  delta={delta(k.awaiting_approval)}
                  to="/cases?status=awaiting_approval"
                  warn={(k.awaiting_approval.value ?? 0) > 0}
                  trend={trend('awaiting_approval')}
                />
              </GlowFrame>
              <GlowFrame>
                <StatTile
                  label="Critical / high open"
                  value={count(k.critical_high_open)}
                  delta={delta(k.critical_high_open)}
                  to="/cases?sort=priority"
                  trend={trend('critical_high_open')}
                />
              </GlowFrame>
              <GlowFrame>
                <StatTile
                  label="Auto-closed"
                  value={count(k.auto_closed)}
                  suffix={k.auto_closed_pct.value !== null ? `(${k.auto_closed_pct.value}%)` : undefined}
                  delta={delta(k.auto_closed)}
                  to="/cases?status=auto_closed"
                  trend={trend('auto_closed')}
                />
              </GlowFrame>
              <GlowFrame>
                <StatTile
                  label="Median time to decision"
                  value={formatSeconds(k.median_decision_seconds.value)}
                  delta={delta(k.median_decision_seconds)}
                  deltaUnit=" s"
                  trend={trend('median_decision_seconds')}
                />
              </GlowFrame>
              <GlowFrame>
                <StatTile
                  label="Active playbooks"
                  value={count(k.active_playbooks)}
                  delta={delta(k.active_playbooks)}
                  to="/playbooks"
                  trend={trend('active_playbooks')}
                />
              </GlowFrame>
            </section>

            <section className="panel">
              <h2>Case pipeline</h2>
              <PipelineStrip pipeline={data.pipeline} />
            </section>

            <div className="dash-row dash-row-wide">
              <section className="panel">
                <h2>Cases over time</h2>
                <CasesOverTime data={data} empty={windowEmpty('No cases opened in this window.')} />
              </section>
              <section className="panel">
                <h2>Needs you</h2>
                <NeedsYouList cases={data.needs_you} />
              </section>
            </div>

            <div className="dash-row dash-row-three">
              <section className="panel">
                <h2>By priority</h2>
                <BarList
                  empty={windowEmpty('No cases in this window.')}
                  items={PRIORITY_ORDER.filter((p) => data.by_priority[p]).map((p) => ({
                    label: humanize(p),
                    value: data.by_priority[p],
                  }))}
                />
              </section>
              <section className="panel">
                <h2>By Talos category</h2>
                <BarList
                  empty={windowEmpty('No cases in this window.')}
                  items={Object.entries(data.by_category).map(([category, value]) => ({ label: humanize(category), value }))}
                />
              </section>
              <section className="panel">
                <h2>Agents &amp; workers</h2>
                <AgentsTable agents={data.agents} />
              </section>
            </div>

            <div className="dash-row dash-row-wide">
              <section className="panel">
                <h2>Recent activity</h2>
                <RecentActivity items={data.recent_activity} />
              </section>
              <section className="panel">
                <h2>Quick Actions</h2>
                <div className="quick-actions">
                  {QUICK_ACTIONS.map((a) => (
                    <Link key={a.to} to={a.to} className="quick-action">
                      <Icon name={a.icon} /> {a.label}
                      <Icon name="chevronRight" size={18} />
                    </Link>
                  ))}
                </div>
              </section>
            </div>
          </>
        )
      )}
    </div>
  )
}
