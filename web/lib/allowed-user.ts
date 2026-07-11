export function isAllowedEmail(
  email: string | null | undefined,
  configured = process.env.AUTH_ALLOWED_EMAILS ?? "",
  nodeEnv = process.env.NODE_ENV
): boolean {
  if (!email) return false
  const allowed = new Set(
    configured
      .split(",")
      .map((value) => value.trim().toLowerCase())
      .filter(Boolean)
  )
  if (allowed.size === 0) return nodeEnv !== "production"
  return allowed.has(email.toLowerCase())
}

export function isAdminEmail(
  email: string | null | undefined,
  configured = process.env.AUTH_ADMIN_EMAILS ?? ""
): boolean {
  if (!email) return false
  const admins = new Set(
    configured
      .split(",")
      .map((value) => value.trim().toLowerCase())
      .filter(Boolean)
  )
  return admins.has(email.toLowerCase())
}
