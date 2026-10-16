import type { CaseDetail } from '../api/apiTypes.ts'
import { humanize } from '../lib/caseTitle.ts'
import Icon from './Icon.tsx'

type CaseDecisionPanelProps = {
  case: CaseDetail
  /** Opens the Feedback tab, where the analyst approves, rejects or marks benign. */
  onGiveFeedback: () => void
}

const OUTCOME_LABEL: Record<string, string> = {
  pending: 'Waiting for analyst approval',
  approved: 'Approved by an analyst',
  rejected: 'Rejected by an analyst',
  auto: 'Decided automatically',
}

function Targets({ label, values }: { label: string; values: string[] }) {
  if (values.length === 0) return null
  return (
    <p className="small">
      <span className="muted">{label}:</span> {values.join(', ')}
    </p>
  )
}

export default function CaseDecisionPanel({ case: detail, onGiveFeedback }: CaseDecisionPanelProps) {
  const decision = detail.decision
  if (!decision) {
    return (
      <>
        <h2>Decision Panel</h2>
        <p className="muted">No decision yet. The agents are still working on this case.</p>
      </>
    )
  }

  // GAP-5: the Responder may lower urgency (rule R4, e.g. high -> medium).
  const priorityChanged = decision.previous_priority !== null && decision.previous_priority !== detail.priority

  return (
    <>
      <h2>Decision Panel</h2>

      <h3>Agent Verdict</h3>
      <p className="verdict">{decision.explanation ?? decision.reason ?? 'No explanation recorded.'}</p>
      <p className="muted small">
        {decision.rule_id ? `Rule ${decision.rule_id}` : 'No rule'}
        {decision.reason && decision.explanation ? ` · ${decision.reason}` : ''}
      </p>
      {decision.playbook && <p className="muted small">Decided by playbook {decision.playbook}</p>}
      {priorityChanged && (
        <p className="small">
          Priority changed by the Responder: <strong>{decision.previous_priority}</strong> → <strong>{detail.priority}</strong>
        </p>
      )}

      <h3>Recommended Actions</h3>
      {decision.actions.length === 0 ? (
        <p className="muted">No actions.</p>
      ) : (
        <ul className="action-list">
          {decision.actions.map((action) => (
            <li key={action}>
              <span className="action-item">{humanize(action)}</span>
            </li>
          ))}
        </ul>
      )}
      <Targets label="Hosts" values={decision.target_hosts} />
      <Targets label="Accounts" values={decision.target_users} />
      <Targets label="IOCs" values={decision.target_iocs} />
      <p className="muted small">
        {OUTCOME_LABEL[decision.outcome ?? ''] ?? decision.outcome}. Actions are simulated: they run on the graph when
        approved, never on real systems.
      </p>

      {detail.needs_approval && (
        <button type="button" className="btn-primary decision-cta" onClick={onGiveFeedback}>
          Review and give verdict <Icon name="chevronRight" size={18} />
        </button>
      )}
    </>
  )
}
