import { useState, type FormEvent } from 'react'
import type { CaseDetail, FeedbackVerdict } from '../api/apiTypes.ts'
import { submitFeedback } from '../api/argusApi.ts'
import { timeAgo } from '../lib/formatTime.ts'

type CaseFeedbackFormProps = {
  tenant: string
  /** Shown only: the API records the signed-in user from the session token. */
  analyst: string
  detail: CaseDetail
  onSubmitted: () => void
}

const NOTE_MAX = 500
const VERDICTS: { value: FeedbackVerdict; label: string; hint: string }[] = [
  { value: 'approve', label: 'Approve', hint: 'Runs the simulated actions and closes the case' },
  { value: 'reject', label: 'Reject', hint: 'Closes the case without the actions' },
  { value: 'benign', label: 'Mark benign', hint: 'Closes it as benign; the system may learn a playbook' },
]

export default function CaseFeedbackForm({ tenant, analyst, detail, onSubmitted }: CaseFeedbackFormProps) {
  const [verdict, setVerdict] = useState<FeedbackVerdict>('approve')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<string | null>(null)

  // Same rules as the API (409 otherwise): approve / reject only while awaiting approval;
  // benign also on a closed or auto-closed case.
  const awaiting = detail.status === 'awaiting_approval'
  const closed = detail.status === 'closed' || detail.status === 'auto_closed'
  const canAnswer = (v: FeedbackVerdict) => (v === 'benign' ? awaiting || closed : awaiting)
  const anyAllowed = VERDICTS.some((v) => canAnswer(v.value))
  const effective = canAnswer(verdict) ? verdict : (VERDICTS.find((v) => canAnswer(v.value))?.value ?? verdict)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      const out = await submitFeedback(tenant, detail.id, { verdict: effective, note: note.trim() })
      setResult(
        out.playbook_created ? `Feedback saved. New playbook learned: ${out.playbook_created}.` : 'Feedback saved.',
      )
      setNote('')
      onSubmitted()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save feedback.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="feedback">
      {result && (
        <p className="form-ok" role="status">
          {result}
        </p>
      )}

      {anyAllowed ? (
        <form onSubmit={handleSubmit}>
          <fieldset disabled={busy}>
            <legend>Your verdict</legend>
            <div className="verdict-options">
              {VERDICTS.map((v) => (
                <label key={v.value} className={!canAnswer(v.value) ? 'is-disabled' : ''} title={v.hint}>
                  <input
                    type="radio"
                    name="verdict"
                    value={v.value}
                    checked={effective === v.value}
                    disabled={!canAnswer(v.value)}
                    onChange={() => setVerdict(v.value)}
                  />
                  {v.label}
                </label>
              ))}
            </div>
            <p className="muted small">{VERDICTS.find((v) => v.value === effective)?.hint}</p>
          </fieldset>

          <label className="note-field">
            Reason
            <textarea
              value={note}
              maxLength={NOTE_MAX}
              rows={4}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Why? For example: internal pentest scanner"
            />
            <small className="muted">
              {note.length}/{NOTE_MAX}
            </small>
          </label>

          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}

          <p className="muted small">Submitting as {analyst}</p>
          <button type="submit" className="btn-primary" disabled={busy}>
            {busy ? 'Saving…' : 'Submit feedback'}
          </button>
        </form>
      ) : (
        <p className="muted">This case is still with the agents, so it takes no verdict yet.</p>
      )}

      <h3>Feedback so far</h3>
      {detail.feedback.length === 0 ? (
        <p className="muted">None yet.</p>
      ) : (
        <ul className="feedback-list">
          {detail.feedback.map((f) => (
            <li key={f.id}>
              <strong>{f.verdict}</strong> by {f.analyst} · {timeAgo(f.created_at)}
              {f.note && <p>{f.note}</p>}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
