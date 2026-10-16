export function timeAgo(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return '—'
  const minutes = Math.max(0, Math.round((now - new Date(iso).getTime()) / 60_000))
  if (Number.isNaN(minutes)) return '—'
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.round(hours / 24)}d ago`
}

export function formatSeconds(seconds: number | null): string {
  if (seconds === null) return '—'
  return seconds < 60 ? `${Math.round(seconds)} s` : `${Math.round(seconds / 60)} min`
}

/** "14:32" in the viewer's time zone. */
export function clockTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })
}
