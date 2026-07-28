import { describe, expect, test } from "bun:test"

import {
  GENERIC_INTERRUPT_PROJECTION,
  INTERRUPT_UI_SCHEMA,
  projectInterruptForUi,
  readRuntimeInterruptProjection,
} from "./interrupt-projection"

describe("projectInterruptForUi", () => {
  test("projects only the exact versioned approval allowlist", () => {
    expect(
      projectInterruptForUi({
        schema: INTERRUPT_UI_SCHEMA,
        kind: "approval",
        title: "검색 도구 실행",
        prompt: "블로그 검색 도구를 실행할까요?",
        input_hint: "수정할 조건을 입력해 재개",
      })
    ).toEqual({
      recognized: true,
      kind: "approval",
      title: "검색 도구 실행",
      prompt: "블로그 검색 도구를 실행할까요?",
      inputHint: "수정할 조건을 입력해 재개",
    })
  })

  test("projects the bounded input variant without adding approval semantics", () => {
    expect(
      projectInterruptForUi({
        schema: INTERRUPT_UI_SCHEMA,
        kind: "input",
        prompt: "검색 범위를 입력해 주세요.",
      })
    ).toEqual({
      recognized: true,
      kind: "input",
      title: "추가 입력이 필요합니다.",
      prompt: "검색 범위를 입력해 주세요.",
      inputHint: "응답을 입력해 재개",
    })
  })

  test("uses generic safe copy for unknown versions and unversioned Aegra payloads", () => {
    for (const value of [
      "raw prompt must stay opaque",
      { action: "approve_tool", tool_name: "search_blog" },
      {
        schema: "syshin.rag.interrupt.v2",
        kind: "approval",
        prompt: "future prompt",
      },
    ]) {
      expect(projectInterruptForUi(value)).toEqual(
        GENERIC_INTERRUPT_PROJECTION
      )
    }
  })

  test("rejects nested secret and reasoning fields instead of partially projecting them", () => {
    const secret = "NESTED_DATABASE_PASSWORD"
    const projected = projectInterruptForUi({
      schema: INTERRUPT_UI_SCHEMA,
      kind: "approval",
      title: "apparently safe",
      prompt: "apparently safe",
      tool_payload: {
        chain_of_thought: ["private plan", { secret }],
      },
    })

    expect(projected).toEqual(GENERIC_INTERRUPT_PROJECTION)
    expect(JSON.stringify(projected)).not.toContain(secret)
    expect(JSON.stringify(projected)).not.toContain("private plan")
  })

  test("rejects huge strings, lists, object counts, depth, cycles, and accessors", () => {
    const cyclic: Record<string, unknown> = {}
    cyclic.self = cyclic
    const accessor = Object.defineProperty(
      {
        schema: INTERRUPT_UI_SCHEMA,
        kind: "approval",
        prompt: "safe",
      },
      "secret",
      {
        enumerable: true,
        get: () => "MUST_NOT_BE_READ",
      }
    )
    const adversarial = [
      {
        schema: INTERRUPT_UI_SCHEMA,
        kind: "approval",
        prompt: "x".repeat(1_000_000),
      },
      Array.from({ length: 9 }, (_, index) => index),
      Object.fromEntries(
        Array.from({ length: 17 }, (_, index) => [`key-${index}`, index])
      ),
      { a: { b: { c: { d: { e: "too deep" } } } } },
      cyclic,
      accessor,
    ]

    for (const value of adversarial) {
      expect(projectInterruptForUi(value)).toEqual(
        GENERIC_INTERRUPT_PROJECTION
      )
    }
  })

  test("enforces UTF-8 byte and field boundaries", () => {
    const accepted = projectInterruptForUi({
      schema: INTERRUPT_UI_SCHEMA,
      kind: "input",
      prompt: "가".repeat(160),
    })
    const rejected = projectInterruptForUi({
      schema: INTERRUPT_UI_SCHEMA,
      kind: "input",
      prompt: "가".repeat(161),
    })

    expect(accepted.recognized).toBe(true)
    expect(accepted.prompt).toBe("가".repeat(160))
    expect(rejected).toEqual(GENERIC_INTERRUPT_PROJECTION)
  })

  test("reads only the bounded local runtime projection", () => {
    const projected = projectInterruptForUi({
      schema: INTERRUPT_UI_SCHEMA,
      kind: "approval",
      prompt: "검색을 계속할까요?",
    })
    expect(readRuntimeInterruptProjection(projected)).toEqual(projected)
    expect(
      readRuntimeInterruptProjection({
        ...projected,
        secret: "MUST_NOT_ENTER_RUNTIME",
      })
    ).toEqual(GENERIC_INTERRUPT_PROJECTION)
    expect(
      JSON.stringify(
        readRuntimeInterruptProjection({
          prompt: "raw backend prompt",
          secret: "MUST_NOT_ENTER_RUNTIME",
        })
      )
    ).not.toContain("MUST_NOT_ENTER_RUNTIME")
  })
})
