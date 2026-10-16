// CaseSummary has no title field, so the Talos category is turned into one.
export function caseTitle(category: string | null | undefined): string {
  if (!category) return 'Uncategorised case'
  const words = category.replace(/_/g, ' ')
  return words.charAt(0).toUpperCase() + words.slice(1)
}

/** "isolate_top_host" -> "Isolate top host". */
export function humanize(value: string): string {
  return caseTitle(value)
}
