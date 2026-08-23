import { describe, expect, test } from "bun:test"

import {
  toolArgumentSummary,
  toolResultText,
} from "./tool-arguments"

const summary = (args: Record<string, unknown>) =>
  toolArgumentSummary(JSON.stringify(args))

describe("tool argument summary", () => {
  test("shows the query for the search tools", () => {
    expect(summary({ query: "RAG 파이프라인", top_k: 10 })).toBe("RAG 파이프라인")
  })

  test("shows the path read_post was actually given", () => {
    expect(summary({ path: "AI/2025-06-04-Agent.md" })).toBe(
      "AI/2025-06-04-Agent.md"
    )
  })

  test("shows the file read_file was actually given", () => {
    expect(summary({ file_path: "/skills/blog/SKILL.md" })).toBe(
      "/skills/blog/SKILL.md"
    )
  })

  test("shows the slug graph_traverse was actually given", () => {
    expect(summary({ slug: "AI/2025-06-04-Agent", depth: 2 })).toBe(
      "AI/2025-06-04-Agent"
    )
  })

  test("joins metadata_filter constraints, which have no single primary field", () => {
    expect(summary({ tags: ["rag", "llm"], category: "AI" })).toBe(
      "tags: rag, llm · category: AI"
    )
  })

  test("keeps a numeric-only argument visible", () => {
    expect(summary({ limit: 20 })).toBe("limit: 20")
  })

  test("reports nothing for an argument-free call", () => {
    expect(summary({})).toBeUndefined()
    expect(toolArgumentSummary("")).toBeUndefined()
  })

  test("reports nothing rather than throwing on malformed arguments", () => {
    expect(toolArgumentSummary("{not json")).toBeUndefined()
    expect(toolArgumentSummary("[1,2]")).toBeUndefined()
  })

  test("ignores an empty query so the fallback is not a blank line", () => {
    expect(summary({ query: "   ", path: "AI/post.md" })).toBe("AI/post.md")
  })

  test("bounds a very long argument", () => {
    const value = summary({ query: "가".repeat(5_000) })
    expect(value?.length).toBe(1_000)
  })
})

describe("toolResultText", () => {
  test("passes plain text through", () => {
    expect(toolResultText("검색 결과 3건")).toBe("검색 결과 3건")
  })

  test("renders structured results as readable JSON", () => {
    expect(toolResultText({ hits: 2 })).toBe('{\n  "hits": 2\n}')
  })

  test("has nothing to show for an absent or blank result", () => {
    expect(toolResultText(undefined)).toBeUndefined()
    expect(toolResultText("   ")).toBeUndefined()
  })

  test("truncates a dump that would push the composer off screen", () => {
    const text = toolResultText("가".repeat(5_000))
    expect(text).toHaveLength(4_000 + "\n…(생략됨)".length)
    expect(text?.endsWith("…(생략됨)")).toBe(true)
  })
})
