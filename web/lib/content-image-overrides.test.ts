import { describe, expect, test } from "bun:test"

import { applyContentImageOverrides } from "./content-image-overrides"

describe("applyContentImageOverrides", () => {
  test("replaces the removed LangGraph ReAct diagram with a local asset", () => {
    const html =
      '<img src="https://langchain-ai.github.io/langgraph/agents/assets/react_agent_graphs/1111.svg" alt="graph image">'

    expect(applyContentImageOverrides(html)).toBe(
      '<img src="/images/blog/react-agent-graph.svg" alt="graph image">'
    )
  })

  test("leaves unrelated external images unchanged", () => {
    const html =
      '<img src="https://example.com/diagram.svg" alt="other diagram">'

    expect(applyContentImageOverrides(html)).toBe(html)
  })
})
