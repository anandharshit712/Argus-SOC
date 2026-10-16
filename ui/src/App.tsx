import { useState } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import type { Session } from './api/authMock.ts'
import AppShell from './components/AppShell.tsx'
import NotFoundView from './components/NotFoundView.tsx'
import CaseDetailPage from './pages/CaseDetailPage.tsx'
import CaseQueuePage from './pages/CaseQueuePage.tsx'
import DashboardPage from './pages/DashboardPage.tsx'
import ActivityPage from './pages/ActivityPage.tsx'
import LoginPage from './pages/LoginPage.tsx'
import PlaybooksPage from './pages/PlaybooksPage.tsx'

export default function App() {
  const [session, setSession] = useState<Session | null>(null)

  if (!session) return <LoginPage onSignedIn={setSession} />

  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell username={session.username} onSignOut={() => setSession(null)} />}>
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/cases" element={<CaseQueuePage />} />
          <Route path="/cases/:caseId" element={<CaseDetailPage />} />
          <Route path="/playbooks" element={<PlaybooksPage />} />
          <Route path="/activity" element={<ActivityPage />} />
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="*" element={<NotFoundView />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
