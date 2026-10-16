import { useState, type FormEvent } from 'react'
import { ApiError } from '../api/apiClient.ts'
import type { SessionOut } from '../api/apiTypes.ts'
import { login } from '../api/argusApi.ts'
import './LoginForm.css'

type LoginFormProps = { onSignedIn: (session: SessionOut) => void }

// Same message for an unknown user and a wrong password (the API does not say which).
function signInError(err: unknown): string {
  if (err instanceof ApiError && err.status === 401) return 'Wrong username or password.'
  if (err instanceof ApiError && err.status !== 0 && err.status < 500) return err.message
  return 'Can’t reach the server. Try again shortly.'
}

export default function LoginForm({ onSignedIn }: LoginFormProps) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (!username.trim() || !password) {
      setError('Enter your username and password.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const session = await login(username.trim(), password)
      setBusy(false)
      onSignedIn(session)
    } catch (err) {
      setError(signInError(err))
      setPassword('') // never keep a rejected password in the form
      setBusy(false)
    }
  }

  return (
    <form className="login-form" onSubmit={handleSubmit} noValidate>
      <label className="field">
        <span className="field-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.6">
            <circle cx="12" cy="8" r="4" />
            <path d="M4 21c0-4.4 3.6-7 8-7s8 2.6 8 7" />
          </svg>
        </span>
        <input
          type="text"
          placeholder="Username"
          autoComplete="username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          aria-label="Username"
        />
      </label>

      <label className="field">
        <span className="field-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.6">
            <rect x="5" y="11" width="14" height="10" rx="1.5" />
            <path d="M8 11V8a4 4 0 0 1 8 0v3" />
          </svg>
        </span>
        <input
          type={showPassword ? 'text' : 'password'}
          placeholder="Password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          aria-label="Password"
        />
        <button
          type="button"
          className="field-toggle"
          onClick={() => setShowPassword((v) => !v)}
          aria-label={showPassword ? 'Hide password' : 'Show password'}
          aria-pressed={showPassword}
        >
          <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.6">
            <path d="M2 12s3.6-6 10-6 10 6 10 6-3.6 6-10 6S2 12 2 12z" />
            <circle cx="12" cy="12" r="2.5" />
            {showPassword ? null : <path d="M4 20L20 4" />}
          </svg>
        </button>
      </label>

      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}

      <button type="submit" className="sign-in" disabled={busy}>
        {busy ? 'SIGNING IN…' : 'SIGN IN'}
      </button>

      <p className="form-note">Demo environment — synthetic data only.</p>
    </form>
  )
}
