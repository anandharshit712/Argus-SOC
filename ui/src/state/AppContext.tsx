import { createContext, useContext } from 'react'

// Shared by the shell and every page: who is signed in, which tenant is shown, whether polling is on.
export type AppState = {
  username: string
  displayName: string
  /** Tenants the signed-in user may see (from the session). */
  tenants: string[]
  tenant: string
  setTenant: (tenant: string) => void
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
