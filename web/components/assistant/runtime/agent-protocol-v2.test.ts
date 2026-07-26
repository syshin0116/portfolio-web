import { describe, expect, test } from "bun:test"
import { readFileSync } from "node:fs"

import type {
  Command,
  CommandResponse,
  ErrorResponse,
  Event,
  EventStreamRequest,
} from "./protocol-types"
import {
  AEGRA_EVENT_STREAM_FEATURE_FLAG,
  AEGRA_THREAD_EVENT_STREAM_SUFFIX,
  AGENT_PROTOCOL_UPSTREAM_THREAD_STREAM_SUFFIX,
  AgentProtocolDecodeError,
  AgentProtocolV2Transport,
  AgentTransportHttpError,
  createAgentRuntimeState,
  decodeAegraEvent,
  decodeCommandResponse,
  eventStreamRequestFor,
  reduceAgentCommandResult,
  reduceAgentProtocolEvent,
  selectVisibleText,
  type AgentEventStreamRequest,
  type AgentRuntimeState,
} from "./agent-protocol-v2"

type FixtureRecord = {
  kind: string
  connection?: string
  sse?: { id?: string; event?: string }
  payload: Record<string, unknown>
}

type Fixture = {
  name: string
  records: FixtureRecord[]
  expectations: {
    replay?: {
      disconnect_after_seq: number
      reconnect_since: number
      visible_text: string
    }
  }
}

const FIXTURE_NAMES = [
  "aegra-dialect-translation.json",
  "content-tool-run.json",
  "hitl-command-response.json",
  "nested-namespace.json",
  "replay-disconnect.json",
  "structured-error.json",
] as const

function fixture(name: (typeof FIXTURE_NAMES)[number]): Fixture {
  return JSON.parse(
    readFileSync(
      new URL(`../../../../protocol/fixtures/${name}`, import.meta.url),
      "utf8"
    )
  )
}

function recordsOfKind(source: Fixture, kind: string): FixtureRecord[] {
  return source.records.filter((record) => record.kind === kind)
}

function decodedEvent(record: FixtureRecord): Event {
  return decodeAegraEvent(record.payload, record.sse)
}

function reduceFixtureEvents(source: Fixture): AgentRuntimeState {
  return source.records
    .filter((record) =>
      ["event", "normalized_event", "aegra_raw_event"].includes(record.kind)
    )
    .reduce(
      (state, record) =>
        reduceAgentProtocolEvent(state, decodedEvent(record)),
      createAgentRuntimeState()
    )
}

describe("locked Agent Protocol v2 fixtures", () => {
  test("loads and exercises all six committed fixtures", () => {
    const names = FIXTURE_NAMES.map((name) => fixture(name).name)
    expect(names).toHaveLength(6)
    expect(new Set(names).size).toBe(6)

    for (const name of FIXTURE_NAMES) {
      const source = fixture(name)
      const commands = new Map<number, Command>()
      let state = createAgentRuntimeState()

      for (const record of source.records) {
        if (record.kind === "stream_request") {
          const request = { ...record.payload }
          delete request.since
          const since =
            typeof record.payload.since === "number"
              ? { seq: record.payload.since }
              : null
          expect(
            eventStreamRequestFor(
              request as unknown as AgentEventStreamRequest,
              since
            ) as unknown
          ).toEqual(record.payload)
        } else if (record.kind === "command") {
          const command = record.payload as Command
          commands.set(command.id, command)
        } else if (
          record.kind === "command_response" &&
          typeof record.payload.id === "number"
        ) {
          const response = decodeCommandResponse(record.payload)
          const command = commands.get(response.id as number)
          if (command) {
            state = reduceAgentCommandResult(state, command, response)
          }
        } else if (
          ["event", "normalized_event", "aegra_raw_event"].includes(record.kind)
        ) {
          state = reduceAgentProtocolEvent(state, decodedEvent(record))
        }
      }

      expect(state.diagnostics.filter((item) => item.kind === "malformed")).toEqual(
        []
      )
    }
  })

  test("maps content blocks, tools, and root lifecycle", () => {
    const state = reduceFixtureEvents(fixture("content-tool-run.json"))

    expect(state.run.status).toBe("completed")
    expect(state.cursor).toEqual({ seq: 15, eventId: "evt-tool-015" })
    expect(state.messages).toHaveLength(2)
    expect(selectVisibleText(state)).toBe("도커 관련 글을 찾았습니다.")
    expect(state.messages[0].content[0].content).toMatchObject({
      type: "tool_call",
      id: "call-search-001",
      name: "search_blog",
      args: { query: "도커" },
    })
    expect(state.tools).toEqual([
      expect.objectContaining({
        toolCallId: "call-search-001",
        name: "search_blog",
        status: "completed",
        outputText: "1 result",
        output: {
          path: "content/Tools/Docker/example.md",
          title: "Docker",
        },
      }),
    ])
  })

  test("tracks nested namespaces and their streamed messages", () => {
    const state = reduceFixtureEvents(fixture("nested-namespace.json"))
    const child = state.agents.find(
      (agent) => agent.namespace.join("/") === "retrieval-researcher"
    )

    expect(child).toMatchObject({
      parentKey: "root",
      depth: 1,
      graphName: "retrieval-researcher",
      status: "completed",
      cause: { type: "toolCall", tool_call_id: "call-subagent-001" },
    })
    expect(state.messages[0]).toMatchObject({
      namespace: ["retrieval-researcher"],
      role: "assistant",
      status: "complete",
    })
    expect(selectVisibleText(state)).toBe("근거를 찾았습니다.")
  })

  test("reconnects from the reducer cursor without duplicate visible text", () => {
    const source = fixture("replay-disconnect.json")
    const initial = source.records.filter(
      (record) => record.kind === "event" && record.connection === "initial"
    )
    const resumed = source.records.filter(
      (record) => record.kind === "event" && record.connection === "resumed"
    )
    let state = initial.reduce(
      (current, record) =>
        reduceAgentProtocolEvent(current, decodedEvent(record)),
      createAgentRuntimeState()
    )

    expect(state.cursor?.seq).toBe(
      source.expectations.replay?.disconnect_after_seq
    )
    const resumedRequest = recordsOfKind(source, "stream_request").find(
      (record) => record.connection === "resumed"
    )
    if (!resumedRequest) throw new Error("fixture is missing resumed request")
    expect(
      eventStreamRequestFor(
        {
          channels: ["messages", "lifecycle"],
          namespaces: [[]],
        },
        state.cursor
      )
    ).toEqual(resumedRequest.payload as unknown as EventStreamRequest)

    state = resumed.reduce(
      (current, record) =>
        reduceAgentProtocolEvent(current, decodedEvent(record)),
      state
    )
    expect(selectVisibleText(state)).toBe(
      source.expectations.replay?.visible_text ?? ""
    )

    const replayed = resumed.reduce(
      (current, record) =>
        reduceAgentProtocolEvent(current, decodedEvent(record)),
      state
    )
    expect(selectVisibleText(replayed)).toBe("재연결")
    expect(replayed.cursor).toEqual(state.cursor)
    expect(
      replayed.diagnostics.filter(
        (diagnostic) => diagnostic.kind === "stale-or-duplicate"
      )
    ).toHaveLength(resumed.length)
  })

  test("translates Aegra HITL value exactly once at the transport boundary", () => {
    const source = fixture("aegra-dialect-translation.json")
    const raw = recordsOfKind(source, "aegra_raw_event")[0]
    const normalized = recordsOfKind(source, "normalized_event")[0]
    const decoded = decodedEvent(raw)

    expect(decoded as unknown).toEqual(normalized.payload)
    expect(
      (
        (raw.payload.params as Record<string, unknown>).data as Record<
          string,
          unknown
        >
      ).value
    ).toBeDefined()
    expect(
      (
        (raw.payload.params as Record<string, unknown>).data as Record<
          string,
          unknown
        >
      ).payload
    ).toBeUndefined()

    const ambiguous = structuredClone(raw.payload)
    const data = (ambiguous.params as { data: Record<string, unknown> }).data
    data.payload = { duplicate: true }
    expect(() => decodeAegraEvent(ambiguous, raw.sse)).toThrow(
      AgentProtocolDecodeError
    )
  })

  test("maps HITL and structured command errors", () => {
    const hitl = fixture("hitl-command-response.json")
    const requested = hitl.records.find(
      (record) =>
        record.kind === "event" &&
        record.payload.method === "input.requested"
    )
    if (!requested) throw new Error("fixture is missing input.requested")
    let state = reduceAgentProtocolEvent(
      createAgentRuntimeState(),
      decodedEvent(requested)
    )
    expect(state.interrupts[0]).toMatchObject({
      interruptId: "interrupt-approve-001",
      status: "pending",
      payload: {
        action: "approve_tool",
        tool_name: "search_blog",
      },
    })

    const command = hitl.records.find(
      (record) =>
        record.kind === "command" &&
        record.payload.method === "input.respond"
    )?.payload as Command
    const response = decodeCommandResponse(
      hitl.records.find(
        (record) =>
          record.kind === "command_response" && record.payload.id === 21
      )?.payload
    )
    state = reduceAgentCommandResult(state, command, response)
    expect(state.interrupts[0].status).toBe("responded")

    const failed = fixture("structured-error.json")
    const failedCommand = recordsOfKind(failed, "command")[0].payload as Command
    const failedResponse = decodeCommandResponse(
      recordsOfKind(failed, "command_response")[0].payload
    )
    state = reduceAgentCommandResult(
      createAgentRuntimeState(),
      failedCommand,
      failedResponse
    )
    expect(state.error).toEqual({
      source: "command",
      commandId: 30,
      code: "no_such_run",
      message: "Assistant 'missing-agent' was not found.",
    })
  })

  test("maps checkpoints, tasks, values, updates, custom data, and all delta kinds", () => {
    const base = 200
    const events: Event[] = [
      {
        type: "event",
        event_id: "synthetic-message",
        seq: base,
        method: "messages",
        params: {
          namespace: [],
          timestamp: 1,
          node: "model",
          data: { event: "message-start", role: "ai", id: "synthetic" },
        },
      },
      {
        type: "event",
        event_id: "synthetic-reasoning-start",
        seq: base + 1,
        method: "messages",
        params: {
          namespace: [],
          timestamp: 2,
          node: "model",
          data: {
            event: "content-block-start",
            index: 0,
            content: { type: "reasoning", reasoning: "" },
          },
        },
      },
      {
        type: "event",
        event_id: "synthetic-reasoning-delta",
        seq: base + 2,
        method: "messages",
        params: {
          namespace: [],
          timestamp: 3,
          node: "model",
          data: {
            event: "content-block-delta",
            index: 0,
            delta: { type: "reasoning-delta", reasoning: "bounded summary" },
          },
        },
      },
      {
        type: "event",
        event_id: "synthetic-data-start",
        seq: base + 3,
        method: "messages",
        params: {
          namespace: [],
          timestamp: 4,
          node: "model",
          data: {
            event: "content-block-start",
            index: 1,
            content: { type: "image", base64: "" },
          },
        },
      },
      {
        type: "event",
        event_id: "synthetic-data-delta",
        seq: base + 4,
        method: "messages",
        params: {
          namespace: [],
          timestamp: 5,
          node: "model",
          data: {
            event: "content-block-delta",
            index: 1,
            delta: { type: "data-delta", data: "YWJj" },
          },
        },
      },
      {
        type: "event",
        event_id: "synthetic-checkpoint",
        seq: base + 5,
        method: "checkpoints",
        params: {
          namespace: ["worker"],
          timestamp: 6,
          data: { id: "cp-1", step: 3, source: "loop" },
        },
      },
      {
        type: "event",
        event_id: "synthetic-task",
        seq: base + 6,
        method: "tasks",
        params: {
          namespace: ["worker"],
          timestamp: 7,
          data: { id: "task-1", status: "completed" },
        },
      },
      {
        type: "event",
        event_id: "synthetic-values",
        seq: base + 7,
        method: "values",
        params: {
          namespace: ["worker"],
          timestamp: 8,
          data: { answer: 42 },
        },
      },
      {
        type: "event",
        event_id: "synthetic-updates",
        seq: base + 8,
        method: "updates",
        params: {
          namespace: ["worker"],
          timestamp: 9,
          data: { node: "research", values: { hits: 3 } },
        },
      },
      {
        type: "event",
        event_id: "synthetic-custom",
        seq: base + 9,
        method: "custom",
        params: {
          namespace: ["worker"],
          timestamp: 10,
          data: { name: "retrieval", payload: { method: "rrf" } },
        },
      },
    ]
    const state = events.reduce(
      reduceAgentProtocolEvent,
      createAgentRuntimeState()
    )

    expect(state.messages[0].content[0].content).toMatchObject({
      reasoning: "bounded summary",
    })
    expect(state.messages[0].content[1].content).toMatchObject({
      base64: "YWJj",
    })
    expect(state.checkpoints[0]).toMatchObject({
      namespace: ["worker"],
      id: "cp-1",
      step: 3,
    })
    expect(state.tasks[0]).toMatchObject({
      namespace: ["worker"],
      data: { id: "task-1", status: "completed" },
    })
    expect(state.values[0].data).toEqual({ answer: 42 })
    expect(state.updates[0].data).toEqual({
      node: "research",
      values: { hits: 3 },
    })
    expect(state.custom[0].data).toEqual({
      name: "retrieval",
      payload: { method: "rrf" },
    })
  })

  test("diagnoses unknown events without corrupting known runtime state", () => {
    const known = reduceFixtureEvents(fixture("content-tool-run.json"))
    const unknown = decodeAegraEvent({
      type: "event",
      event_id: "future-016",
      seq: 16,
      method: "future.channel",
      params: {
        namespace: [],
        timestamp: 1785031200016,
        data: { future: true },
      },
    })
    const next = reduceAgentProtocolEvent(known, unknown)

    expect(next.messages).toEqual(known.messages)
    expect(next.tools).toEqual(known.tools)
    expect(next.run).toEqual(known.run)
    expect(next.cursor).toEqual({ seq: 16, eventId: "future-016" })
    expect(next.diagnostics.at(-1)).toMatchObject({
      kind: "unknown-event",
      method: "future.channel",
      seq: 16,
    })
  })
})

function sseResponse(
  payload: Record<string, unknown>,
  options: { id?: string; event?: string } = {}
): Response {
  const id = options.id ?? String(payload.seq)
  const event = options.event ?? String(payload.method)
  return new Response(
    `: heartbeat\r\nid: ${id}\r\nevent: ${event}\r\ndata: ${JSON.stringify(
      payload
    )}\r\n\r\n`,
    {
      headers: { "content-type": "text/event-stream; charset=utf-8" },
    }
  )
}

describe("AgentProtocolV2Transport", () => {
  test("uses Aegra's explicit POST event path and sequence replay cursor", async () => {
    const event = recordsOfKind(
      fixture("content-tool-run.json"),
      "event"
    )[0].payload
    let requestUrl = ""
    let requestInit: RequestInit | undefined
    const transport = new AgentProtocolV2Transport({
      baseUrl: "https://agent.example/",
      fetch: (async (input, init) => {
        requestUrl = String(input)
        requestInit = init
        return sseResponse(event)
      }) as typeof fetch,
      onRequest: async ({ purpose }) => ({
        token: `token-for-${purpose}`,
        expiresAt: Math.floor(Date.now() / 1000) + 900,
      }),
    })

    const stream = transport.streamEvents({
      threadId: "thread / 한글",
      channels: ["messages", "lifecycle"],
      namespaces: [[]],
      cursor: { seq: 104, eventId: "evt-104" },
    })
    const received = []
    for await (const item of stream) received.push(item)

    expect(AEGRA_EVENT_STREAM_FEATURE_FLAG).toBe("FF_V2_EVENT_STREAMING")
    expect(AGENT_PROTOCOL_UPSTREAM_THREAD_STREAM_SUFFIX).toBe("/stream")
    expect(AEGRA_THREAD_EVENT_STREAM_SUFFIX).toBe("/stream/events")
    expect(requestUrl).toBe(
      "https://agent.example/threads/thread%20%2F%20%ED%95%9C%EA%B8%80/stream/events"
    )
    expect(requestInit?.method).toBe("POST")
    expect(JSON.parse(String(requestInit?.body))).toEqual({
      channels: ["messages", "lifecycle"],
      namespaces: [[]],
      since: 104,
    })
    const headers = new Headers(requestInit?.headers)
    expect(headers.get("accept")).toBe("text/event-stream")
    expect(headers.get("authorization")).toBe("Bearer token-for-event-stream")
    expect(received as unknown).toEqual([event])
  })

  test("posts commands and preserves a structured protocol error envelope", async () => {
    const source = fixture("structured-error.json")
    const command = recordsOfKind(source, "command")[0].payload as Command
    const expected = recordsOfKind(source, "command_response")[0]
      .payload as ErrorResponse
    let method = ""
    let url = ""
    const transport = new AgentProtocolV2Transport({
      baseUrl: "https://agent.example",
      fetch: (async (input, init) => {
        url = String(input)
        method = String(init?.method)
        expect(JSON.parse(String(init?.body))).toEqual(command)
        return Response.json(expected)
      }) as typeof fetch,
    })

    const response = await transport.sendCommand("thread-1", command)

    expect(url).toBe("https://agent.example/threads/thread-1/commands")
    expect(method).toBe("POST")
    expect(response).toEqual(expected)
  })

  test.each([
    [401, "unauthorized"],
    [403, "forbidden"],
    [409, "busy-thread"],
    [429, "rate-limited"],
    [500, "server-error"],
    [503, "server-error"],
  ] as const)("maps HTTP %i to typed %s errors", async (status, kind) => {
    const transport = new AgentProtocolV2Transport({
      baseUrl: "https://agent.example",
      fetch: (async () =>
        new Response(JSON.stringify({ detail: `status-${status}` }), {
          status,
          headers: {
            "content-type": "application/json",
            "retry-after": status === 429 ? "12" : "",
          },
        })) as unknown as typeof fetch,
    })
    const command = recordsOfKind(
      fixture("structured-error.json"),
      "command"
    )[0].payload as Command

    try {
      await transport.sendCommand("thread-1", command)
      throw new Error("expected an HTTP error")
    } catch (error) {
      expect(error).toBeInstanceOf(AgentTransportHttpError)
      expect(error).toMatchObject({
        kind,
        status,
        retryAfterMs: status === 429 ? 12_000 : undefined,
      })
    }
  })

  test("rejects an SSE id that cannot represent either event id or sequence", async () => {
    const event = recordsOfKind(
      fixture("content-tool-run.json"),
      "event"
    )[0].payload
    const transport = new AgentProtocolV2Transport({
      baseUrl: "https://agent.example",
      fetch: (async () =>
        sseResponse(event, {
          id: "corrupt-cursor",
        })) as unknown as typeof fetch,
    })

    const consume = async () => {
      const iterator = transport
        .streamEvents({
        threadId: "thread-1",
        channels: ["lifecycle"],
        })
        [Symbol.asyncIterator]()
      await iterator.next()
    }

    await expect(consume()).rejects.toThrow(AgentProtocolDecodeError)
  })

  test("cancels an in-flight stream through AbortSignal", async () => {
    let requestSignal: AbortSignal | null = null
    const body = new ReadableStream<Uint8Array>({
      pull() {
        return new Promise(() => undefined)
      },
    })
    const transport = new AgentProtocolV2Transport({
      baseUrl: "https://agent.example",
      fetch: (async (_input, init) => {
        requestSignal = init?.signal as AbortSignal
        return new Response(body, {
          headers: { "content-type": "text/event-stream" },
        })
      }) as typeof fetch,
    })
    const stream = transport.streamEvents({
      threadId: "thread-1",
      channels: ["messages"],
    })
    const iterator = stream[Symbol.asyncIterator]()
    const pending = iterator.next()

    await Promise.resolve()
    stream.cancel()

    await expect(pending).rejects.toMatchObject({ name: "AbortError" })
    expect(requestSignal).not.toBeNull()
    expect((requestSignal as unknown as AbortSignal).aborted).toBe(true)
  })

  test("rejects Aegra-unsupported atomic HITL update/goto before fetch", async () => {
    let fetched = false
    const transport = new AgentProtocolV2Transport({
      baseUrl: "https://agent.example",
      fetch: (async () => {
        fetched = true
        return Response.json({ type: "success", id: 1, result: {} })
      }) as unknown as typeof fetch,
    })
    const unsupported = recordsOfKind(
      fixture("hitl-command-response.json"),
      "command"
    ).find(
      (record) => record.payload.method === "input.respond"
    )?.payload as Command

    await expect(
      transport.sendCommand("thread-1", unsupported)
    ).rejects.toThrow("does not forward")
    expect(fetched).toBe(false)
  })

  test("validates command response correlation", () => {
    const response: CommandResponse = {
      type: "success",
      id: 3,
      result: { run_id: "run-3" },
    }
    expect(decodeCommandResponse(response, 3)).toEqual(response)
    expect(() => decodeCommandResponse(response, 4)).toThrow(
      AgentProtocolDecodeError
    )
  })
})
