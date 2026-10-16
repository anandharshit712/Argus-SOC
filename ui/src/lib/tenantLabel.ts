// Tenant ids are lowercase ("acme"); the UI shows them capitalised ("Acme").
export function tenantLabel(tenant: string): string {
  return tenant.charAt(0).toUpperCase() + tenant.slice(1)
}
