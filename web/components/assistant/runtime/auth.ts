export const DEFAULT_TOKEN_REFRESH_MARGIN_SECONDS = 60

export type AgentRequestPurpose = "event-stream" | "command"

export interface AgentAccessToken {
  /** Raw bearer token, without the `Bearer` prefix. */
  token: string
  /** Expiration as Unix epoch seconds, matching `/api/agent-token`. */
  expiresAt: number
}

export interface AgentOnRequestContext {
  purpose: AgentRequestPurpose
  threadId: string
  url: string
  signal: AbortSignal
}

/**
 * Called asynchronously before an authenticated request needs a fresh token.
 *
 * The transport owns caching so callers cannot accidentally capture a token
 * once at component mount and receive a mid-conversation 401.
 */
export type AgentOnRequest = (
  context: AgentOnRequestContext
) => Promise<AgentAccessToken>

export class AgentTokenError extends Error {
  constructor(message: string) {
    super(message)
    this.name = "AgentTokenError"
  }
}

interface RefreshingAgentTokenOptions {
  refreshMarginSeconds?: number
  nowSeconds?: () => number
}

export class RefreshingAgentToken {
  readonly #onRequest: AgentOnRequest
  readonly #refreshMarginSeconds: number
  readonly #nowSeconds: () => number
  #cached: AgentAccessToken | undefined

  constructor(
    onRequest: AgentOnRequest,
    options: RefreshingAgentTokenOptions = {}
  ) {
    const margin =
      options.refreshMarginSeconds ?? DEFAULT_TOKEN_REFRESH_MARGIN_SECONDS
    if (!Number.isFinite(margin) || margin < 0) {
      throw new AgentTokenError(
        "Token refresh margin must be a non-negative number"
      )
    }

    this.#onRequest = onRequest
    this.#refreshMarginSeconds = margin
    this.#nowSeconds = options.nowSeconds ?? (() => Date.now() / 1_000)
  }

  clear(): void {
    this.#cached = undefined
  }

  async get(context: AgentOnRequestContext): Promise<string> {
    context.signal.throwIfAborted()
    const now = this.#nowSeconds()
    const cached = this.#cached
    if (
      cached &&
      cached.expiresAt - now > this.#refreshMarginSeconds
    ) {
      return cached.token
    }

    const token = await this.#onRequest(context)
    context.signal.throwIfAborted()
    const refreshedAt = this.#nowSeconds()
    this.#validate(token, refreshedAt)
    const normalized = { ...token, token: token.token.trim() }
    this.#cached = normalized
    return normalized.token
  }

  #validate(token: AgentAccessToken, now: number): void {
    if (typeof token.token !== "string" || token.token.trim().length === 0) {
      throw new AgentTokenError("onRequest must return a non-empty token")
    }
    if (!Number.isFinite(token.expiresAt)) {
      throw new AgentTokenError("onRequest must return a finite expiresAt")
    }
    if (token.expiresAt <= now) {
      throw new AgentTokenError("onRequest returned an expired token")
    }
  }
}
