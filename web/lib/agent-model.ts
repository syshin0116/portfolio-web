export const AGENT_MODELS = [
  "gpt-5.6-luna",
  "gpt-5.6-terra",
  "gpt-5.6-sol",
] as const

export type AgentModel = (typeof AGENT_MODELS)[number]

export const DEFAULT_AGENT_MODEL: AgentModel = "gpt-5.6-luna"

export function isAgentModel(value: unknown): value is AgentModel {
  return (
    typeof value === "string" &&
    (AGENT_MODELS as readonly string[]).includes(value)
  )
}

export function normalizeAgentModel(value: unknown): AgentModel {
  return isAgentModel(value) ? value : DEFAULT_AGENT_MODEL
}
