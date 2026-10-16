import { useState } from 'react'
import type { DecisionOut, Priority } from '../api/apiTypes.ts'
import Icon from './Icon.tsx'

type CaseDecisionPanelProps = {
  decision: DecisionOut | null
  priority: Priority
  onApplyPriority: (priority: Priority) => void
}

const PRIORITIES: Priority[] = ['critical', 'high', 'medium', 'low']

export default function CaseDecisionPanel({ decision, priority, onApplyPriority }: CaseDecisionPanelProps) {
  const [queued, setQueued] = useState<string[]>([])
  const [selected, setSelected] = useState<Priority>(priority)

  if (!decision) {
    return (
      <>
        <h2>Decision Panel</h2>
        <p className="muted">No decision yet. The agents are still working on this case.</p>
      </>
    )
  }

  return (
    <>
      <h2>Decision Panel</h2>

      <h3>Analyst Verdict</h3>
      <p className="verdict">{decision.explanation}</p>
      <p className="muted small">
        Rule {decision.rule_id} · {decision.reason}
      </p>

      <h3>Recommended Actions</h3>
      <ul className="action-list">
        {decision.actions.map((action) => {
          const done = queued.includes(action)
          return (
            <li key={action}>
              <button
                type="button"
                disabled={done}
                onClick={() => setQueued([...queued, action])}
              >
                {action}
                {done ? <span className="muted small">Queued (simulated)</span> : <Icon name="chevronRight" size={18} />}
              </button>
            </li>
          )
        })}
      </ul>
      <p className="muted small">Actions are simulated. Nothing runs on real systems.</p>

      <h3>Change Priority</h3>
      <div className="priority-row">
        <select value={selected} onChange={(e) => setSelected(e.target.value as Priority)} aria-label="Priority">
          {PRIORITIES.map((p) => (
            <option key={p} value={p}>{p.charAt(0).toUpperCase() + p.slice(1)}</option>
          ))}
        </select>
        <button type="button" className="btn-primary" onClick={() => onApplyPriority(selected)} disabled={selected === priority}>
          Apply
        </button>
      </div>
    </>
  )
}
