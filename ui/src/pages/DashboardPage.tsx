import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { Kpi, TimeWindow } from '../api/apiTypes.ts'
import { fetchCases, fetchDashboard } from '../api/argusApi.ts'
import { CaseTable } from '../components/CaseTable.tsx'
import Icon, { type IconName } from '../components/Icon.tsx'
import StatTile from '../components/StatTile.tsx'
import { usePoll } from '../hooks/usePoll.ts'
import { formatSeconds } from '../lib/formatTime.ts'
import { tenantLabel } from '../lib/tenantLabel.ts'
import { useApp } from '../state/AppContext.tsx'
import './DashboardPage.css'

const POLL_MS = 5000
const RECENT_CASES = 5

const count = (kpi: Kpi) => (kpi.value === null ? '—' : String(kpi.value))
/** Change vs the previous window, when the API has both numbers. */
const delta = (kpi: Kpi) => (kpi.value !== null && kpi.previous !== null ? kpi.value - kpi.previous : null)

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
  const { tenant, live, displayName } = useApp()
  const [window, setWindow] = useState<TimeWindow>('1h')
  const { data, error, loading } = usePoll(() => fetchDashboard(tenant, window), POLL_MS, live, [tenant, window])
  const recent = usePoll(() => fetchCases(tenant, RECENT_CASES), POLL_MS, live, [tenant])

  const label = tenantLabel(tenant)
  const k = data?.kpis

  return (
    <div className="dashboard">
      <section className="welcome">
        <div>
          <h1>Welcome back, {displayName}</h1>
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
        k && (
          <>
            <section className="tile-grid" aria-label={`${label} summary`}>
              <StatTile label="Open cases" value={count(k.open_cases)} delta={null} to="/cases?status=open" />
              <StatTile
                label="Awaiting approval"
                value={count(k.awaiting_approval)}
                delta={null}
                to="/cases?status=awaiting_approval"
                warn={(k.awaiting_approval.value ?? 0) > 0}
              />
              <StatTile
                label="Critical / high open"
                value={count(k.critical_high_open)}
                delta={null}
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
                delta={null}
              />
              <StatTile label="Active playbooks" value={count(k.active_playbooks)} delta={null} to="/playbooks" />
            </section>

            <div className="dash-lower">
              <section className="panel">
                <h2>Recent Cases</h2>
                {recent.data ? (
                  <CaseTable cases={recent.data} />
                ) : (
                  <p className="muted">{recent.error ? `Could not load cases: ${recent.error}` : 'Loading cases…'}</p>
                )}
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
