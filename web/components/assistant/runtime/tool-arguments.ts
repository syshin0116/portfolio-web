// Only the search tools take a "query". read_post takes a path, graph_traverse a
// slug, metadata_filter a set of constraints - reading one key left every other
// tool showing the not-provided fallback, which blamed the server for a value it
// had actually sent.
const TOOL_ARGUMENT_PRIORITY = [
  "query",
  "path",
  "file_path",
  "slug",
  "description",
] as const
const MAX_ARGUMENT_TEXT = 1_000
const MAX_ARGUMENT_PAIRS = 4

export function scalarText(value: unknown): string | undefined {
  if (typeof value === "string") return value.trim() || undefined
  if (typeof value === "number" && Number.isFinite(value)) return String(value)
  if (typeof value === "boolean") return String(value)
  if (Array.isArray(value)) {
    const parts = value.map(scalarText).filter((part) => part !== undefined)
    return parts.length ? parts.join(", ") : undefined
  }
  return undefined
}

export function toolArgumentSummary(argsText: string): string | undefined {
  if (!argsText) return undefined
  let parsed: unknown
  try {
    parsed = JSON.parse(argsText)
  } catch {
    return undefined
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    return undefined
  }
  const entries = Object.entries(parsed as Record<string, unknown>)

  for (const key of TOOL_ARGUMENT_PRIORITY) {
    const primary = scalarText((parsed as Record<string, unknown>)[key])
    if (primary) return primary.slice(0, MAX_ARGUMENT_TEXT)
  }

  const pairs: string[] = []
  for (const [key, value] of entries) {
    const text = scalarText(value)
    if (!text) continue
    pairs.push(`${key}: ${text}`)
    if (pairs.length === MAX_ARGUMENT_PAIRS) break
  }
  return pairs.length ? pairs.join(" · ").slice(0, MAX_ARGUMENT_TEXT) : undefined
}
