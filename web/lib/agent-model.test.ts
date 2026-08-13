import { describe, expect, test } from "bun:test"

import {
  AGENT_MODELS,
  DEFAULT_AGENT_MODEL,
  isAgentModel,
  normalizeAgentModel,
} from "./agent-model"

describe("agent model selection", () => {
  test("only accepts the server allowlist and defaults to Luna", () => {
    expect(AGENT_MODELS).toEqual([
      "gpt-5.6-luna",
      "gpt-5.6-terra",
      "gpt-5.6-sol",
    ])
    expect(isAgentModel("gpt-5.6-terra")).toBe(true)
    expect(isAgentModel("gpt-5.6-arbitrary")).toBe(false)
    expect(normalizeAgentModel("gpt-5.6-arbitrary")).toBe(
      DEFAULT_AGENT_MODEL
    )
  })
})
