import { useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import type { SessionOut } from '../api/apiTypes.ts'
import { fetchHealth } from '../api/argusApi.ts'
import { usePoll } from '../hooks/usePoll.ts'
import { tenantLabel } from '../lib/tenantLabel.ts'
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
  const [tenant, setTenant] = useState<string>(tenants[0] ?? '')
  const [live, setLive] = useState(true)
  const health = usePoll(fetchHealth, HEALTH_POLL_MS, live, [])
  const view = healthView(health.data?.status, health.error !== null)

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

  return (
    <AppContext.Provider value={context}>
      <div className="shell">
        <header className="topbar">
          <div className="brand">
            <ArgusLogo size={34} />
            <span>Argus SOC</span>
          </div>

          {tenants.length > 0 && (
            <select className="tenant-select" value={tenant} onChange={(e) => setTenant(e.target.value)} aria-label="Tenant">
              {tenants.map((t) => (
                <option key={t} value={t}>
                  {tenantLabel(t)}
                </option>
              ))}
            </select>
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
            <button type="button" className="user-button" onClick={onSignOut} title={`Sign out ${session.username}`}>
              <Icon name="user" size={18} />
              <span className="visually-hidden">Sign out {session.display_name}</span>
            </button>
          </div>
        </header>

        <div className="shell-body">
          <aside className="sidebar">
            <nav aria-label="Main">
              {NAV.map((item) => (
                <NavLink key={item.to} to={item.to} className="side-link">
                  <Icon name={item.icon} /> {item.label}
                </NavLink>
              ))}
            </nav>

            <div className="tenant-switcher">
              <h2>Tenant Switcher</h2>
              {tenants.map((t) => (
                <button
                  key={t}
                  type="button"
                  className={`tenant-option${t === tenant ? ' is-active' : ''}`}
                  onClick={() => setTenant(t)}
                  aria-pressed={t === tenant}
                >
                  <Icon name="building" /> {tenantLabel(t)}
                  {t === tenant && <Icon name="check" size={16} />}
                </button>
              ))}
            </div>

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
