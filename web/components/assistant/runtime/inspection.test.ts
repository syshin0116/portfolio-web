import { describe, expect, test } from "bun:test"
import type {
  CustomEvent,
  Event,
  LifecycleEvent,
  MessagesEvent,
  ToolsEvent,
} from "@langchain/protocol"

import contentToolRun from "../../../../protocol/fixtures/content-tool-run.json"
import inspectionEvents from "../../../../protocol/fixtures/inspection-events-v1.json"
import nestedNamespace from "../../../../protocol/fixtures/nested-namespace.json"
import {
  INSPECTION_EVENT_NAME,
  InspectionProjector,
  inspectionSourcesFromUnknown,
  projectInspectionCustomEvent,
  safeSourceUrl,
} from "./inspection"

const protocolEvents = (fixture: {
  records: Array<{ kind: string; payload: unknown }>
}): Event[] =>
  fixture.records.flatMap((record) =>
    record.kind === "event" ? [record.payload as Event] : []
  )

describe("InspectionProjector", () => {
  test("projects the canonical retrieval-only live-run v1 fixture without inference", () => {
    const projector = new InspectionProjector()
    const activities = protocolEvents(inspectionEvents).map((event) =>
      projector.consumeCustom(event as CustomEvent)
    )

    expect(activities).toHaveLength(1)
    expect(activities[0]).toEqual({
      id: "retrieval:fixture-tool-call",
      kind: "retrieval",
      namespace: [],
      status: "completed",
      label: "검색 검사 정보가 도착했습니다.",
      delivery: "live-run-only",
      toolCallId: "fixture-tool-call",
      query: "aegra",
      queryTruncated: false,
      methodId: "fixture-retriever",
      methodIdentity: {
        methodId: "fixture-retriever",
        implementationId: "agent.tests.fixture:retrieve@1",
        fingerprint:
          "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      },
      hitCount: 1,
      corpusDocumentCount: 1,
      corpusRevision:
        "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      sourcesTruncated: false,
      sources: [
        {
          key: "AI/fixture.md",
          docId: "AI/fixture.md",
          title: "Fixture",
          rank: 1,
          score: 1,
          provenance: {
            kind: "published-corpus",
            corpusRevision:
              "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            retrieverFingerprint:
              "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
          },
        },
      ],
      stages: [
        {
          stageId: "fixture-retriever",
          implementationId: "agent.tests.fixture:retrieve@1",
          fingerprint:
            "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
          elapsedMs: 1,
          application: {
            status: "applied",
            inputCount: 1,
            outputCount: 1,
          },
        },
      ],
    })
  })

  test("matches the backend v1 count, score, and truncation contract exactly", () => {
    const event = structuredClone(
      protocolEvents(inspectionEvents)[0]
    ) as CustomEvent
    const payload = event.params.data.payload as Record<string, unknown>
    const sources = payload.sources as Array<Record<string, unknown>>
    const secondSource = structuredClone(sources[0])
    secondSource.doc_id = "AI/fixture-two.md"
    secondSource.title = "Fixture Two"
    secondSource.rank = 2
    secondSource.score = -0.25
    payload.sources = [sources[0], secondSource]
    payload.hit_count = 2
    payload.corpus_document_count = 335
    const stage = (payload.stages as Array<Record<string, unknown>>)[0]
    const application = stage.application as Record<string, unknown>
    application.input_count = 1
    application.output_count = 2

    expect(projectInspectionCustomEvent(event)).toMatchObject({
      hitCount: 2,
      corpusDocumentCount: 335,
      sources: [{ score: 1 }, { score: -0.25 }],
      stages: [{ application: { inputCount: 1, outputCount: 2 } }],
    })

    application.input_count = 335
    expect(projectInspectionCustomEvent(event)).toBeUndefined()
  })

  test("fails closed on unknown fields and inconsistent source truncation", () => {
    const event = structuredClone(
      protocolEvents(inspectionEvents)[0]
    ) as CustomEvent
    const payload = event.params.data.payload as Record<string, unknown>
    payload.sources_truncated = true
    expect(projectInspectionCustomEvent(event)).toBeUndefined()

    payload.sources_truncated = false
    payload.unreviewed_backend_detail = "must-not-cross-the-boundary"
    expect(projectInspectionCustomEvent(event)).toBeUndefined()
  })

  test("uses tools only for generic lifecycle status and leaves inspection fields unknown", () => {
    const projector = new InspectionProjector()
    const activities = protocolEvents(contentToolRun)
      .filter((event) => event.method === "tools")
      .map((event) => projector.consumeTool(event as ToolsEvent))

    expect(activities[0]).toMatchObject({
      kind: "tool",
      status: "running",
      toolName: "search_blog",
    })
    expect(activities.at(-1)).toMatchObject({
      kind: "tool",
      status: "completed",
    })
    const final = activities.at(-1)!
    expect("query" in final).toBe(false)
    expect("methodId" in final).toBe(false)
    expect("hitCount" in final).toBe(false)
    expect("corpusRevision" in final).toBe(false)
  })

  test("projects nested lifecycle identity and measured latency from the real fixture", () => {
    const projector = new InspectionProjector()
    const nested = protocolEvents(nestedNamespace)
      .filter(
        (event) =>
          event.method === "lifecycle" &&
          event.params.namespace.length > 0
      )
      .map((event) => projector.consumeLifecycle(event as LifecycleEvent))

    expect(nested[0]).toMatchObject({
      kind: "nested",
      name: "retrieval-researcher",
      status: "started",
    })
    expect(nested.at(-1)).toMatchObject({
      kind: "nested",
      name: "retrieval-researcher",
      status: "completed",
      elapsedMs: 6,
    })
    expect("purpose" in nested.at(-1)!).toBe(false)
    expect("evidenceCount" in nested.at(-1)!).toBe(false)
    expect("budget" in nested.at(-1)!).toBe(false)
  })

  test("projects protocol citation annotations and rejects unsafe source URLs", () => {
    const projector = new InspectionProjector()
    projector.consumeMessage(messageEvent({
      event: "message-start",
      role: "ai",
      id: "answer-1",
    }))
    const activity = projector.consumeMessage(messageEvent({
      event: "content-block-start",
      index: 0,
      content: {
        type: "text",
        text: "근거",
        annotations: [
          {
            type: "citation",
            id: "citation-1",
            title: "Docker",
            url: "https://example.com/docker",
            cited_text: "도커 근거",
          },
        ],
      },
    }))

    expect(activity).toMatchObject({
      kind: "sources",
      messageId: "answer-1",
      sources: [
        {
          key: "citation-1",
          title: "Docker",
          url: "https://example.com/docker",
          citedText: "도커 근거",
        },
      ],
    })
    expect(safeSourceUrl("javascript:alert(1)")).toBeUndefined()
    expect(safeSourceUrl("https://example.com/docker")).toBe(
      "https://example.com/docker"
    )
  })

  test("rejects synthetic capability variants and ignores unknown versions", () => {
    const base = protocolEvents(inspectionEvents)[0] as CustomEvent

    expect(
      projectInspectionCustomEvent({
        ...base,
        params: {
          ...base.params,
          data: {
            name: "syshin.rag.inspection.v2",
            payload: base.params.data.payload,
          },
        },
      })
    ).toBeUndefined()
    expect(
      projectInspectionCustomEvent({
        ...base,
        params: {
          ...base.params,
          data: {
            name: INSPECTION_EVENT_NAME,
            payload: {
              schema_version: 1,
              kind: "quickjs",
              delivery: "live-run-only",
              tool_call_id: "synthetic-capability",
              chain_of_thought: "NEVER_RENDER_THIS",
            },
          },
        },
      })
    ).toBeUndefined()
  })

  test("does not reconstruct inspection from formatted tool output", () => {
    const projector = new InspectionProjector()
    const events = protocolEvents(contentToolRun).filter(
      (event) => event.method === "tools"
    )
    const forged = events.map((event) => ({
      ...event,
      params: {
        ...event.params,
        data: {
          ...event.params.data,
          output: JSON.stringify({
            method_id: "forged",
            corpus_revision: "forged",
            hit_count: 999,
          }),
        },
      },
    }))
    const final = forged
      .map((event) => projector.consumeTool(event as ToolsEvent))
      .at(-1)!

    expect(JSON.stringify(final)).not.toContain("forged")
    expect("methodId" in final).toBe(false)
    expect("hitCount" in final).toBe(false)
    expect("corpusRevision" in final).toBe(false)
  })

  test("accepts only bounded projected source metadata for answer rendering", () => {
    expect(
      inspectionSourcesFromUnknown([
        {
          key: "source-1",
          title: "Docker",
          url: "https://example.com/docker",
          citedText: "검증된 인용",
          chain_of_thought: "NEVER_RENDER_THIS",
        },
      ])
    ).toEqual([
      {
        key: "source-1",
        title: "Docker",
        url: "https://example.com/docker",
        citedText: "검증된 인용",
      },
    ])
    expect(
      JSON.stringify(
        inspectionSourcesFromUnknown([
          {
            key: "source-1",
            title: "Docker",
            chain_of_thought: "NEVER_RENDER_THIS",
          },
        ])
      )
    ).not.toContain("NEVER_RENDER_THIS")
    expect(
      inspectionSourcesFromUnknown([
        { key: "source-1", title: "x".repeat(301) },
      ])
    ).toEqual([])
  })
})

function messageEvent(
  data: MessagesEvent["params"]["data"]
): MessagesEvent {
  return {
    type: "event",
    method: "messages",
    params: {
      namespace: [],
      timestamp: 1,
      node: "model",
      data,
    },
  } as MessagesEvent
}
