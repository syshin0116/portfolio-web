const READY_PATH = "/ready"
const ATTEMPT_TIMEOUT_MS = 30_000
const RETRY_DELAY_MS = 2_000
const MAX_ATTEMPTS = 4
const RETRYABLE_STATUSES = new Set([408, 429])

type FetchLike = (
  input: RequestInfo | URL,
  init?: RequestInit
) => Promise<Response>

interface WarmAgentOptions {
  apiUrl: string
  fetch?: FetchLike
  signal: AbortSignal
  sleep?: (ms: number, signal: AbortSignal) => Promise<void>
}

function delay(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", onAbort)
      resolve()
    }, ms)
    const onAbort = () => {
      clearTimeout(timer)
      reject(signal.reason)
    }
    signal.addEventListener("abort", onAbort, { once: true })
  })
}

/**
 * Resolves once the agent itself answers, which serves two purposes: the agent
 * scales to zero, so probing on mount moves the container boot into the time
 * the visitor spends reading and typing, and a minted credential alone proves
 * only that Vercel answered - the connection state needs the agent.
 *
 * A cold Cloud Run revision holds the request open while the container boots,
 * so an attempt normally succeeds by waiting rather than by retrying; the
 * retries only cover a boot that outruns one attempt timeout.
 */
export async function warmAgent(options: WarmAgentOptions): Promise<boolean> {
  const fetchImpl = options.fetch ?? ((input, init) => fetch(input, init))
  const sleep = options.sleep ?? delay
  const target = new URL(READY_PATH, options.apiUrl)

  for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt += 1) {
    options.signal.throwIfAborted()
    const attemptSignal = AbortSignal.any([
      options.signal,
      AbortSignal.timeout(ATTEMPT_TIMEOUT_MS),
    ])
    try {
      const response = await fetchImpl(target, {
        method: "GET",
        cache: "no-store",
        credentials: "omit",
        mode: "cors",
        redirect: "error",
        referrerPolicy: "no-referrer",
        signal: attemptSignal,
      })
      await response.body?.cancel()
      if (response.ok) return true
      // A booting or overloaded revision answers again; a route that is not
      // there will not appear on a retry, and each retry costs a console error.
      if (!RETRYABLE_STATUSES.has(response.status) && response.status < 500) {
        return false
      }
    } catch {
      options.signal.throwIfAborted()
    }
    if (attempt < MAX_ATTEMPTS - 1) await sleep(RETRY_DELAY_MS, options.signal)
  }
  return false
}
