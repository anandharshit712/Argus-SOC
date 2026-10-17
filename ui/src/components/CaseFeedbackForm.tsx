import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import type { CaseDetail, FeedbackVerdict } from '../api/apiTypes.ts'
import { submitFeedback } from '../api/argusApi.ts'
import { timeAgo } from '../lib/formatTime.ts'
import { actionLine } from '../lib/decisionText.ts'

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
// The reason is required where it teaches the system: a benign note becomes the IOC owner fact
// shown in Memory next time, and a rejection should say why.
const NOTE_REQUIRED: Record<FeedbackVerdict, boolean> = { approve: false, reject: true, benign: true }

export default function CaseFeedbackForm({ tenant, analyst, detail, onSubmitted }: CaseFeedbackFormProps) {
  const [verdict, setVerdict] = useState<FeedbackVerdict>('approve')
  const [note, setNote] = useState('')
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState<{ playbook: string | null } | null>(null)

  // Same rules as the API (409 otherwise): approve / reject only while awaiting approval;
  // benign also on a closed or auto-closed case. One verdict per case: once there is
  // feedback, the form is replaced by the result.
  const awaiting = detail.status === 'awaiting_approval'
  const closed = detail.status === 'closed' || detail.status === 'auto_closed'
  const hasVerdict = detail.feedback.length > 0
  const canAnswer = (v: FeedbackVerdict) => !hasVerdict && (v === 'benign' ? awaiting || closed : awaiting)
  const anyAllowed = VERDICTS.some((v) => canAnswer(v.value))
  const effective = canAnswer(verdict) ? verdict : (VERDICTS.find((v) => canAnswer(v.value))?.value ?? verdict)
  const noteMissing = NOTE_REQUIRED[effective] && note.trim() === ''

  const decision = detail.decision
  const actions = decision ? decision.actions.map((a) => actionLine(a, decision, detail.findings.shortest_path ?? [])) : []
  const targetCount = decision ? decision.target_hosts.length + decision.target_users.length + decision.target_iocs.length : 0

  async function send() {
    setBusy(true)
    setError(null)
    try {
      const out = await submitFeedback(tenant, detail.id, { verdict: effective, note: note.trim() })
      setSaved({ playbook: out.playbook_created })
      setNote('')
      setConfirming(false)
      onSubmitted()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save feedback.')
      setConfirming(false)
    } finally {
      setBusy(false)
    }
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (noteMissing) {
      setError(effective === 'benign' ? 'Say why it is benign (for example: internal pentest scanner).' : 'Say why you reject it.')
      return
    }
    // Approve runs the actions: ask once more, in the page (no browser dialog).
    if (effective === 'approve' && actions.length > 0 && !confirming) {
      setConfirming(true)
      return
    }
    void send()
  }

  return (
    <div className="feedback">
      {saved && (
        <div className="feedback-result" role="status">
          <strong>Feedback saved.</strong>
          {saved.playbook && (
            <p className="playbook-callout">
              New playbook learned: <strong>{saved.playbook}</strong>. Matching alerts will now be auto-closed.{' '}
              <Link to="/playbooks">View playbooks</Link>
            </p>
          )}
        </div>
      )}

      {anyAllowed ? (
        <form onSubmit={handleSubmit}>
          <fieldset disabled={busy || confirming}>
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
                    onChange={() => {
                      setVerdict(v.value)
                      setError(null)
                    }}
                  />
                  {v.label}
                </label>
              ))}
            </div>
            <p className="muted small">{VERDICTS.find((v) => v.value === effective)?.hint}</p>

            <label className="note-field">
              Reason {NOTE_REQUIRED[effective] ? <span className="required">(required)</span> : <span className="muted small">(optional)</span>}
              <textarea
                value={note}
                maxLength={NOTE_MAX}
                rows={4}
                required={NOTE_REQUIRED[effective]}
                onChange={(e) => setNote(e.target.value)}
                placeholder={effective === 'benign' ? 'Why is it benign? For example: internal pentest scanner' : 'Why?'}
              />
              <small className="muted">
                {note.length}/{NOTE_MAX}
              </small>
            </label>
          </fieldset>

          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}

          {confirming ? (
            <div className="confirm-box" role="alertdialog" aria-label="Confirm approval">
              <p>
                <strong>
                  Approve {actions.length} action{actions.length === 1 ? '' : 's'} on {targetCount} target
                  {targetCount === 1 ? '' : 's'}? (simulated)
                </strong>
              </p>
              <ul>
                {actions.map((a) => (
                  <li key={a}>{a}</li>
                ))}
              </ul>
              <div className="confirm-actions">
                <button type="button" className="btn-primary" onClick={() => void send()} disabled={busy}>
                  {busy ? 'Saving…' : 'Yes, approve'}
                </button>
                <button type="button" className="btn-outline" onClick={() => setConfirming(false)} disabled={busy}>
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <>
              <p className="muted small">Submitting as {analyst}</p>
              <button type="submit" className="btn-primary" disabled={busy}>
                {busy ? 'Saving…' : 'Submit feedback'}
              </button>
            </>
          )}
        </form>
      ) : (
        !saved && (
          <p className="muted">
            {hasVerdict ? 'This case already has a verdict.' : 'This case is still with the agents, so it takes no verdict yet.'}
          </p>
        )
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
