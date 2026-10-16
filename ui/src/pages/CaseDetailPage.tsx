import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import type { Priority } from '../api/apiTypes.ts'
import { fetchCaseDetail } from '../api/mockCaseDetail.ts'
import NotFoundView from '../components/NotFoundView.tsx'
import { PriorityBadge, StatusBadge } from '../components/CaseBadges.tsx'
import CaseDecisionPanel from '../components/CaseDecisionPanel.tsx'
import CaseFeedbackForm from '../components/CaseFeedbackForm.tsx'
import { HostRankingList, KeyFindingsList, LinkedAlertsList, MemoryPanel, TimelineList } from '../components/CasePanels.tsx'
import CasePathGraph from '../components/CasePathGraph.tsx'
import { usePoll } from '../hooks/usePoll.ts'
import { caseTitle } from '../lib/caseTitle.ts'
import { timeAgo } from '../lib/formatTime.ts'
import { useApp } from '../state/AppContext.tsx'
import './CaseDetailPage.css'

const POLL_MS = 5000

type TabKey = 'overview' | 'path' | 'ranking' | 'alerts' | 'timeline' | 'feedback'

const TABS: { key: TabKey; label: string }[] = [
  { key: 'overview', label: 'Overview' },
  { key: 'path', label: 'Path' },
  { key: 'ranking', label: 'Host Ranking' },
  { key: 'alerts', label: 'Linked Alerts' },
  { key: 'timeline', label: 'Timeline' },
  { key: 'feedback', label: 'Feedback' },
]

export default function CaseDetailPage() {
  const { caseId } = useParams()
  const { tenant, live, username } = useApp()
  const id = Number(caseId)
  const [tab, setTab] = useState<TabKey>('overview')
  // Mock only: the contract has no "change priority" call yet, so this stays in the browser.
  const [priorityOverride, setPriorityOverride] = useState<Priority | null>(null)

  const { data, error, loading, refresh } = usePoll(() => fetchCaseDetail(tenant, id), POLL_MS, live, [tenant, id])

  if (loading && data === null) return <p className="muted">Loading case…</p>
  if (data === null) return <NotFoundView message={`There is no case #${caseId} for this tenant.`} />

  const priority = priorityOverride ?? data.priority

  const decisionPanel = (
    <CaseDecisionPanel key={data.id} decision={data.decision} priority={priority} onApplyPriority={setPriorityOverride} />
  )
  const path = data.decision ? <CasePathGraph path={data.decision.path} /> : <p className="muted">No path yet.</p>
  const ranking = <HostRankingList ranking={data.decision?.ranking ?? []} />

  return (
    <div className="case-detail">
      <header className="case-head">
        <div className="case-title">
          <Link to="/cases" className="back-link">← Cases</Link>
          <h1>
            #{data.id} <span>{caseTitle(data.category)}</span>
          </h1>
          <PriorityBadge priority={priority} />
        </div>
        <div className="case-meta">
          <StatusBadge status={data.status} />
          <span>Updated {timeAgo(data.updated_at)}</span>
        </div>
      </header>

      {error && (
        <p className="detail-error" role="alert">
          Could not refresh: {error} Showing the last data received.
        </p>
      )}

      <div className="case-tabs" role="tablist" aria-label="Case sections">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={t.key === tab}
            className={t.key === tab ? 'is-active' : ''}
            onClick={() => setTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'overview' && (
        <div className="overview-grid">
          <section className="panel area-decision">{decisionPanel}</section>
          <section className="panel area-path">
            <h2>Path to Crown Jewel</h2>
            {path}
          </section>
          <section className="panel area-ranking">
            <h2>Host Ranking</h2>
            {ranking}
          </section>
          <section className="panel area-findings">
            <h2>Key Findings</h2>
            <KeyFindingsList findings={data.findings.key_findings} />
          </section>
          <section className="panel area-memory">
            <h2>Memory</h2>
            <MemoryPanel findings={data.findings} />
          </section>
          <section className="panel area-alerts">
            <h2>Linked Alerts</h2>
            <LinkedAlertsList alerts={data.alerts} />
          </section>
        </div>
      )}

      {tab === 'path' && (
        <section className="panel">
          <h2>Path to Crown Jewel</h2>
          {path}
        </section>
      )}
      {tab === 'ranking' && (
        <section className="panel">
          <h2>Host Ranking</h2>
          {ranking}
        </section>
      )}
      {tab === 'alerts' && (
        <section className="panel">
          <h2>Linked Alerts</h2>
          <LinkedAlertsList alerts={data.alerts} expanded />
        </section>
      )}
      {tab === 'timeline' && (
        <section className="panel">
          <h2>Timeline</h2>
          <TimelineList runs={data.agent_runs} />
        </section>
      )}
      {tab === 'feedback' && (
        <section className="panel">
          <h2>Feedback</h2>
          <CaseFeedbackForm tenant={tenant} analyst={username} detail={data} onSubmitted={refresh} />
        </section>
      )}
    </div>
  )
}
