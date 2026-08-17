import { useEffect, useState } from "react"

import { normalizeAgentApiUrl } from "./agent-config"

const READY_PATH = "/ready"
const ATTEMPT_TIMEOUT_MS = 30_000
const RETRY_DELAY_MS = 2_000
const MAX_ATTEMPTS = 4

/**
 * The agent scales to zero, so the first visitor after an idle period otherwise
 * waits out a full container boot inside their first question. Probing `/ready`
 * on mount moves that boot into the time the visitor spends reading and typing.
 */
export type AgentWarmupPhase = "warming" | "ready" | "unavailable"

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
 * Resolves once the agent answers its readiness probe. A cold Cloud Run
 * revision holds the request open while the container boots, so an attempt
 * normally succeeds by waiting rather than by retrying; the retries only cover
 * a boot that outruns one attempt timeout.
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
    } catch {
      options.signal.throwIfAborted()
    }
    if (attempt < MAX_ATTEMPTS - 1) await sleep(RETRY_DELAY_MS, options.signal)
  }
  return false
}

export function useAgentWarmup(enabled: boolean): AgentWarmupPhase {
  const [phase, setPhase] = useState<AgentWarmupPhase>("warming")

  useEffect(() => {
    if (!enabled) return
    const parsed = normalizeAgentApiUrl(process.env.NEXT_PUBLIC_AGENT_API_URL)
    if ("error" in parsed) {
      setPhase("unavailable")
      return
    }
    const controller = new AbortController()
    warmAgent({ apiUrl: parsed.apiUrl, signal: controller.signal })
      .then((ready) => setPhase(ready ? "ready" : "unavailable"))
      .catch(() => {
        // Only an unmount aborts the probe; leave the phase for the next mount.
      })
    return () => controller.abort()
  }, [enabled])

  return phase
}
