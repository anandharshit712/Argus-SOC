import { useEffect, useState } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { loadSession, onUnauthorized, saveSession } from './api/apiClient.ts'
import type { SessionOut } from './api/apiTypes.ts'
import { fetchMe, logout } from './api/argusApi.ts'
import AppShell from './components/AppShell.tsx'
import NotFoundView from './components/NotFoundView.tsx'
import ActivityPage from './pages/ActivityPage.tsx'
import CaseDetailPage from './pages/CaseDetailPage.tsx'
import CaseQueuePage from './pages/CaseQueuePage.tsx'
import DashboardPage from './pages/DashboardPage.tsx'
import LoginPage from './pages/LoginPage.tsx'
import PlaybooksPage from './pages/PlaybooksPage.tsx'

export default function App() {
  // A session in sessionStorage survives a reload; closing the tab signs out.
  const [session, setSession] = useState<SessionOut | null>(() => loadSession())

  // Any 401 from the API (expired token, API secret changed) sends the user back to sign in.
  useEffect(() => onUnauthorized(() => setSession(null)), [])

  // On load, confirm a stored token is still valid (the API may have restarted with a new secret).
  useEffect(() => {
    if (!loadSession()) return
    fetchMe()
      .then((me) =>
        setSession((current) => {
          if (!current) return current
          const updated = { ...current, ...me }
          saveSession(updated)
          return updated
        }),
      )
      .catch(() => {
        // 401 is handled by onUnauthorized; a network error keeps the session for the next try.
      })
  }, [])

  function handleSignedIn(next: SessionOut) {
    saveSession(next)
    setSession(next)
  }

  function handleSignOut() {
    // Tokens are stateless; logout only tells the API. Drop the token whatever it answers.
    void logout().catch(() => undefined).finally(() => saveSession(null))
    setSession(null)
  }

  // The URL is kept while signed out, so after signing in the user lands where they were.
  if (!session) return <LoginPage onSignedIn={handleSignedIn} />

  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell key={session.username} session={session} onSignOut={handleSignOut} />}>
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/cases" element={<CaseQueuePage />} />
          <Route path="/cases/:caseId" element={<CaseDetailPage />} />
          <Route path="/playbooks" element={<PlaybooksPage />} />
          <Route path="/activity" element={<ActivityPage />} />
          <Route path="*" element={<NotFoundView />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
