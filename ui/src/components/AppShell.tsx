import { useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { fetchHealth, TENANTS, TENANT_LABEL, type Tenant } from '../api/mockData.ts'
import { usePoll } from '../hooks/usePoll.ts'
import { AppContext } from '../state/AppContext.tsx'
import ArgusLogo from './ArgusLogo.tsx'
import Icon, { type IconName } from './Icon.tsx'
import './AppShell.css'

type AppShellProps = { username: string; onSignOut: () => void }

const NAV: { to: string; label: string; icon: IconName }[] = [
  { to: '/dashboard', label: 'Dashboard', icon: 'home' },
  { to: '/cases', label: 'Cases', icon: 'cases' },
  { to: '/playbooks', label: 'Playbooks', icon: 'playbooks' },
  { to: '/activity', label: 'Activity', icon: 'activity' },
]

export default function AppShell({ username, onSignOut }: AppShellProps) {
  const [tenant, setTenant] = useState<Tenant>('acme')
  const [live, setLive] = useState(true)
  const health = usePoll(fetchHealth, 10_000, live, [])
  const healthy = health.data ? health.data.status === 'ok' && health.data.falkordb : null

  return (
    <AppContext.Provider value={{ username, tenant, setTenant, live, setLive, signOut: onSignOut }}>
      <div className="shell">
        <header className="topbar">
          <div className="brand">
            <ArgusLogo size={34} />
            <span>Argus SOC</span>
          </div>

          <select
            className="tenant-select"
            value={tenant}
            onChange={(e) => setTenant(e.target.value as Tenant)}
            aria-label="Tenant"
          >
            {TENANTS.map((t) => (
              <option key={t} value={t}>{TENANT_LABEL[t]}</option>
            ))}
          </select>

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
            <span className="health-text">
              Health: {healthy === null ? '…' : healthy ? 'OK' : 'Degraded'}
            </span>
            <button type="button" className="user-button" onClick={onSignOut} title={`Sign out ${username}`}>
              <Icon name="user" size={18} />
              <span className="visually-hidden">Sign out {username}</span>
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
              {TENANTS.map((t) => (
                <button
                  key={t}
                  type="button"
                  className={`tenant-option${t === tenant ? ' is-active' : ''}`}
                  onClick={() => setTenant(t)}
                  aria-pressed={t === tenant}
                >
                  <Icon name="building" /> {TENANT_LABEL[t]}
                  {t === tenant && <Icon name="check" size={16} />}
                </button>
              ))}
            </div>

            <div className={`system-health${healthy === false ? ' is-bad' : ''}`}>
              <span className="dot" />
              <div>
                <strong>System Health</strong>
                <small>
                  {healthy === null ? 'Checking…' : healthy ? 'All systems operational' : 'Degraded — check graph'}
                </small>
              </div>
            </div>
          </aside>

          <main className="shell-main">
            <Outlet />
          </main>
        </div>
      </div>
    </AppContext.Provider>
  )
}
