import { createContext, useContext } from 'react'
import type { Tenant } from '../api/mockData.ts'

// Shared by the shell and every page: which tenant is shown, whether polling is on, who is signed in.
export type AppState = {
  username: string
  tenant: Tenant
  setTenant: (tenant: Tenant) => void
  live: boolean
  setLive: (live: boolean) => void
  signOut: () => void
}

export const AppContext = createContext<AppState | null>(null)

export function useApp(): AppState {
  const value = useContext(AppContext)
  if (!value) throw new Error('useApp must be used inside the app shell')
  return value
}
