// CaseSummary has no title field, so the Talos category is turned into one.
export function caseTitle(category: string): string {
  const words = category.replace(/_/g, ' ')
  return words.charAt(0).toUpperCase() + words.slice(1)
}
