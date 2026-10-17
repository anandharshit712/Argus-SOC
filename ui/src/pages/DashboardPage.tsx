import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { Kpi, TimeWindow } from '../api/apiTypes.ts'
import { fetchDashboard } from '../api/argusApi.ts'
import {
  AgentsTable,
  BarList,
  CasesOverTime,
  NeedsYouList,
  PipelineStrip,
  RecentActivity,
} from '../components/DashboardCharts.tsx'
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

const WINDOWS: { value: TimeWindow; label: string }[] = [
  { value: '30m', label: '30m' },
  { value: '1h', label: '1h' },
  { value: '24h', label: '24h' },
  { value: 'all', label: 'All' },
]

const QUICK_ACTIONS: { to: string; label: string; icon: IconName }[] = [
  { to: '/cases', label: 'View All Cases', icon: 'cases' },
  { to: '/playbooks', label: 'Open Playbooks', icon: 'playbooks' },
  { to: '/activity', label: 'Check Activity', icon: 'activity' },
]

const PRIORITY_ORDER = ['critical', 'high', 'medium', 'low', 'info']

export default function DashboardPage() {
  const { tenant, live, displayName } = useApp()
  const [window, setWindow] = useState<TimeWindow>('1h')
  const { data, error, loading } = usePoll(() => fetchDashboard(tenant, window), POLL_MS, live, [tenant, window])

  const label = tenantLabel(tenant)
  const k = data?.kpis

  return (
    <div className="dashboard">
      <section className="welcome">
        <div>
          <h1>Welcome back, {displayName}</h1>
          <p>Here’s what’s happening in {label}’s SOC.</p>
        </div>
        <div className="window-select" role="group" aria-label="Time window">
          {WINDOWS.map((w) => (
            <button
              key={w.value}
              type="button"
              className={w.value === window ? 'is-active' : ''}
              aria-pressed={w.value === window}
              onClick={() => setWindow(w.value)}
            >
              {w.label}
            </button>
          ))}
        </div>
      </section>

      {error && (
        <p className="dash-error" role="alert">
          Could not refresh: {error} {data ? 'Showing the last data received.' : ''}
        </p>
      )}

      {loading && !data ? (
        <p className="dash-loading">Loading {label}…</p>
      ) : (
        data &&
        k && (
          <>
            <section className="tile-grid" aria-label={`${label} summary`}>
              <StatTile label="Open cases" value={count(k.open_cases)} delta={delta(k.open_cases)} to="/cases?status=open" />
              <StatTile
                label="Awaiting approval"
                value={count(k.awaiting_approval)}
                delta={delta(k.awaiting_approval)}
                to="/cases?status=awaiting_approval"
                warn={(k.awaiting_approval.value ?? 0) > 0}
              />
              <StatTile
                label="Critical / high open"
                value={count(k.critical_high_open)}
                delta={delta(k.critical_high_open)}
                to="/cases?sort=priority"
              />
              <StatTile
                label="Auto-closed"
                value={count(k.auto_closed)}
                suffix={k.auto_closed_pct.value !== null ? `(${k.auto_closed_pct.value}%)` : undefined}
                delta={delta(k.auto_closed)}
                to="/cases?status=auto_closed"
              />
              <StatTile
                label="Median time to decision"
                value={formatSeconds(k.median_decision_seconds.value)}
                delta={delta(k.median_decision_seconds)}
                deltaUnit=" s"
              />
              <StatTile
                label="Active playbooks"
                value={count(k.active_playbooks)}
                delta={delta(k.active_playbooks)}
                to="/playbooks"
              />
            </section>

            <section className="panel">
              <h2>Case pipeline</h2>
              <PipelineStrip pipeline={data.pipeline} />
            </section>

            <div className="dash-row dash-row-wide">
              <section className="panel">
                <h2>Cases over time</h2>
                <CasesOverTime data={data} />
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
                  empty="No cases in this window."
                  items={PRIORITY_ORDER.filter((p) => data.by_priority[p]).map((p) => ({
                    label: humanize(p),
                    value: data.by_priority[p],
                  }))}
                />
              </section>
              <section className="panel">
                <h2>By Talos category</h2>
                <BarList
                  empty="No cases in this window."
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
