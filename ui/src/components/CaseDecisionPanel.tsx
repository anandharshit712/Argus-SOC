import type { CaseDetail } from '../api/apiTypes.ts'
import { actionLine, talosSuggestions } from '../lib/decisionText.ts'
import CaseProgress from './CaseProgress.tsx'
import Icon from './Icon.tsx'

type CaseDecisionPanelProps = {
  case: CaseDetail
  /** Opens the Feedback tab, where the analyst approves, rejects or marks benign. */
  onGiveFeedback: () => void
}

// The decision table's rules (docs/LLD.md §6.4), for the rule chip's tooltip.
const RULES: Record<string, string> = {
  R1: 'R1: attack succeeded and a path to a crown jewel exists',
  R2: 'R2: attack succeeded, no path to a crown jewel',
  R3: 'R3: attack failed, but a path to a crown jewel exists',
  R4: 'R4: attack failed and no path: lower the priority',
}

const OUTCOME_LABEL: Record<string, string> = {
  pending: 'Pending approval',
  approved: 'Approved',
  rejected: 'Rejected',
  auto: 'Applied automatically',
}

export default function CaseDecisionPanel({ case: detail, onGiveFeedback }: CaseDecisionPanelProps) {
  const decision = detail.decision
  const suggested = talosSuggestions(detail)

  const talosBox = suggested.length > 0 && (
    <aside className="talos-box" aria-label="Talos suggested">
      <h3>Talos suggested</h3>
      <ul>
        {suggested.map((s) => (
          <li key={s}>{s}</li>
        ))}
      </ul>
      <p className="muted small">From the detection engine, not the agents. Not applied.</p>
    </aside>
  )

  if (!decision) {
    return (
      <>
        <h2>Decision Panel</h2>
        <p className="muted">The agents are still working on this case.</p>
        <CaseProgress detail={detail} />
        {talosBox}
      </>
    )
  }

  // GAP-5: the Responder may lower urgency (rule R4, e.g. high -> medium).
  const priorityChanged = decision.previous_priority !== null && decision.previous_priority !== detail.priority
  const path = detail.findings.shortest_path ?? []

  return (
    <>
      <h2>Decision Panel</h2>

      <div className="decision-meta">
        {decision.rule_id && (
          <span className="rule-chip" title={RULES[decision.rule_id] ?? decision.rule_id}>
            {decision.rule_id}
          </span>
        )}
        <span className={`outcome-pill outcome-${decision.outcome ?? 'unknown'}`}>
          {OUTCOME_LABEL[decision.outcome ?? ''] ?? decision.outcome ?? 'No outcome'}
        </span>
        <span className="muted small">{decision.needs_approval ? 'Needs analyst approval' : 'Applied automatically'}</span>
      </div>

      {decision.reason && <p className="decision-reason">{decision.reason}</p>}
      {decision.explanation && <p className="verdict">{decision.explanation}</p>}
      {decision.playbook && <p className="muted small">Decided by playbook {decision.playbook}</p>}
      {priorityChanged && (
        <p className="small">
          Priority lowered by the Responder: <strong>{decision.previous_priority}</strong> →{' '}
          <strong>{detail.priority}</strong>
        </p>
      )}

      <h3>Recommended Actions</h3>
      {decision.actions.length === 0 ? (
        <p className="muted">No actions.</p>
      ) : (
        <ul className="action-list">
          {decision.actions.map((action) => (
            <li key={action} className="action-item">
              <span>{actionLine(action, decision, path)}</span>
              <span className="simulated-tag">simulated</span>
            </li>
          ))}
        </ul>
      )}
      <p className="muted small">Actions run on the graph only, never on real systems.</p>

      {detail.needs_approval && (
        <button type="button" className="btn-primary decision-cta" onClick={onGiveFeedback}>
          Review and give verdict <Icon name="chevronRight" size={18} />
        </button>
      )}

      {talosBox}
    </>
  )
}
