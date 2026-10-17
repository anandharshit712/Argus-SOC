import type { CaseDetail } from '../api/apiTypes.ts'

// Triage → Investigator → Responder → Analyst (UI_PAGES §4.2). Done = ✓, current = pulsing dot.
// An auto-closed case shows Triage → Playbook and stops.

type Step = { label: string; state: 'done' | 'current' | 'todo' }

const LABELS = ['Triage', 'Investigator', 'Responder', 'Analyst']
// How many steps are finished in each status: a `triaged` case has passed Triage, and so on.
// A `closed` case is finished whether the analyst decided or no approval was needed.
const DONE_IN_STATUS: Record<string, number> = {
  new: 0,
  triaged: 1,
  investigated: 2,
  awaiting_approval: 3,
  closed: 4,
}

function steps(c: CaseDetail): Step[] {
  if (c.status === 'auto_closed') {
    return [
      { label: 'Triage', state: 'done' },
      { label: c.auto_closed_by ? `Playbook ${c.auto_closed_by}` : 'Playbook', state: 'done' },
    ]
  }
  const done = DONE_IN_STATUS[c.status] ?? 0
  return LABELS.map((label, i) => ({ label, state: i < done ? 'done' : i === done ? 'current' : 'todo' }))
}

export default function CaseProgress({ detail }: { detail: CaseDetail }) {
  return (
    <ol className="progress-strip" aria-label="Case progress">
      {steps(detail).map((s, i) => (
        <li key={s.label} className={`step-${s.state}`}>
          {i > 0 && (
            <span className="progress-arrow" aria-hidden="true">
              →
            </span>
          )}
          <span className="progress-mark" aria-hidden="true">
            {s.state === 'done' ? '✓' : ''}
          </span>
          {s.label}
          <span className="visually-hidden">
            {s.state === 'done' ? ' (done)' : s.state === 'current' ? ' (in progress)' : ' (not started)'}
          </span>
        </li>
      ))}
    </ol>
  )
}
