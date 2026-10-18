// Tenant ids are lowercase ("acme"); the UI shows them capitalised ("Acme").
export function tenantLabel(tenant: string): string {
  return tenant.charAt(0).toUpperCase() + tenant.slice(1)
}

// Every tenant uses the theme green, so the UI keeps one colour scheme; the tenant
// name in the picker and the page headings shows which tenant is selected.
const TENANT_ACCENT = '#4ade6a' // --accent in index.css

export function tenantColor(_tenant: string, _all: string[]): string {
  return TENANT_ACCENT
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
