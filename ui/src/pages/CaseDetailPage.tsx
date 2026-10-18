import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { fetchCaseDetail } from '../api/argusApi.ts'
import { PriorityBadge, StatusBadge } from '../components/CaseBadges.tsx'
import CaseDecisionPanel from '../components/CaseDecisionPanel.tsx'
import CaseFeedbackForm from '../components/CaseFeedbackForm.tsx'
import {
  DeepDivePanel,
  FindingsPanel,
  HostRankingList,
  LinkedAlertsList,
  MemoryPanel,
  TimelineList,
} from '../components/CasePanels.tsx'
import CasePathGraph from '../components/CasePathGraph.tsx'
import CaseProgress from '../components/CaseProgress.tsx'
import GlowFrame from '../components/GlowFrame.tsx'
import NotFoundView from '../components/NotFoundView.tsx'
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

  const { data, error, loading, refresh } = usePoll(() => fetchCaseDetail(tenant, id), POLL_MS, live, [tenant, id])

  if (data === null) {
    if (loading) return <p className="muted">Loading case…</p>
    if (error) {
      return (
        <section className="panel" style={{ maxWidth: 560 }}>
          <h2>Could not load case #{caseId}</h2>
          <p className="muted">{error} Retrying…</p>
        </section>
      )
    }
    return <NotFoundView message={`There is no case #${caseId} for this tenant.`} />
  }

  const decision = data.decision
  // The decision's path, or the Investigator's shortest path before there is a decision.
  const nodes = decision?.path.length
    ? decision.path
    : (data.findings.shortest_path ?? []).map((name) => ({ name, label: 'Host' }))
  const path =
    nodes.length > 0 ? (
      <CasePathGraph
        path={nodes}
        targets={[...(decision?.target_hosts ?? []), ...(decision?.target_users ?? [])]}
        endsOnCrownJewel={data.findings.path_to_crown_jewel !== false}
        ranking={decision?.ranking ?? []}
      />
    ) : (
      <p className="muted">
        {data.findings.path_to_crown_jewel === false ? 'No path to a crown jewel within 6 hops' : 'No path yet.'}
      </p>
    )
  const ranking = (
    <HostRankingList
      ranking={decision?.ranking ?? []}
      isolates={decision?.actions.includes('isolate_top_host') ?? false}
    />
  )

  return (
    <div className="case-detail">
      <header className="case-head">
        <div className="case-title">
          <Link to="/cases" className="back-link">
            ← Cases
          </Link>
          <h1>
            #{data.id} <span>{caseTitle(data.category)}</span>
          </h1>
          <PriorityBadge priority={data.priority} />
        </div>
        <div className="case-meta">
          <StatusBadge status={data.status} />
          {data.auto_closed_by && (
            <span>
              Auto-closed by <Link to="/playbooks">{data.auto_closed_by}</Link>
              {data.auto_closed_source_case !== null && (
                <>
                  , learned from <Link to={`/cases/${data.auto_closed_source_case}`}>Case {data.auto_closed_source_case}</Link>
                </>
              )}
            </span>
          )}
        </div>
        <div className="case-subline">
          <span>
            {data.alert_count} alert{data.alert_count === 1 ? '' : 's'}
          </span>
          <span>Opened {timeAgo(data.opened_at)}</span>
          <span>Updated {timeAgo(data.updated_at)}</span>
          {data.closed_at && <span>Closed {timeAgo(data.closed_at)}</span>}
        </div>
        <CaseProgress detail={data} />
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
            {t.key === 'feedback' && data.needs_approval && <span className="tab-dot" aria-label="needs your verdict" />}
          </button>
        ))}
      </div>

      {tab === 'overview' && (
        <div className="overview-grid">
          <GlowFrame className="area-decision">
            <section className="panel">
              <CaseDecisionPanel case={data} onGiveFeedback={() => setTab('feedback')} />
            </section>
          </GlowFrame>
          <GlowFrame className="area-path">
            <section className="panel path-panel">
              <h2>Path to Crown Jewel</h2>
              {path}
            </section>
          </GlowFrame>
          <GlowFrame className="area-ranking">
            <section className="panel">
              <h2>Host Ranking</h2>
              {ranking}
            </section>
          </GlowFrame>
          <GlowFrame className="area-findings">
            <section className="panel">
              <h2>Key Findings</h2>
              <FindingsPanel findings={data.findings} />
            </section>
          </GlowFrame>
          <GlowFrame className="area-memory">
            <section className="panel">
              <h2>Memory</h2>
              <MemoryPanel findings={data.findings} />
            </section>
          </GlowFrame>
          <GlowFrame className="area-alerts">
            <section className="panel">
              <h2>Linked Alerts</h2>
              <LinkedAlertsList alerts={data.alerts} />
            </section>
          </GlowFrame>
          <GlowFrame className="area-deepdive">
            <section className="panel">
              <h2>Deep Dive (MCP tools)</h2>
              <DeepDivePanel calls={data.findings.deep_dive} />
            </section>
          </GlowFrame>
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
          <CaseFeedbackForm key={data.id} tenant={tenant} analyst={username} detail={data} onSubmitted={refresh} />
        </section>
      )}
    </div>
  )
}
