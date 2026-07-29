export function canonicalAuthSubject(value: unknown): string | null {
  if (typeof value === "string") {
    return value.length > 0 && value.trim() === value ? value : null
  }

  if (
    typeof value === "number" &&
    Number.isSafeInteger(value) &&
    value >= 0
  ) {
    return String(value)
  }

  return null
}
