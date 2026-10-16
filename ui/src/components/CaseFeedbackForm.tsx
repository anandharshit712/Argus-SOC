import { useState, type FormEvent } from 'react'
import type { CaseDetail, FeedbackVerdict } from '../api/apiTypes.ts'
import { submitFeedback } from '../api/mockCaseDetail.ts'
import type { Tenant } from '../api/mockData.ts'
import { timeAgo } from '../lib/formatTime.ts'

type CaseFeedbackFormProps = {
  tenant: Tenant
  analyst: string
  detail: CaseDetail
  onSubmitted: () => void
}

const NOTE_MAX = 500
const VERDICTS: { value: FeedbackVerdict; label: string }[] = [
  { value: 'approve', label: 'Approve' },
  { value: 'reject', label: 'Reject' },
  { value: 'benign', label: 'Mark benign' },
]

export default function CaseFeedbackForm({ tenant, analyst, detail, onSubmitted }: CaseFeedbackFormProps) {
  const [verdict, setVerdict] = useState<FeedbackVerdict>('approve')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<string | null>(null)

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
      const out = await submitFeedback(tenant, detail.id, { verdict: effective, note: note.trim(), analyst })
      setResult(out.playbook_created ? `Feedback saved. Playbook created: ${out.playbook_created}.` : 'Feedback saved.')
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
      {anyAllowed ? (
        <form onSubmit={handleSubmit}>
          <fieldset disabled={busy}>
            <legend>Your verdict</legend>
            <div className="verdict-options">
              {VERDICTS.map((v) => (
                <label key={v.value} className={!canAnswer(v.value) ? 'is-disabled' : ''}>
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
            <small className="muted">{note.length}/{NOTE_MAX}</small>
          </label>

          {error && <p className="form-error" role="alert">{error}</p>}
          {result && <p className="form-ok" role="status">{result}</p>}

          <button type="submit" className="btn-primary" disabled={busy}>
            {busy ? 'Saving…' : 'Submit feedback'}
          </button>
        </form>
      ) : (
        <p className="muted">This case is not awaiting approval, so it takes no verdict yet.</p>
      )}

      <h3>Feedback so far</h3>
      {detail.feedback.length === 0 ? (
        <p className="muted">None yet.</p>
      ) : (
        <ul className="feedback-list">
          {detail.feedback.map((f) => (
            <li key={f.feedback_id}>
              <strong>{f.verdict}</strong> by {f.analyst} · {timeAgo(f.at)}
              {f.note && <p>{f.note}</p>}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
