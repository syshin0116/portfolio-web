import { describe, expect, test } from "bun:test"
import type { Client, ThreadState, ThreadStream } from "@langchain/langgraph-sdk"
import type { Event } from "@langchain/protocol"
import type {
  LangChainMessage,
  LangGraphMessagesEvent,
} from "@assistant-ui/react-langgraph"

import aegraDialect from "../../../../protocol/fixtures/aegra-dialect-translation.json"
import contentToolRun from "../../../../protocol/fixtures/content-tool-run.json"
import inspectionEvents from "../../../../protocol/fixtures/inspection-events-v1.json"
import nestedNamespace from "../../../../protocol/fixtures/nested-namespace.json"
import { AgentLifecycleError } from "./error-state"
import {
  NativeAgentClient,
  NativeMessageProjection,
  cancelRunAndWait,
  extractPendingInterrupt,
  nativeClientTesting,
  normalizeStateMessages,
} from "./native-client"
import {
  AgentTokenBroker,
  tokenBrokerTesting,
} from "./token-broker"
import type { AgentActivity } from "./inspection"
import { GENERIC_INTERRUPT_PROJECTION } from "./interrupt-projection"

const protocolEvents = (fixture: {
  records: Array<{ kind: string; payload: unknown }>
}): Event[] =>
  fixture.records.flatMap((record) =>
    record.kind === "event" || record.kind === "aegra_raw_event"
      ? [record.payload as Event]
      : []
  )

describe("NativeMessageProjection", () => {
  test("assembles real APv2 tool partial JSON and text content blocks", () => {
    const projection = new NativeMessageProjection()
    const outputs = protocolEvents(contentToolRun)
      .filter(
        (event): event is Extract<Event, { method: "messages" }> =>
          event.method === "messages"
      )
      .flatMap((event) => {
        const output = projection.consume(event)
        return output ? [output] : []
      })

    const toolPartial = outputs.findLast((output) => {
      const message = output.data[0] as LangChainMessage
      return (
        message.type === "ai" &&
        message.tool_calls?.[0]?.partial_json === '{"query":"도커"}'
      )
    })
    expect(toolPartial).toBeDefined()
    const toolMessage = toolPartial!.data[0] as Extract<
      LangChainMessage,
      { type: "ai" }
    >
    expect(toolMessage.tool_calls?.[0]).toMatchObject({
      id: "call-search-001",
      name: "search_blog",
      args: { query: "도커" },
      partial_json: '{"query":"도커"}',
    })

    const final = outputs.at(-1)!
    expect(final.event).toBe("messages/complete")
    expect(final.data[0]).toMatchObject({
      type: "ai",
      content: [{ type: "text", text: "도커 관련 글을 찾았습니다." }],
    })
  })

  test("renders an explicit fallback for an unknown content block", () => {
    const projection = new NativeMessageProjection()
    const base = {
      type: "event",
      method: "messages",
      params: { namespace: [], timestamp: 1, node: "agent" },
    } as const
    projection.consume({
      ...base,
      params: {
        ...base.params,
        data: { event: "message-start", role: "ai", id: "message-unknown" },
      },
    } as unknown as Extract<Event, { method: "messages" }>)
    const output = projection.consume({
      ...base,
      params: {
        ...base.params,
        data: {
          event: "content-block-start",
          index: 0,
          content: { type: "future_block", payload: "redacted" },
        },
      },
    } as unknown as Extract<Event, { method: "messages" }>)!

    expect(output.data[0]).toMatchObject({
      content: [
        { type: "text", text: "[지원하지 않는 콘텐츠: future_block]" },
      ],
    })
  })

  test("keeps assembled citation annotations as assistant-ui source metadata", () => {
    const projection = new NativeMessageProjection()
    const base = {
      type: "event",
      method: "messages",
      params: { namespace: [], timestamp: 1, node: "agent" },
    } as const
    projection.consume({
      ...base,
      params: {
        ...base.params,
        data: {
          event: "message-start",
          role: "ai",
          id: "message-with-citation",
        },
      },
    } as unknown as Extract<Event, { method: "messages" }>)
    const output = projection.consume({
      ...base,
      params: {
        ...base.params,
        data: {
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
              },
            ],
          },
        },
      },
    } as unknown as Extract<Event, { method: "messages" }>)!

    expect(output.data[0]).toMatchObject({
      additional_kwargs: {
        metadata: {
          sources: [
            {
              key: "citation-1",
              title: "Docker",
              url: "https://example.com/docker",
            },
          ],
        },
      },
    })
  })

  test("never projects system prompts or model reasoning text", () => {
    const projection = new NativeMessageProjection()
    const secret = "PRIVATE_CHAIN_OF_THOUGHT_AND_SYSTEM_PROMPT"
    const base = {
      type: "event",
      method: "messages",
      params: { namespace: [], timestamp: 1, node: "agent" },
    } as const

    expect(
      projection.consume({
        ...base,
        params: {
          ...base.params,
          data: { event: "message-start", role: "system", id: "system-1" },
        },
      } as unknown as Extract<Event, { method: "messages" }>)
    ).toBeUndefined()
    expect(
      projection.consume({
        ...base,
        params: {
          ...base.params,
          data: {
            event: "content-block-start",
            index: 0,
            content: { type: "text", text: secret },
          },
        },
      } as unknown as Extract<Event, { method: "messages" }>)
    ).toBeUndefined()

    projection.consume({
      ...base,
      params: {
        ...base.params,
        data: { event: "message-start", role: "ai", id: "answer-1" },
      },
    } as unknown as Extract<Event, { method: "messages" }>)
    const reasoning = projection.consume({
      ...base,
      params: {
        ...base.params,
        data: {
          event: "content-block-start",
          index: 0,
          content: { type: "reasoning", reasoning: secret },
        },
      },
    } as unknown as Extract<Event, { method: "messages" }>)

    expect(reasoning).toMatchObject({
      data: [
        {
          content: [{ type: "reasoning", reasoning: "" }],
        },
      ],
    })
    expect(JSON.stringify(reasoning)).not.toContain(secret)
  })
})

describe("APv2 state and HITL normalization", () => {
  test("prefers Aegra top-level interrupts over the tasks fallback", () => {
    const state = {
      values: {},
      next: [],
      checkpoint: {
        thread_id: "thread-1",
        checkpoint_ns: "",
        checkpoint_id: "checkpoint-1",
        checkpoint_map: null,
      },
      metadata: {},
      created_at: null,
      parent_checkpoint: null,
      interrupts: [
        {
          id: "top-level",
          value: { action: "approve_tool" },
          ns: ["tools"],
        },
      ],
      tasks: [
        {
          id: "task-1",
          name: "tools",
          error: null,
          interrupts: [{ id: "task-fallback", value: "wrong" }],
          checkpoint: null,
          state: null,
        },
      ],
    } satisfies ThreadState<Record<string, unknown>> & { interrupts: unknown }

    expect(extractPendingInterrupt(state)).toEqual({
      interruptId: "top-level",
      namespace: ["tools"],
      value: GENERIC_INTERRUPT_PROJECTION,
      resumable: true,
      when: "during",
    })
  })

  test("translates Aegra 0.9.24 value to one correlated input.respond", async () => {
    const rawInput = protocolEvents(aegraDialect).find(
      (event) => event.method === "input.requested"
    )!
    const pending = nativeClientTesting.pendingFromInputEvent(
      rawInput as Extract<Event, { method: "input.requested" }>
    )
    expect(pending).toEqual({
      interruptId: "0123456789abcdef0123456789abcdef",
      namespace: [],
      value: GENERIC_INTERRUPT_PROJECTION,
      resumable: true,
      when: "during",
    })

    const responded: unknown[] = []
    const fakeClient = makeClient([
      {
        events: [
          rawInput,
          lifecycle("interrupted"),
        ],
      },
      {
        events: [lifecycle("completed")],
        onRespond: (params) => responded.push(params),
      },
    ])
    const native = makeNative(fakeClient)

    await collect(
      native.stream(
        [{ id: "human-1", type: "human", content: "승인해줘" }],
        streamConfig()
      )
    )
    await collect(
      native.stream([], {
        ...streamConfig(),
        command: { resume: { action: "approve" } } as never,
      })
    )

    expect(responded).toEqual([
      {
        namespace: [],
        interrupt_id: "0123456789abcdef0123456789abcdef",
        response: { action: "approve" },
      },
    ])
    expect(fakeClient.testing.runStarts).toBe(1)
  })

  test("resumes with only the user command and never echoes the opaque interrupt value", async () => {
    const secret = "OPAQUE_TOOL_SECRET_MUST_NOT_BE_ECHOED"
    const requested = {
      type: "event",
      method: "input.requested",
      params: {
        namespace: [],
        timestamp: 1,
        data: {
          interrupt_id: "interrupt-with-secret",
          payload: {
            schema: "future.private.schema",
            tool_payload: {
              chain_of_thought: ["private plan", { secret }],
            },
          },
        },
      },
    } as unknown as Event
    const responded: unknown[] = []
    const fakeClient = makeClient([
      { events: [requested, lifecycle("interrupted")] },
      {
        events: [lifecycle("completed")],
        onRespond: (params) => responded.push(params),
      },
    ])
    const native = makeNative(fakeClient)

    const interruptOutput = await collect(
      native.stream(
        [{ id: "human-1", type: "human", content: "승인 필요" }],
        streamConfig()
      )
    )
    await collect(
      native.stream([], {
        ...streamConfig(),
        command: { resume: "reject" } as never,
      })
    )

    expect(responded).toEqual([
      {
        namespace: [],
        interrupt_id: "interrupt-with-secret",
        response: "reject",
      },
    ])
    expect(JSON.stringify(responded)).not.toContain(secret)
    expect(JSON.stringify(responded)).not.toContain("private plan")
    expect(interruptOutput).toMatchObject([
      {
        event: "updates",
        data: {
          __interrupt__: [
            {
              value: {
                recognized: false,
                kind: "unknown",
              },
            },
          ],
        },
      },
    ])
    expect(JSON.stringify(interruptOutput)).not.toContain(secret)
    expect(JSON.stringify(interruptOutput)).not.toContain("private plan")
  })

  test("authoritative values reconcile only visible human and assistant text", () => {
    expect(
      normalizeStateMessages([
        {
          id: "answer-1",
          role: "assistant",
          content: [{ type: "text", text: "서버 최종 답변" }],
        },
        {
          id: "tool-result-1",
          type: "tool",
          name: "search_blog",
          tool_call_id: "call-1",
          content: "검색 완료",
        },
      ])
    ).toEqual([
      {
        id: "answer-1",
        type: "ai",
        content: [{ type: "text", text: "서버 최종 답변" }],
      },
    ])
  })

  test("never subscribes to checkpoint values, updates, or nested content", async () => {
    const secret = "RAW_DEEP_AGENT_STATE_MUST_NOT_REACH_ASSISTANT_UI"
    const events = [
      {
        type: "event",
        method: "values",
        params: {
          namespace: [],
          timestamp: 1,
          data: {
            messages: [
              {
                id: "human-1",
                role: "user",
                content: [{ type: "text", text: "공개 질문" }],
              },
              {
                id: "answer-1",
                role: "assistant",
                content: [{ type: "text", text: "공개 답변" }],
                tool_calls: [{ id: "call-1", name: "secret", args: { secret } }],
              },
              { id: "system-1", role: "system", content: secret },
              {
                id: "tool-1",
                role: "tool",
                content: secret,
                tool_call_id: "call-1",
              },
              {
                id: "reasoning-1",
                role: "assistant",
                content: [{ type: "reasoning", reasoning: secret }],
              },
              {
                id: "thinking-1",
                role: "assistant",
                content: [{ type: "thinking", thinking: secret }],
              },
            ],
            todos: [{ secret }],
            files: { "/memories/secret.txt": secret },
            scratch: { chain_of_thought: secret },
            ui: [{ type: "future-ui", secret }],
          },
        },
      },
      {
        type: "event",
        method: "updates",
        params: {
          namespace: [],
          timestamp: 2,
          data: {
            node: "deep-agent",
            values: { todos: [{ secret }], files: { secret } },
          },
        },
      },
      {
        type: "event",
        method: "values",
        params: {
          namespace: ["subagent:private"],
          timestamp: 3,
          data: {
            messages: [
              { role: "assistant", content: [{ type: "text", text: secret }] },
            ],
          },
        },
      },
      lifecycle("completed"),
    ] as unknown as Event[]
    const fakeClient = makeClient([{ events }])
    const output = await collect(
      makeNative(fakeClient).stream(
        [{ id: "human-1", type: "human", content: "질문" }],
        streamConfig()
      )
    )

    expect(fakeClient.testing.subscriptions[0]).toEqual({
      channels: ["messages", "lifecycle", "input", "tools", "custom"],
      options: {
        namespaces: [[]],
        depth: 0,
      },
    })
    expect(output).toEqual([])
    const serialized = JSON.stringify(output)
    expect(serialized).not.toContain(secret)
    expect(serialized).not.toContain("todos")
    expect(serialized).not.toContain("files")
    expect(serialized).not.toContain("scratch")
    expect(serialized).not.toContain("future-ui")
  })

  test("preserves only protocol citation annotations as answer source metadata", () => {
    expect(
      normalizeStateMessages([
        {
          id: "answer-with-source",
          role: "assistant",
          content: [
            {
              type: "text",
              text: "근거가 있습니다.",
              annotations: [
                {
                  type: "citation",
                  id: "source-1",
                  title: "Docker",
                  url: "https://example.com/docker",
                  chain_of_thought: "NEVER_PROJECT",
                },
              ],
            },
          ],
        },
      ])
    ).toMatchObject([
      {
        additional_kwargs: {
          metadata: {
            sources: [
              {
                key: "source-1",
                title: "Docker",
                url: "https://example.com/docker",
              },
            ],
          },
        },
      },
    ])
    expect(
      JSON.stringify(
        normalizeStateMessages([
          {
            id: "answer-with-source",
            role: "assistant",
            content: [
              {
                type: "text",
                text: "근거",
                annotations: [
                  {
                    type: "citation",
                    id: "source-1",
                    title: "Docker",
                    chain_of_thought: "NEVER_PROJECT",
                  },
                ],
              },
            ],
          },
        ])
      )
    ).not.toContain("NEVER_PROJECT")
  })

  test("rejects ambiguous parallel interrupts instead of resuming the wrong one", () => {
    const state = {
      values: {},
      tasks: [],
      interrupts: [
        { id: "interrupt-1", value: "one" },
        { id: "interrupt-2", value: "two" },
      ],
    } as unknown as ThreadState<Record<string, unknown>> & {
      interrupts: unknown
    }
    expect(() => extractPendingInterrupt(state)).toThrow(
      "동시에 여러 승인 요청"
    )
  })

  test("does not misclassify resumed-run resolver exhaustion as user cancellation", async () => {
    const controller = new AbortController()
    controller.abort(
      new DOMException("private resolver timed out", "TimeoutError")
    )
    const error = await nativeClientTesting
      .resolveResumedRunIdOrThrow(
        {
          runs: {
            list: async () => [],
          },
        } as unknown as Pick<Client, "runs">,
        "thread-1",
        new Set(),
        controller.signal
      )
      .catch((caught: unknown) => caught)

    expect(error).toBeInstanceOf(Error)
    expect((error as Error).name).toBe("Error")
    expect((error as Error).message).toBe(
      "재개된 실행 식별자를 확인하지 못했습니다."
    )
  })
})

describe("native stream lifecycle", () => {
  test("projects and deduplicates a nested watcher interrupt, then resumes its exact namespace", async () => {
    const secret = "NESTED_OPAQUE_PAYLOAD_MUST_NOT_BE_RETAINED"
    const requested = inputRequested(
      "interrupt-nested-1",
      ["nested_worker:task-1"],
      {
        schema: "syshin.rag.interrupt.v1",
        kind: "approval",
        title: "검색 실행 승인",
        prompt: "블로그 검색을 실행할까요?",
        private: secret,
      }
    )
    const responded: unknown[] = []
    const fakeClient = makeClient([
      {
        events: [lifecycle("running"), lifecycle("interrupted")],
        watcherEvents: [requested, requested],
      },
      {
        events: [lifecycle("running"), lifecycle("completed")],
        onRespond: (params) => responded.push(params),
      },
    ])
    const native = makeNative(fakeClient)

    const output = await collect(
      native.stream(
        [{ id: "human-1", type: "human", content: "중첩 승인" }],
        streamConfig()
      )
    )
    expect(
      output.filter(
        (item) =>
          item.event === "updates" &&
          "__interrupt__" in (item.data as Record<string, unknown>)
      )
    ).toHaveLength(1)
    expect(output).toMatchObject([
      {
        event: "updates",
        data: {
          __interrupt__: [
            {
              ns: ["nested_worker:task-1"],
              value: {
                recognized: false,
                kind: "unknown",
              },
            },
          ],
        },
      },
    ])
    expect(JSON.stringify(output)).not.toContain(secret)
    expect(nativeClientTesting.inspect(native).pendingInterrupts).toBe(1)

    await collect(
      native.stream([], {
        ...streamConfig(),
        command: { resume: "approve" } as never,
      })
    )
    expect(responded).toEqual([
      {
        namespace: ["nested_worker:task-1"],
        interrupt_id: "interrupt-nested-1",
        response: "approve",
      },
    ])
    expect(nativeClientTesting.inspect(native).pendingInterrupts).toBe(0)
    expect(fakeClient.testing.subscriptions).toEqual([
      {
        channels: ["messages", "lifecycle", "input", "tools", "custom"],
        options: { namespaces: [[]], depth: 0 },
      },
      {
        channels: ["messages", "lifecycle", "input", "tools", "custom"],
        options: { namespaces: [[]], depth: 0 },
      },
    ])
  })

  test("waits for a delayed nested watcher interrupt after root interrupted arrives", async () => {
    const requested = inputRequested(
      "interrupt-delayed",
      ["nested_worker:delayed"],
      {
        schema: "syshin.rag.interrupt.v1",
        kind: "approval",
        prompt: "지연된 중첩 승인을 계속할까요?",
      }
    )
    const fakeClient = makeClient([
      {
        events: [lifecycle("running"), lifecycle("interrupted")],
        delayedWatcherEvents: [requested],
        watcherDelayMs: 25,
      },
    ])
    const native = makeNative(fakeClient)

    const output = await collect(
      native.stream(
        [{ id: "human-1", type: "human", content: "역순 이벤트" }],
        streamConfig()
      )
    )
    expect(output).toMatchObject([
      {
        event: "updates",
        data: {
          __interrupt__: [
            {
              ns: ["nested_worker:delayed"],
              value: {
                recognized: true,
                kind: "approval",
                prompt: "지연된 중첩 승인을 계속할까요?",
              },
            },
          ],
        },
      },
    ])
    expect(nativeClientTesting.inspect(native).pendingInterrupts).toBe(1)
  })

  test("fails closed and retains no pending value when distinct nested interrupts race", async () => {
    const observedErrors: Error[] = []
    const fakeClient = makeClient([
      {
        events: [lifecycle("interrupted")],
        watcherEvents: [
          inputRequested("interrupt-1", ["worker:one"], {
            private: "FIRST_SECRET",
          }),
          inputRequested("interrupt-2", ["worker:two"], {
            private: "SECOND_SECRET",
          }),
          inputRequested("interrupt-3", ["worker:three"], {
            private: "THIRD_SECRET",
          }),
        ],
      },
    ])
    const native = makeNative(fakeClient, {
      onError: (error) => observedErrors.push(error),
    })

    await expect(
      collect(
        native.stream(
          [{ id: "human-1", type: "human", content: "동시 승인" }],
          streamConfig()
        )
      )
    ).rejects.toThrow("에이전트 실행을 완료하지 못했습니다.")
    expect(observedErrors).toHaveLength(1)
    expect(JSON.stringify(observedErrors)).not.toContain("FIRST_SECRET")
    expect(JSON.stringify(observedErrors)).not.toContain("SECOND_SECRET")
    expect(JSON.stringify(observedErrors)).not.toContain("THIRD_SECRET")
    expect(nativeClientTesting.inspect(native).pendingInterrupts).toBe(0)
  })

  test("fails closed when a watcher delivers malformed interrupt identifiers", async () => {
    const malformed = {
      type: "event",
      method: "input.requested",
      params: {
        namespace: null,
        timestamp: 1,
        data: {
          interrupt_id: "../unsafe",
          payload: { private: "MALFORMED_SECRET" },
        },
      },
    } as unknown as Event
    const fakeClient = makeClient([
      {
        events: [lifecycle("interrupted")],
        watcherEvents: [malformed],
      },
    ])
    const native = makeNative(fakeClient)

    await expect(
      collect(
        native.stream(
          [{ id: "human-1", type: "human", content: "잘못된 승인" }],
          streamConfig()
        )
      )
    ).rejects.toThrow("에이전트 실행을 완료하지 못했습니다.")
    expect(nativeClientTesting.inspect(native).pendingInterrupts).toBe(0)
  })

  test("treats a nested failure as activity while allowing the root run to recover", async () => {
    const activities: AgentActivity[] = []
    const observedErrors: Error[] = []
    const fakeClient = makeClient([
      {
        events: [
          lifecycle(
            "failed",
            "postgres://owner:nested-secret@db.internal",
            ["nested_worker:task-1"]
          ),
          lifecycle("running"),
          lifecycle("completed"),
        ],
      },
    ])
    const native = makeNative(fakeClient, {
      onActivity: (activity) => activities.push(activity),
      onError: (error) => observedErrors.push(error),
    })

    const output = await collect(
      native.stream(
        [{ id: "human-1", type: "human", content: "복구 테스트" }],
        streamConfig()
      )
    )
    expect(output).toEqual([])
    expect(observedErrors).toEqual([])
    expect(activities).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          kind: "nested",
          namespace: ["nested_worker:task-1"],
          status: "failed",
        }),
        expect.objectContaining({
          kind: "lifecycle",
          namespace: [],
          status: "completed",
        }),
      ])
    )
    expect(JSON.stringify(activities)).not.toContain("nested-secret")
  })

  test("keeps a pending interrupt after input.respond rejects and permits a safe retry", async () => {
    const requested = inputRequested("interrupt-retry", [], {
      private: "OPAQUE_RETRY_SECRET",
    })
    const responded: unknown[] = []
    const fakeClient = makeClient([
      { events: [requested, lifecycle("interrupted")] },
      {
        events: [],
        onRespond: () => {
          throw new Error("postgres://owner:respond-secret@db.internal")
        },
      },
      {
        events: [lifecycle("running"), lifecycle("completed")],
        onRespond: (params) => responded.push(params),
      },
    ])
    const auth = makeAuthHarness("user-1", {
      runLists: [
        [],
        [],
        [{ run_id: "resumed-run-retry", status: "running" }],
      ],
    })
    const native = makeNative(fakeClient, {}, auth)
    await collect(
      native.stream(
        [{ id: "human-1", type: "human", content: "재시도 승인" }],
        streamConfig()
      )
    )

    await expect(
      collect(
        native.stream([], {
          ...streamConfig(),
          command: { resume: "approve" } as never,
        })
      )
    ).rejects.toThrow("에이전트 실행을 완료하지 못했습니다.")
    expect(nativeClientTesting.inspect(native).pendingInterrupts).toBe(1)

    await collect(
      native.stream([], {
        ...streamConfig(),
        command: { resume: "approve" } as never,
      })
    )
    expect(responded).toEqual([
      {
        namespace: [],
        interrupt_id: "interrupt-retry",
        response: "approve",
      },
    ])
    expect(nativeClientTesting.inspect(native).pendingInterrupts).toBe(0)
    expect(JSON.stringify(responded)).not.toContain("respond-secret")
  })

  test("subscribes to custom inspection events and suppresses nested transcript text", async () => {
    const activities: AgentActivity[] = []
    const events = [
      ...protocolEvents(inspectionEvents),
      ...protocolEvents(nestedNamespace),
    ]
    const fakeClient = makeClient([{ events }])
    const native = makeNative(fakeClient, {
      onActivity: (activity) => activities.push(activity),
    })
    const output = await collect(
      native.stream(
        [{ id: "human-1", type: "human", content: "질문" }],
        streamConfig()
      )
    )

    expect(fakeClient.testing.subscriptions[0]).toMatchObject({
      channels: expect.arrayContaining(["messages", "custom"]),
      options: {
        namespaces: [[]],
        depth: 0,
      },
    })
    expect(activities).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          kind: "retrieval",
          delivery: "live-run-only",
          methodId: "fixture-retriever",
          corpusRevision:
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        }),
      ])
    )
    expect(
      activities.filter((activity) => activity.kind === "retrieval")
    ).toHaveLength(1)
    expect(JSON.stringify(activities)).not.toContain("chain_of_thought")
    expect(JSON.stringify(output)).not.toContain("근거를 찾았습니다.")
  })

  test("starts one APv2 run and surfaces lifecycle failure safely", async () => {
    const error = `postgres://owner:secret@db.internal ${"x".repeat(400)}`
    const observedErrors: Error[] = []
    const fakeClient = makeClient([
      { events: [lifecycle("failed", error)] },
    ])
    const native = makeNative(fakeClient, {
      onError: (observed) => observedErrors.push(observed),
    })
    const output = await collect(
      native.stream(
        [{ id: "human-1", type: "human", content: "질문" }],
        streamConfig()
      )
    )

    expect(fakeClient.testing.runStarts).toBe(1)
    expect(output).toEqual([
      {
        event: "error",
        data: { message: "에이전트 실행을 완료하지 못했습니다." },
      },
    ])
    expect(JSON.stringify(output)).not.toContain("secret")
    expect(observedErrors).toHaveLength(1)
    expect(observedErrors[0]).toBeInstanceOf(AgentLifecycleError)
  })

  test("cancels exactly once and waits only through read-only status polls", async () => {
    let cancelCalls = 0
    let getCalls = 0
    const client = {
      runs: {
        cancel: async () => {
          cancelCalls += 1
        },
        get: async () => {
          getCalls += 1
          return {
            status: getCalls === 1 ? "running" : "interrupted",
          }
        },
      },
    } as unknown as Pick<Client, "runs">

    await cancelRunAndWait(client, "thread-1", "run-1")
    expect(cancelCalls).toBe(1)
    expect(getCalls).toBe(2)
  })

  test("auth abort closes the APv2 stream and cancels the active run once", async () => {
    const fakeClient = makeClient([
      {
        events: [lifecycle("running")],
        waitForClose: () => undefined,
      },
    ])
    const native = makeNative(fakeClient)
    const controller = new AbortController()
    const iterator = await native.stream(
      [{ id: "human-1", type: "human", content: "오래 걸리는 질문" }],
      { ...streamConfig(), abortSignal: controller.signal }
    )
    const pending = iterator.next()
    await waitUntil(() => fakeClient.testing.runStarts === 1)
    controller.abort(new DOMException("identity changed", "AbortError"))

    await expect(pending).resolves.toMatchObject({ done: true })
    expect(cancellationRequests(authFor(native))).toHaveLength(1)
  })

  test("abort before run.start returns keeps the old credential until the late run id is cancelled", async () => {
    let resolveStart:
      | ((value: { run_id: string }) => void)
      | undefined
    let startAttempted = false
    const fakeClient = makeClient([
      {
        events: [],
        waitForClose: () => undefined,
        startRun: async () => {
          startAttempted = true
          return await new Promise<{ run_id: string }>((resolve) => {
            resolveStart = resolve
          })
        },
      },
    ])
    const native = makeNative(fakeClient)
    const controller = new AbortController()
    const iterator = await native.stream(
      [{ id: "human-1", type: "human", content: "시작 중 취소" }],
      { ...streamConfig(), abortSignal: controller.signal }
    )
    const pending = iterator.next()
    await waitUntil(() => startAttempted)

    controller.abort(new DOMException("cancel before run id", "AbortError"))
    expect(cancellationRequests(authFor(native))).toEqual([])
    resolveStart?.({ run_id: "late-run-id" })

    await expect(pending).resolves.toMatchObject({ done: true })
    expect(cancellationRequests(authFor(native))).toEqual([
      expect.objectContaining({
        method: "POST",
        url: expect.stringContaining(
          "/threads/thread-1/runs/late-run-id/cancel?wait=0&action=interrupt"
        ),
      }),
    ])
  })

  test("resolves and cancels a resumed APv2 run exactly once", async () => {
    const requested = {
      type: "event",
      method: "input.requested",
      params: {
        namespace: [],
        timestamp: 1,
        data: {
          interrupt_id: "interrupt-1",
          payload: { action: "approve" },
        },
      },
    } as unknown as Event
    const fakeClient = makeClient(
      [
        { events: [requested, lifecycle("interrupted")] },
        {
          events: [lifecycle("running")],
          waitForClose: () => undefined,
        },
      ],
      {
        onListRuns: () => [
          { run_id: "resumed-run-1", status: "running" },
        ],
      }
    )
    const native = makeNative(fakeClient)
    await collect(
      native.stream(
        [{ id: "human-1", type: "human", content: "승인 필요" }],
        streamConfig()
      )
    )

    const controller = new AbortController()
    const iterator = await native.stream([], {
      ...streamConfig(),
      command: { resume: "approve" } as never,
      abortSignal: controller.signal,
    })
    await expect(iterator.next()).resolves.toMatchObject({
      done: false,
      value: { event: "updates", data: { __interrupt__: [] } },
    })
    const pending = iterator.next()
    await Promise.resolve()
    await Promise.resolve()
    controller.abort(new DOMException("stop resumed run", "AbortError"))

    await expect(pending).resolves.toMatchObject({ done: true })
    expect(cancellationRequests(authFor(native))).toHaveLength(1)
  })

  test("finishes resumed-run discovery after Stop and cancels only the discovered run", async () => {
    const requested = inputRequested("interrupt-race", [], {
      schema: "syshin.rag.interrupt.v1",
      kind: "approval",
      prompt: "재개할까요?",
    })
    const fakeClient = makeClient([
      { events: [requested, lifecycle("interrupted")] },
      {
        events: [lifecycle("running")],
        waitForClose: () => undefined,
      },
    ])
    const auth = makeAuthHarness("user-1", {
      runLists: [
        [],
        [],
        [{ run_id: "resumed-run-after-stop", status: "running" }],
      ],
    })
    const native = makeNative(fakeClient, {}, auth)
    await collect(
      native.stream(
        [{ id: "human-1", type: "human", content: "승인 필요" }],
        streamConfig()
      )
    )

    const controller = new AbortController()
    const iterator = await native.stream([], {
      ...streamConfig(),
      command: { resume: "approve" } as never,
      abortSignal: controller.signal,
    })
    const pending = iterator.next()
    await waitUntil(() => auth.runListCalls === 2)
    controller.abort(
      new DOMException("stop while resolving resumed run", "AbortError")
    )

    await expect(pending).resolves.toMatchObject({ done: true })
    expect(cancellationRequests(auth)).toEqual([
      expect.objectContaining({
        method: "POST",
        url: expect.stringContaining(
          "/threads/thread-1/runs/resumed-run-after-stop/cancel?wait=0&action=interrupt"
        ),
      }),
    ])
  })

  test("identity dispose cancels exactly once with the stream-start old token before clearing it", async () => {
    let brokerStateDuringCancel:
      | ReturnType<typeof tokenBrokerTesting.inspect>
      | undefined
    const oldAuth = makeAuthHarness("old-user", {
      onCancel: () => {
        brokerStateDuringCancel = tokenBrokerTesting.inspect(oldAuth.broker)
      },
    })
    const newAuth = makeAuthHarness("new-user")
    const fakeClient = makeClient([
      {
        events: [lifecycle("running")],
        waitForClose: () => undefined,
      },
    ])
    const native = makeNative(fakeClient, {}, oldAuth)
    native.setPendingInterrupt("thread-pending", {
      interruptId: "interrupt-pending",
      namespace: [],
      value: GENERIC_INTERRUPT_PROJECTION,
      resumable: true,
      when: "during",
    })
    const iterator = await native.stream(
      [{ id: "human-1", type: "human", content: "오래 걸리는 질문" }],
      streamConfig()
    )
    const pending = iterator.next()
    await waitUntil(() => fakeClient.testing.runStarts === 1)
    const newToken = await newAuth.broker.get(
      new AbortController().signal
    )

    const firstDispose = native.dispose()
    const concurrentDispose = native.dispose()
    expect(concurrentDispose).toBe(firstDispose)
    await expect(pending).resolves.toMatchObject({ done: true })
    await firstDispose

    const cancels = cancellationRequests(oldAuth)
    expect(cancels).toHaveLength(1)
    expect(cancels[0]).toMatchObject({
      authorization: `Bearer ${oldAuth.token}`,
      method: "POST",
    })
    expect(cancels[0]!.authorization).not.toBe(`Bearer ${newToken}`)
    expect(brokerStateDuringCancel).toEqual({
      cached: false,
      refreshing: false,
      sealed: true,
    })
    expect(oldAuth.mintCalls).toBe(1)
    expect(newAuth.mintCalls).toBe(1)
    expect(tokenBrokerTesting.inspect(oldAuth.broker)).toEqual({
      cached: false,
      refreshing: false,
      sealed: true,
    })
    expect(tokenBrokerTesting.inspect(newAuth.broker)).toEqual({
      cached: true,
      refreshing: false,
      sealed: false,
    })
    expect(nativeClientTesting.inspect(native)).toEqual({
      activeStreams: 0,
      disposed: true,
      pendingInterrupts: 0,
    })
    await expect(
      oldAuth.broker.get(new AbortController().signal, true)
    ).rejects.toThrow("disposed")
  })

  test("401 during identity cancellation never refreshes or leaks across identities", async () => {
    const oldAuth = makeAuthHarness("old-user", { cancelStatus: 401 })
    const newAuth = makeAuthHarness("new-user")
    const fakeClient = makeClient([
      {
        events: [lifecycle("running")],
        waitForClose: () => undefined,
      },
    ])
    const native = makeNative(fakeClient, {}, oldAuth)
    const iterator = await native.stream(
      [{ id: "human-1", type: "human", content: "취소될 질문" }],
      streamConfig()
    )
    const pending = iterator.next()
    await waitUntil(() => fakeClient.testing.runStarts === 1)
    const newToken = await newAuth.broker.get(
      new AbortController().signal
    )

    await Promise.all([native.dispose(), native.dispose()])
    await expect(pending).resolves.toMatchObject({ done: true })

    const cancels = cancellationRequests(oldAuth)
    expect(cancels).toHaveLength(1)
    expect(cancels[0]!.authorization).toBe(`Bearer ${oldAuth.token}`)
    expect(cancels[0]!.authorization).not.toBe(`Bearer ${newToken}`)
    expect(oldAuth.mintCalls).toBe(1)
    expect(
      oldAuth.requests.filter((request) => request.method === "GET")
    ).toEqual([])
    expect(tokenBrokerTesting.inspect(oldAuth.broker)).toEqual({
      cached: false,
      refreshing: false,
      sealed: true,
    })
    expect(nativeClientTesting.inspect(native)).toEqual({
      activeStreams: 0,
      disposed: true,
      pendingInterrupts: 0,
    })
  })

  test("concurrent dispose during token capture aborts the old refresh and still clears client state", async () => {
    let mintSignal: AbortSignal | undefined
    const oldAuth = makeAuthHarness("old-user", {
      mintResponse: async (signal) => {
        mintSignal = signal
        return await new Promise<Response>((_resolve, reject) => {
          signal.addEventListener("abort", () => reject(signal.reason), {
            once: true,
          })
        })
      },
    })
    const newAuth = makeAuthHarness("new-user")
    const fakeClient = makeClient([
      {
        events: [lifecycle("running")],
        waitForClose: () => undefined,
      },
    ])
    const native = makeNative(fakeClient, {}, oldAuth)
    const iterator = await native.stream(
      [{ id: "human-1", type: "human", content: "시작 중인 질문" }],
      streamConfig()
    )
    const pending = iterator.next()
    await waitUntil(() => mintSignal !== undefined)
    const newToken = await newAuth.broker.get(
      new AbortController().signal
    )

    await Promise.all([native.dispose(), native.dispose()])
    await expect(pending).resolves.toMatchObject({ done: true })

    expect(mintSignal?.aborted).toBe(true)
    expect(cancellationRequests(oldAuth)).toEqual([])
    expect(fakeClient.testing.runStarts).toBe(0)
    expect(newToken).toBe(newAuth.token)
    expect(tokenBrokerTesting.inspect(oldAuth.broker)).toEqual({
      cached: false,
      refreshing: false,
      sealed: true,
    })
    expect(nativeClientTesting.inspect(native)).toEqual({
      activeStreams: 0,
      disposed: true,
      pendingInterrupts: 0,
    })
  })
})

function lifecycle(
  status: "started" | "running" | "completed" | "failed" | "interrupted",
  error?: string,
  namespace: string[] = []
): Event {
  return {
    type: "event",
    method: "lifecycle",
    params: {
      namespace,
      timestamp: 1,
      data: {
        event: status,
        graph_name: "agent",
        ...(error ? { error } : {}),
      },
    },
  }
}

function inputRequested(
  interruptId: string,
  namespace: string[],
  payload: unknown
): Event {
  return {
    type: "event",
    method: "input.requested",
    params: {
      namespace,
      timestamp: 1,
      data: {
        interrupt_id: interruptId,
        payload,
      },
    },
  } as Event
}

interface FakeStreamPlan {
  events: Event[]
  watcherEvents?: Event[]
  delayedWatcherEvents?: Event[]
  watcherDelayMs?: number
  onRespond?: (params: unknown) => void
  startRun?: () => Promise<{ run_id: string }>
  waitForClose?: (resolve: () => void) => void
}

function makeClient(
  plans: FakeStreamPlan[],
  options: {
    onListRuns?: () => unknown[]
  } = {}
): Client & {
  testing: {
    runStarts: number
    subscriptions: Array<{ channels: unknown; options: unknown }>
  }
} {
  const testing = {
    runStarts: 0,
    subscriptions: [] as Array<{ channels: unknown; options: unknown }>,
  }
  const client = {
    testing,
    threads: {
      stream: () => {
        const plan = plans.shift()
        if (!plan) throw new Error("Missing fake stream plan")
        const listeners = new Set<(event: Event) => void>()
        const interrupts: Array<{
          interruptId: string
          namespace: string[]
          payload: unknown
        }> = []
        const emit = (event: Event) => {
          if (
            event.method === "input.requested" &&
            Array.isArray(event.params.namespace)
          ) {
            const data = event.params.data as typeof event.params.data & {
              value?: unknown
            }
            interrupts.push({
              interruptId: data.interrupt_id,
              namespace: [...event.params.namespace],
              payload: data.payload ?? data.value,
            })
          }
          for (const listener of listeners) {
            try {
              listener(event)
            } catch {
              // Match the SDK watcher contract: observer failures do not
              // wedge the shared transport.
            }
          }
        }
        let close: (() => void) | undefined
        const closed = new Promise<void>((resolve) => {
          close = resolve
          plan.waitForClose?.(resolve)
        })
        const subscription = {
          unsubscribe: async () => undefined,
          async *[Symbol.asyncIterator]() {
            for (const event of plan.events) {
              emit(event)
              if (
                event.method === "lifecycle" &&
                event.params.namespace.length === 0 &&
                event.params.data.event === "interrupted" &&
                plan.delayedWatcherEvents
              ) {
                setTimeout(() => {
                  for (const delayed of plan.delayedWatcherEvents ?? []) {
                    emit(delayed)
                  }
                }, plan.watcherDelayMs ?? 10)
              }
              yield event
            }
            if (plan.waitForClose) await closed
          },
        }
        return {
          submitRun: async () => {
            testing.runStarts += 1
            for (const event of plan.watcherEvents ?? []) emit(event)
            if (plan.startRun) return await plan.startRun()
            return { run_id: `run-${testing.runStarts}` }
          },
          respondInput: async (params: unknown) => plan.onRespond?.(params),
          interrupts,
          run: {
            start: async () => {
              testing.runStarts += 1
              if (plan.startRun) return await plan.startRun()
              return { run_id: `run-${testing.runStarts}` }
            },
          },
          input: {
            respond: async (params: unknown) => plan.onRespond?.(params),
          },
          subscribe: async (channels: unknown, streamOptions: unknown) => {
            testing.subscriptions.push({
              channels,
              options: streamOptions,
            })
            return subscription
          },
          onEvent: (listener: (event: Event) => void) => {
            listeners.add(listener)
            return () => listeners.delete(listener)
          },
          close: async () => close?.(),
        } as unknown as ThreadStream
      },
    },
    runs: {
      cancel: async () => undefined,
      get: async () => ({ status: "interrupted" }),
      list: async () => options.onListRuns?.() ?? [],
    },
  }
  return client as unknown as Client & {
    testing: {
      runStarts: number
      subscriptions: Array<{ channels: unknown; options: unknown }>
    }
  }
}

interface AuthRequest {
  authorization: string | null
  method: string
  url: string
}

interface AuthHarness {
  broker: AgentTokenBroker
  mintCalls: number
  requests: AuthRequest[]
  runListCalls: number
  token: string
}

const nativeAuthHarnesses = new WeakMap<NativeAgentClient, AuthHarness>()

function jwtToken(exp: number, subject: string): string {
  const encode = (value: object) =>
    Buffer.from(JSON.stringify(value)).toString("base64url")
  return `${encode({ alg: "HS256", typ: "JWT" })}.${encode({
    exp,
    sub: subject,
  })}.signature`
}

function makeAuthHarness(
  identity: string,
  options: {
    cancelStatus?: number
    mintResponse?: (
      signal: AbortSignal,
      token: string
    ) => Promise<Response>
    onCancel?: () => void
    runLists?: unknown[][]
  } = {}
): AuthHarness {
  const harness = {
    broker: undefined as unknown as AgentTokenBroker,
    mintCalls: 0,
    requests: [] as AuthRequest[],
    runListCalls: 0,
    token: jwtToken(2_000, identity),
  }
  harness.broker = new AgentTokenBroker(identity, {
    nowSeconds: () => 1_000,
    fetch: async (input, init) => {
      const url = String(input)
      if (url === "/api/agent-token") {
        harness.mintCalls += 1
        if (options.mintResponse) {
          return await options.mintResponse(
            init?.signal as AbortSignal,
            harness.token
          )
        }
        return new Response(JSON.stringify({ token: harness.token }), {
          status: 200,
          headers: { "content-type": "application/json" },
        })
      }
      harness.requests.push({
        authorization: new Headers(init?.headers).get("Authorization"),
        method: init?.method ?? "GET",
        url,
      })
      const parsedUrl = new URL(url)
      if (
        parsedUrl.pathname.endsWith("/runs") &&
        parsedUrl.searchParams.get("limit") === "10" &&
        parsedUrl.searchParams.get("offset") === "0"
      ) {
        const runLists =
          options.runLists ??
          [
            [],
            [{ run_id: "resumed-run-1", status: "running" }],
          ]
        const index = Math.min(harness.runListCalls, runLists.length - 1)
        harness.runListCalls += 1
        return new Response(JSON.stringify(runLists[index] ?? []), {
          status: 200,
          headers: { "content-type": "application/json" },
        })
      }
      if (url.includes("/cancel?")) {
        options.onCancel?.()
        const status = options.cancelStatus ?? 204
        return status === 204
          ? new Response(null, { status })
          : new Response(JSON.stringify({ error: "cancel rejected" }), {
              status,
              headers: { "content-type": "application/json" },
            })
      }
      return new Response(JSON.stringify({ status: "interrupted" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      })
    },
  })
  return harness
}

function authFor(native: NativeAgentClient): AuthHarness {
  const harness = nativeAuthHarnesses.get(native)
  if (!harness) throw new Error("Missing auth harness")
  return harness
}

function cancellationRequests(harness: AuthHarness): AuthRequest[] {
  return harness.requests.filter(
    (request) =>
      request.method === "POST" &&
      new URL(request.url).pathname.endsWith("/cancel")
  )
}

function makeNative(
  client: Client,
  callbacks: {
    onActivity?: (activity: AgentActivity) => void
    onError?: (error: Error) => void
  } = {},
  auth = makeAuthHarness("user-1")
): NativeAgentClient {
  const native = new NativeAgentClient({
    apiUrl: "https://agent.example",
    assistantId: "agent",
    identity: auth.broker.identity,
    client,
    tokenBroker: auth.broker,
    ...callbacks,
  })
  nativeAuthHarnesses.set(native, auth)
  return native
}

function streamConfig() {
  return {
    abortSignal: new AbortController().signal,
    initialize: async () => ({
      remoteId: "thread-1",
      externalId: "thread-1",
    }),
  }
}

async function collect(
  iterable:
    | AsyncGenerator<LangGraphMessagesEvent<LangChainMessage>>
    | Promise<AsyncGenerator<LangGraphMessagesEvent<LangChainMessage>>>
): Promise<LangGraphMessagesEvent<LangChainMessage>[]> {
  const resolved = await iterable
  const output: LangGraphMessagesEvent<LangChainMessage>[] = []
  for await (const item of resolved) output.push(item)
  return output
}

async function waitUntil(predicate: () => boolean): Promise<void> {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (predicate()) return
    await Promise.resolve()
  }
  throw new Error("Condition was not reached")
}
