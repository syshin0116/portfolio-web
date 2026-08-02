export const AGENT_TOKEN_INTENT_HEADER = "X-Agent-Token-Intent"
export const ANONYMOUS_AGENT_TOKEN_INTENT = "anonymous"
export type AgentTokenIntent = typeof ANONYMOUS_AGENT_TOKEN_INTENT

export function hasAnonymousAgentTokenIntent(request: Request): boolean {
  return (
    request.headers.get(AGENT_TOKEN_INTENT_HEADER) ===
    ANONYMOUS_AGENT_TOKEN_INTENT
  )
}
