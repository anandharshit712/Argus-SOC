// Tenant ids are lowercase ("acme"); the UI shows them capitalised ("Acme").
export function tenantLabel(tenant: string): string {
  return tenant.charAt(0).toUpperCase() + tenant.slice(1)
}

// One accent per tenant, so a switch is obvious on screen (and on the demo video).
const TENANT_COLORS: Record<string, string> = { acme: '#4ade6a', globex: '#5eb4ff' }
const FALLBACK_COLORS = ['#c792ea', '#f0c040', '#ff8a5c']

export function tenantColor(tenant: string, all: string[]): string {
  return TENANT_COLORS[tenant] ?? FALLBACK_COLORS[Math.max(0, all.indexOf(tenant)) % FALLBACK_COLORS.length]
}

const TENANT_KEY = 'argus.tenant'

/** The tenant chosen last in this tab, if the user may still see it. */
export function storedTenant(allowed: string[]): string | null {
  try {
    const value = sessionStorage.getItem(TENANT_KEY)
    return value && allowed.includes(value) ? value : null
  } catch {
    return null
  }
}

export function storeTenant(tenant: string): void {
  try {
    sessionStorage.setItem(TENANT_KEY, tenant)
  } catch {
    // Storage blocked: the choice lasts until the page reloads.
  }
}
