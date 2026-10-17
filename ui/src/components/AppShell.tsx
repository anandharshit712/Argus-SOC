import { useState, type CSSProperties } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import type { SessionOut } from '../api/apiTypes.ts'
import { fetchCases, fetchHealth } from '../api/argusApi.ts'
import { usePoll } from '../hooks/usePoll.ts'
import { storedTenant, storeTenant, tenantColor, tenantLabel } from '../lib/tenantLabel.ts'
import { AppContext } from '../state/AppContext.tsx'
import ArgusLogo from './ArgusLogo.tsx'
import Icon, { type IconName } from './Icon.tsx'
import './AppShell.css'

type AppShellProps = { session: SessionOut; onSignOut: () => void }

const NAV: { to: string; label: string; icon: IconName }[] = [
  { to: '/dashboard', label: 'Dashboard', icon: 'home' },
  { to: '/cases', label: 'Cases', icon: 'cases' },
  { to: '/playbooks', label: 'Playbooks', icon: 'playbooks' },
  { to: '/activity', label: 'Activity', icon: 'activity' },
]

const HEALTH_POLL_MS = 10_000
const AWAITING_POLL_MS = 5000

type HealthView = { label: string; detail: string; bad: boolean; banner: string | null }

function healthView(status: string | undefined, unreachable: boolean): HealthView {
  if (unreachable) {
    return { label: 'API down', detail: 'Can’t reach the API', bad: true, banner: 'Can’t reach the API. Showing the last data received; retrying.' }
  }
  if (status === 'ok') return { label: 'OK', detail: 'All systems operational', bad: false, banner: null }
  if (status === 'mock') return { label: 'Mock data', detail: 'Mock mode: sample data, no database', bad: false, banner: null }
  if (status === 'degraded') {
    return { label: 'Degraded', detail: 'Graph database unreachable', bad: true, banner: 'The graph database is unreachable. Data may be out of date; retrying.' }
  }
  return { label: '…', detail: 'Checking…', bad: false, banner: null }
}

export default function AppShell({ session, onSignOut }: AppShellProps) {
  const tenants = session.tenants
  // The tenant survives a refresh (sessionStorage), as long as the user may still see it.
  const [tenant, setTenantState] = useState<string>(() => storedTenant(tenants) ?? tenants[0] ?? '')
  const [live, setLive] = useState(true)
  const navigate = useNavigate()
  const location = useLocation()
  const health = usePoll(fetchHealth, HEALTH_POLL_MS, live, [])
  const view = healthView(health.data?.status, health.error !== null)
  const awaiting = usePoll(
    () => fetchCases(tenant, 500, 'awaiting_approval'),
    AWAITING_POLL_MS,
    live && tenant !== '',
    [tenant],
  )
  const awaitingCount = awaiting.data?.length ?? 0

  function setTenant(next: string) {
    if (next === tenant) return
    storeTenant(next)
    setTenantState(next)
    // A case number belongs to one tenant: leave the case page instead of showing a 404.
    if (/^\/cases\/[^/]+/.test(location.pathname)) navigate('/cases')
  }

  const context = {
    username: session.username,
    displayName: session.display_name,
    tenants,
    tenant,
    setTenant,
    live,
    setLive,
    signOut: onSignOut,
  }
  const accent = { '--tenant': tenantColor(tenant, tenants) } as CSSProperties

  return (
    <AppContext.Provider value={context}>
      <div className="shell" style={accent}>
        <header className="topbar">
          <div className="brand">
            <ArgusLogo size={34} />
            <span>Argus SOC</span>
          </div>

          {/* The only tenant switcher: a user with one tenant sees it fixed, with more they pick. */}
          {tenants.length > 0 && (
            <label className="tenant-picker" title="Switch tenant">
              <span className="tenant-dot" aria-hidden="true" />
              <span className="visually-hidden">Tenant</span>
              <select value={tenant} onChange={(e) => setTenant(e.target.value)} disabled={tenants.length === 1}>
                {tenants.map((t) => (
                  <option key={t} value={t}>
                    {tenantLabel(t)}
                  </option>
                ))}
              </select>
            </label>
          )}

          <div className="topbar-status">
            <button
              type="button"
              className={`live-toggle${live ? ' is-live' : ''}`}
              onClick={() => setLive(!live)}
              aria-pressed={live}
              title={live ? 'Pause refresh' : 'Resume refresh'}
            >
              <span className="dot" /> {live ? 'Live' : 'Paused'}
            </button>
            <span className={`health-text${view.bad ? ' is-bad' : ''}`}>Health: {view.label}</span>
            <span className="user-name" title={session.username}>
              {session.display_name}
            </span>
            <button type="button" className="logout-button" onClick={onSignOut} title={`Log out ${session.username}`}>
              <Icon name="logout" size={18} />
              <span className="logout-label">Logout</span>
            </button>
          </div>
        </header>

        <div className="shell-body">
          <aside className="sidebar">
            <nav aria-label="Main">
              {NAV.map((item) => (
                <NavLink key={item.to} to={item.to} className="side-link">
                  <Icon name={item.icon} /> {item.label}
                  {item.to === '/cases' && awaitingCount > 0 && (
                    <span className="nav-badge" title={`${awaitingCount} awaiting approval`}>
                      {awaitingCount}
                      <span className="visually-hidden"> awaiting approval</span>
                    </span>
                  )}
                </NavLink>
              ))}
            </nav>

            <div className={`system-health${view.bad ? ' is-bad' : ''}`}>
              <span className="dot" />
              <div>
                <strong>System Health</strong>
                <small>{view.detail}</small>
              </div>
            </div>
          </aside>

          <main className="shell-main">
            {view.banner && (
              <p className="health-banner" role="alert">
                {view.banner}
              </p>
            )}
            {tenants.length === 0 ? (
              <section className="panel" style={{ maxWidth: 520 }}>
                <h2>No tenants</h2>
                <p className="muted">This account has no tenant to show. Ask an admin to add one.</p>
              </section>
            ) : (
              <Outlet />
            )}
          </main>
        </div>
      </div>
    </AppContext.Provider>
  )
}
