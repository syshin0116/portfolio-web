interface ProviderEmailVerification {
  provider: string | undefined
  email: string | null | undefined
  accessToken: string | undefined
  profile: unknown
  fetchImpl?: (
    input: RequestInfo | URL,
    init?: RequestInit
  ) => Promise<Response>
  signal?: AbortSignal
}

interface GitHubEmail {
  email?: unknown
  primary?: unknown
  verified?: unknown
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function normalizedEmail(value: string | null | undefined): string | null {
  const normalized = value?.trim().toLowerCase()
  return normalized ? normalized : null
}

export async function hasVerifiedProviderEmail({
  provider,
  email,
  accessToken,
  profile,
  fetchImpl = fetch,
  signal = AbortSignal.timeout(5_000),
}: ProviderEmailVerification): Promise<boolean> {
  const expected = normalizedEmail(email)
  if (expected === null) return false

  if (provider === "google") {
    return (
      isRecord(profile) &&
      profile.email_verified === true &&
      normalizedEmail(
        typeof profile.email === "string" ? profile.email : null
      ) === expected
    )
  }

  if (provider !== "github" || !accessToken) return false

  try {
    const response = await fetchImpl("https://api.github.com/user/emails", {
      headers: {
        Accept: "application/vnd.github+json",
        Authorization: `Bearer ${accessToken}`,
        "X-GitHub-Api-Version": "2022-11-28",
      },
      signal,
    })
    if (!response.ok) return false

    const payload: unknown = await response.json()
    if (!Array.isArray(payload)) return false
    return payload.some((candidate: unknown) => {
      if (!isRecord(candidate)) return false
      const githubEmail = candidate as GitHubEmail
      return (
        githubEmail.primary === true &&
        githubEmail.verified === true &&
        normalizedEmail(
          typeof githubEmail.email === "string"
            ? githubEmail.email
            : null
        ) === expected
      )
    })
  } catch {
    return false
  }
}
