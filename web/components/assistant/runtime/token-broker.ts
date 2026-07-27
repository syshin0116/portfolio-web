const TOKEN_ENDPOINT = "/api/agent-token"
export const TOKEN_REFRESH_MARGIN_SECONDS = 60
const MAX_CANCELLATION_STATUS_POLLS = 32
const MAX_RUN_RESOLUTION_POLLS = 32
const MAX_RUN_IDENTIFIER_CODE_UNITS = 128
const RUN_IDENTIFIER_PATTERN = /^[A-Za-z0-9_-]+$/

export class AgentAuthenticationError extends Error {
  readonly status?: number

  constructor(message: string, status?: number) {
    super(message)
    this.name = "AgentAuthenticationError"
    this.status = status
  }
}

interface CachedToken {
  token: string
  expiresAt: number
  identity: string
}

interface RefreshFlight {
  controller: AbortController
  identity: string
  promise: Promise<CachedToken>
  waiters: number
  settled: boolean
}

interface AgentTokenBrokerOptions {
  fetch?: FetchLike
  nowSeconds?: () => number
  refreshMarginSeconds?: number
}

export type FetchLike = (
  input: RequestInfo | URL,
  init?: RequestInit
) => Promise<Response>

export interface AgentCancellationTarget {
  apiUrl: string
  threadId: string
  runId: string
}

export type AgentRunResolutionTarget = Omit<
  AgentCancellationTarget,
  "runId"
>

export interface AgentCancellationSnapshot {
  readonly identity: string
  createRunResolverFetch(target: AgentRunResolutionTarget): FetchLike
  createFetch(target: AgentCancellationTarget): FetchLike
  dispose(): void
}

interface BrokerInspection {
  cached: boolean
  refreshing: boolean
  sealed: boolean
}

const brokerInspectionReaders = new WeakMap<
  AgentTokenBroker,
  () => BrokerInspection
>()

function decodeJwtExpiration(token: string): number {
  const parts = token.split(".")
  if (parts.length !== 3) {
    throw new AgentAuthenticationError("Agent token is not a JWT")
  }

  try {
    const base64 = parts[1]!.replace(/-/g, "+").replace(/_/g, "/")
    const padded = base64.padEnd(Math.ceil(base64.length / 4) * 4, "=")
    const json =
      typeof atob === "function"
        ? decodeURIComponent(
            Array.from(atob(padded), (character) =>
              `%${character.charCodeAt(0).toString(16).padStart(2, "0")}`
            ).join("")
          )
        : Buffer.from(padded, "base64").toString("utf8")
    const payload = JSON.parse(json) as { exp?: unknown }
    if (typeof payload.exp !== "number" || !Number.isFinite(payload.exp)) {
      throw new Error("missing exp")
    }
    return payload.exp
  } catch (error) {
    if (error instanceof AgentAuthenticationError) throw error
    throw new AgentAuthenticationError("Agent token has an invalid exp claim")
  }
}

function abortReason(signal: AbortSignal): unknown {
  return signal.reason ?? new DOMException("The operation was aborted", "AbortError")
}

async function waitForFlight<T>(
  promise: Promise<T>,
  signal: AbortSignal
): Promise<T> {
  signal.throwIfAborted()

  return await new Promise<T>((resolve, reject) => {
    const onAbort = () => reject(abortReason(signal))
    signal.addEventListener("abort", onAbort, { once: true })
    promise.then(resolve, reject).finally(() => {
      signal.removeEventListener("abort", onAbort)
    })
  })
}

function withAuthorization(init: RequestInit, token: string): RequestInit {
  const headers = new Headers(init.headers)
  headers.set("Authorization", `Bearer ${token}`)
  return { ...init, headers }
}

function requestMethod(
  input: RequestInfo | URL,
  init: RequestInit | undefined
): string {
  const requestMethod =
    typeof Request !== "undefined" && input instanceof Request
      ? input.method
      : undefined
  return (init?.method ?? requestMethod ?? "GET").toUpperCase()
}

function requestHasBody(
  input: RequestInfo | URL,
  init: RequestInit | undefined
): boolean {
  if (init?.body !== undefined && init.body !== null) return true
  return (
    typeof Request !== "undefined" &&
    input instanceof Request &&
    input.body !== null
  )
}

function validatedRunIdentifier(value: string, label: string): string {
  if (
    value.length === 0 ||
    value.length > MAX_RUN_IDENTIFIER_CODE_UNITS ||
    !RUN_IDENTIFIER_PATTERN.test(value)
  ) {
    throw new AgentAuthenticationError(
      `Cancellation ${label} is not a safe identifier`
    )
  }
  return value
}

/**
 * A bearer credential captured before a stream starts and restricted to one
 * run's POST /cancel plus bounded read-only status polling. It bypasses the
 * broker's refresh path by design, so a 401 can never mint another identity's
 * token while an old run is being disposed.
 */
class RunScopedCancellationSnapshot implements AgentCancellationSnapshot {
  readonly identity: string
  readonly #fetch: FetchLike
  #token: string | undefined
  #bound = false
  #resolutionBound = false
  #resolutionPolls = 0
  #cancelCalls = 0
  #statusPolls = 0
  #expectedRunsList?: URL

  constructor(identity: string, token: string, fetchImplementation: FetchLike) {
    this.identity = identity
    this.#token = token
    this.#fetch = fetchImplementation
  }

  createRunResolverFetch(target: AgentRunResolutionTarget): FetchLike {
    if (this.#resolutionBound || this.#bound) {
      throw new AgentAuthenticationError(
        "Run-resolution credential is already bound"
      )
    }
    const apiUrl = new URL(target.apiUrl)
    if (
      apiUrl.search ||
      apiUrl.hash ||
      apiUrl.username ||
      apiUrl.password
    ) {
      throw new AgentAuthenticationError(
        "Run-resolution API URL must not contain query or fragment data"
      )
    }
    const threadId = validatedRunIdentifier(target.threadId, "thread ID")
    this.#expectedRunsList = new URL(
      `${apiUrl.toString().replace(/\/$/, "")}/threads/${threadId}/runs`
    )
    this.#resolutionBound = true

    return async (input, init) => {
      const token = this.#token
      if (!token) {
        throw new AgentAuthenticationError(
          "Run-resolution credential has been disposed"
        )
      }
      if (this.#bound) {
        throw new AgentAuthenticationError(
          "Run-resolution credential was closed after run binding"
        )
      }
      const url = new URL(
        typeof Request !== "undefined" && input instanceof Request
          ? input.url
          : String(input)
      )
      const method = requestMethod(input, init)
      const expected = this.#expectedRunsList
      const isExactList =
        expected !== undefined &&
        !url.username &&
        !url.password &&
        url.origin === expected.origin &&
        url.pathname === expected.pathname &&
        method === "GET" &&
        !url.hash &&
        !requestHasBody(input, init) &&
        url.searchParams.size === 2 &&
        url.searchParams.get("limit") === "10" &&
        url.searchParams.get("offset") === "0"
      if (
        !isExactList ||
        this.#resolutionPolls >= MAX_RUN_RESOLUTION_POLLS
      ) {
        throw new AgentAuthenticationError(
          "Run-resolution credential rejected an out-of-scope request"
        )
      }
      this.#resolutionPolls += 1
      return await this.#fetch(
        url.toString(),
        withAuthorization(
          {
            method: "GET",
            signal:
              init?.signal instanceof AbortSignal ? init.signal : undefined,
            cache: "no-store",
            credentials: "omit",
            redirect: "error",
            referrerPolicy: "no-referrer",
          },
          token
        )
      )
    }
  }

  createFetch(target: AgentCancellationTarget): FetchLike {
    if (this.#bound) {
      throw new AgentAuthenticationError(
        "Cancellation credential is already bound to a run"
      )
    }
    const apiUrl = new URL(target.apiUrl)
    if (
      apiUrl.search ||
      apiUrl.hash ||
      apiUrl.username ||
      apiUrl.password
    ) {
      throw new AgentAuthenticationError(
        "Cancellation API URL must not contain query or fragment data"
      )
    }
    const threadId = validatedRunIdentifier(target.threadId, "thread ID")
    const runId = validatedRunIdentifier(target.runId, "run ID")
    const runUrl = `${apiUrl.toString().replace(/\/$/, "")}/threads/${threadId}/runs/${runId}`
    const expectedRun = new URL(runUrl)
    const expectedCancel = new URL(`${runUrl}/cancel`)
    if (
      this.#expectedRunsList !== undefined &&
      (this.#expectedRunsList.origin !== expectedRun.origin ||
        this.#expectedRunsList.pathname !==
          `${expectedRun.pathname.slice(
            0,
            expectedRun.pathname.lastIndexOf("/")
          )}`)
    ) {
      throw new AgentAuthenticationError(
        "Cancellation target does not match the resolved thread"
      )
    }
    this.#bound = true

    return async (input, init) => {
      const token = this.#token
      if (!token) {
        throw new AgentAuthenticationError(
          "Cancellation credential has been disposed"
        )
      }
      const url = new URL(
        typeof Request !== "undefined" && input instanceof Request
          ? input.url
          : String(input)
      )
      const method = requestMethod(input, init)
      if (
        url.hash ||
        url.username ||
        url.password ||
        requestHasBody(input, init)
      ) {
        throw new AgentAuthenticationError(
          "Cancellation credential rejected an out-of-scope request"
        )
      }

      const isCancel =
        url.origin === expectedCancel.origin &&
        url.pathname === expectedCancel.pathname &&
        method === "POST" &&
        url.searchParams.size === 2 &&
        url.searchParams.get("wait") === "0" &&
        url.searchParams.get("action") === "interrupt"
      const isStatus =
        url.origin === expectedRun.origin &&
        url.pathname === expectedRun.pathname &&
        url.search === "" &&
        method === "GET"

      if (isCancel) {
        if (this.#cancelCalls !== 0) {
          throw new AgentAuthenticationError(
            "Cancellation was already attempted for this run"
          )
        }
        this.#cancelCalls += 1
      } else if (isStatus) {
        if (
          this.#cancelCalls !== 1 ||
          this.#statusPolls >= MAX_CANCELLATION_STATUS_POLLS
        ) {
          throw new AgentAuthenticationError(
            "Cancellation status polling exceeded its scope"
          )
        }
        this.#statusPolls += 1
      } else {
        throw new AgentAuthenticationError(
          "Cancellation credential rejected an out-of-scope request"
        )
      }

      const authorized = withAuthorization(
        {
          method,
          signal:
            init?.signal instanceof AbortSignal ? init.signal : undefined,
          cache: "no-store",
          credentials: "omit",
          redirect: "error",
          referrerPolicy: "no-referrer",
        },
        token
      )
      return await this.#fetch(url.toString(), authorized)
    }
  }

  dispose(): void {
    this.#token = undefined
  }
}

/**
 * Identity-partitioned bearer-token broker for the LangGraph SDK.
 *
 * A refresh is shared by concurrent requests, but each waiter retains its own
 * AbortSignal. The underlying token request is cancelled only when every
 * waiter has gone away.
 */
export class AgentTokenBroker {
  readonly #fetch: FetchLike
  readonly #nowSeconds: () => number
  readonly #refreshMarginSeconds: number
  #identity: string
  #cached?: CachedToken
  #flight?: RefreshFlight
  #sealed = false

  constructor(identity: string, options: AgentTokenBrokerOptions = {}) {
    if (!identity) {
      throw new AgentAuthenticationError("Agent identity is required")
    }
    this.#identity = identity
    // Browser `window.fetch` rejects an arbitrary receiver. Wrap the global
    // instead of storing it as a method-valued field that would be invoked
    // with the broker instance as `this`.
    this.#fetch =
      options.fetch ?? ((input, init) => fetch(input, init))
    this.#nowSeconds = options.nowSeconds ?? (() => Date.now() / 1_000)
    this.#refreshMarginSeconds =
      options.refreshMarginSeconds ?? TOKEN_REFRESH_MARGIN_SECONDS
    brokerInspectionReaders.set(this, () => ({
      cached: this.#cached !== undefined,
      refreshing: this.#flight !== undefined,
      sealed: this.#sealed,
    }))
  }

  get identity(): string {
    return this.#identity
  }

  setIdentity(identity: string): void {
    this.#assertOpen()
    if (!identity) {
      throw new AgentAuthenticationError("Agent identity is required")
    }
    if (identity === this.#identity) return
    this.#identity = identity
    this.clear()
  }

  clear(): void {
    this.#cached = undefined
    this.#flight?.controller.abort(
      new DOMException("Agent identity changed", "AbortError")
    )
    this.#flight = undefined
  }

  seal(): void {
    if (this.#sealed) return
    this.#sealed = true
    // A run-scoped cancellation snapshot owns its own restricted token copy.
    // The general-purpose bearer no longer has a legitimate use after seal.
    this.#cached = undefined
    this.#flight?.controller.abort(
      new DOMException("Agent token broker disposed", "AbortError")
    )
    this.#flight = undefined
  }

  async captureCancellationSnapshot(
    signal: AbortSignal
  ): Promise<AgentCancellationSnapshot> {
    const identity = this.#identity
    const token = await this.get(signal)
    signal.throwIfAborted()
    if (this.#sealed || this.#identity !== identity) {
      throw new DOMException("Agent identity changed", "AbortError")
    }
    return new RunScopedCancellationSnapshot(identity, token, this.#fetch)
  }

  async get(signal: AbortSignal, forceRefresh = false): Promise<string> {
    this.#assertOpen()
    signal.throwIfAborted()
    const cached = this.#cached
    const now = this.#nowSeconds()
    if (
      !forceRefresh &&
      cached?.identity === this.#identity &&
      cached.expiresAt - now > this.#refreshMarginSeconds
    ) {
      return cached.token
    }

    if (forceRefresh) this.#cached = undefined
    const flight = this.#getOrCreateFlight()
    flight.waiters += 1
    try {
      return (await waitForFlight(flight.promise, signal)).token
    } finally {
      flight.waiters -= 1
      if (flight.waiters === 0 && !flight.settled) {
        flight.controller.abort(
          new DOMException("No token refresh waiters remain", "AbortError")
        )
      }
    }
  }

  async onRequest(_url: URL, init: RequestInit): Promise<RequestInit> {
    const signal =
      init.signal instanceof AbortSignal
        ? init.signal
        : new AbortController().signal
    return withAuthorization(init, await this.get(signal))
  }

  /**
   * Fetch implementation supplied to every LangGraph SDK surface.
   *
   * The SDK's onRequest hook has already attached the normal token. A 401
   * invalidates it, coalesces a forced refresh, and retries the exact request
   * once. A second 401 is returned to the SDK unchanged.
   */
  readonly fetchWithAuthRetry: FetchLike = async (input, init) => {
    this.#assertOpen()
    const requestInit = init ?? {}
    const signal =
      requestInit.signal instanceof AbortSignal
        ? requestInit.signal
        : new AbortController().signal
    signal.throwIfAborted()

    const firstResponse = await this.#fetch(input, requestInit)
    if (firstResponse.status !== 401) return firstResponse

    await firstResponse.body?.cancel()
    this.#assertOpen()
    const refreshedToken = await this.get(signal, true)
    return await this.#fetch(input, withAuthorization(requestInit, refreshedToken))
  }

  #getOrCreateFlight(): RefreshFlight {
    this.#assertOpen()
    const current = this.#flight
    if (
      current &&
      current.identity === this.#identity &&
      !current.controller.signal.aborted
    ) {
      return current
    }

    const controller = new AbortController()
    const identity = this.#identity
    const flight: RefreshFlight = {
      controller,
      identity,
      waiters: 0,
      settled: false,
      promise: Promise.resolve({ token: "", expiresAt: 0, identity }),
    }
    flight.promise = this.#mint(identity, controller.signal)
      .then((token) => {
        if (this.#sealed || this.#identity !== identity) {
          throw new DOMException("Agent identity changed", "AbortError")
        }
        this.#cached = token
        return token
      })
      .finally(() => {
        flight.settled = true
        if (this.#flight === flight) this.#flight = undefined
      })
    this.#flight = flight
    return flight
  }

  async #mint(identity: string, signal: AbortSignal): Promise<CachedToken> {
    const response = await this.#fetch(TOKEN_ENDPOINT, {
      method: "POST",
      cache: "no-store",
      credentials: "same-origin",
      signal,
    })
    if (!response.ok) {
      throw new AgentAuthenticationError(
        response.status === 403
          ? "이 계정은 에이전트를 사용할 수 없습니다."
          : "에이전트 인증을 갱신하지 못했습니다.",
        response.status
      )
    }

    const body = (await response.json()) as { token?: unknown }
    if (typeof body.token !== "string" || body.token.trim() === "") {
      throw new AgentAuthenticationError("Agent token response is malformed")
    }
    const token = body.token.trim()
    const expiresAt = decodeJwtExpiration(token)
    if (expiresAt <= this.#nowSeconds()) {
      throw new AgentAuthenticationError("Agent token is already expired")
    }
    return { token, expiresAt, identity }
  }

  #assertOpen(): void {
    if (this.#sealed) {
      throw new AgentAuthenticationError("Agent token broker is disposed")
    }
  }
}

export const tokenBrokerTesting = {
  decodeJwtExpiration,
  inspect(broker: AgentTokenBroker): BrokerInspection {
    const read = brokerInspectionReaders.get(broker)
    if (!read) throw new Error("Unknown AgentTokenBroker")
    return read()
  },
  withAuthorization,
}
