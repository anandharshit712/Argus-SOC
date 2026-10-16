import { useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchDashboard, TENANT_LABEL, type TimeWindow } from '../api/mockData.ts'
import { CaseTable } from '../components/CaseTable.tsx'
import Icon, { type IconName } from '../components/Icon.tsx'
import StatTile from '../components/StatTile.tsx'
import { usePoll } from '../hooks/usePoll.ts'
import { formatSeconds } from '../lib/formatTime.ts'
import { useApp } from '../state/AppContext.tsx'
import './DashboardPage.css'

const POLL_MS = 5000

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

export default function DashboardPage() {
  const { tenant, live } = useApp()
  const [window, setWindow] = useState<TimeWindow>('1h')
  const { data, error, loading } = usePoll(() => fetchDashboard(tenant, window), POLL_MS, live, [tenant, window])

  const label = TENANT_LABEL[tenant]
  const m = data?.metrics
  const p = data?.previous
  const delta = (pick: (x: NonNullable<typeof m>) => number) => (m && p ? pick(m) - pick(p) : null)

  return (
    <div className="dashboard">
      <section className="welcome">
        <div>
          <h1>Welcome back, {label} Analyst</h1>
          <p>Here’s what’s happening in your SOC today.</p>
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
        m &&
        data && (
          <>
            <section className="tile-grid" aria-label={`${label} summary`}>
              <StatTile label="Open cases" value={String(m.open)} delta={delta((x) => x.open)} to="/cases?status=open" />
              <StatTile
                label="Awaiting approval"
                value={String(m.awaiting)}
                delta={delta((x) => x.awaiting)}
                to="/cases?status=awaiting_approval"
                warn={m.awaiting > 0}
              />
              <StatTile
                label="Critical / high open"
                value={String(m.criticalHighOpen)}
                delta={delta((x) => x.criticalHighOpen)}
                to="/cases?sort=priority"
              />
              <StatTile
                label="Auto-closed"
                value={String(m.autoClosed)}
                suffix={`(${m.autoClosedPct}%)`}
                delta={delta((x) => x.autoClosed)}
                to="/cases?status=auto_closed"
              />
              <StatTile label="Median time to decision" value={formatSeconds(m.medianDecisionSeconds)} delta={null} />
              <StatTile label="Active playbooks" value={String(data.activePlaybooks)} delta={null} to="/playbooks" />
            </section>

            <div className="dash-lower">
              <section className="panel">
                <h2>Recent Cases</h2>
                <CaseTable cases={data.recentCases} />
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
