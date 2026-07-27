const LOCAL_AGENT_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]"])

export type AgentApiUrlResult =
  | { apiUrl: string }
  | { error: string }

/**
 * The agent endpoint is an origin, not a general URL prefix. Production must
 * use HTTPS; local development may use HTTP(S) on exact loopback hostnames.
 */
export function normalizeAgentApiUrl(
  rawApiUrl: string | undefined
): AgentApiUrlResult {
  const raw = rawApiUrl?.trim()
  if (!raw) {
    return { error: "에이전트 API 주소가 설정되지 않았습니다." }
  }

  try {
    const url = new URL(raw)
    const isLocal = LOCAL_AGENT_HOSTS.has(url.hostname)
    const protocolAllowed = isLocal
      ? url.protocol === "http:" || url.protocol === "https:"
      : url.protocol === "https:"

    if (!protocolAllowed) {
      return {
        error: isLocal
          ? "로컬 에이전트 API는 HTTP 또는 HTTPS 주소여야 합니다."
          : "에이전트 API는 HTTPS 주소여야 합니다.",
      }
    }
    if (url.username || url.password || url.search || url.hash) {
      return {
        error:
          "에이전트 API 주소에는 인증 정보, 쿼리, 프래그먼트를 넣을 수 없습니다.",
      }
    }
    if (url.pathname !== "/") {
      return {
        error: "에이전트 API 주소는 경로가 없는 origin이어야 합니다.",
      }
    }
    if (raw !== url.origin && raw !== `${url.origin}/`) {
      return {
        error: "에이전트 API 주소는 정규화된 origin 형식이어야 합니다.",
      }
    }
    return { apiUrl: url.origin }
  } catch {
    return { error: "에이전트 API 주소가 올바르지 않습니다." }
  }
}
