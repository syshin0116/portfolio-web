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
      expect.objectContaining({
        namespace: [],
        interrupt_id: "0123456789abcdef0123456789abcdef",
        response: { action: "approve" },
        config: {
          metadata: {
            syshin_ui_submit_nonce: expect.any(String),
          },
        },
        metadata: expect.objectContaining({
          syshin_ui_submit_nonce: expect.any(String),
        }),
      }),
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
      expect.objectContaining({
        namespace: [],
        interrupt_id: "interrupt-with-secret",
        response: "reject",
        metadata: expect.objectContaining({
          syshin_ui_submit_nonce: expect.any(String),
        }),
      }),
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
        "00000000-0000-4000-8000-000000000000",
        controller.signal
      )
      .catch((caught: unknown) => caught)

    expect(error).toBeInstanceOf(Error)
    expect((error as Error).name).toBe("Error")
    expect((error as Error).message).toBe(
      "재개된 실행 식별자를 확인하지 못했습니다."
    )
  })

  test("binds only a fresh same-thread run with the exact internal nonce", async () => {
    const nonce = "00000000-0000-4000-8000-000000000000"
    const correlatedConfig = {
      metadata: { syshin_ui_submit_nonce: nonce },
    }
    const resolved = await nativeClientTesting.resolveResumedRunIdOrThrow(
      {
        runs: {
          list: async () =>
            [
              {
                run_id: "stale-run",
                thread_id: "thread-1",
                config: correlatedConfig,
              },
              {
                run_id: "foreign-run",
                thread_id: "thread-2",
                config: correlatedConfig,
              },
              {
                run_id: "wrong-nonce-run",
                thread_id: "thread-1",
                config: {
                  metadata: { syshin_ui_submit_nonce: "wrong" },
                },
              },
              {
                run_id: "conflicting-run",
                thread_id: "thread-1",
                metadata: { syshin_ui_submit_nonce: nonce },
                config: {
                  metadata: { syshin_ui_submit_nonce: "wrong" },
                },
              },
              {
                run_id: "exact-run",
                thread_id: "thread-1",
                config: correlatedConfig,
              },
            ] as never,
        },
      } as unknown as Pick<Client, "runs">,
      "thread-1",
      new Set(["stale-run"]),
      nonce,
      new AbortController().signal
    )

    expect(resolved).toBe("exact-run")
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
      expect.objectContaining({
        namespace: ["nested_worker:task-1"],
        interrupt_id: "interrupt-nested-1",
        response: "approve",
        metadata: expect.objectContaining({
          syshin_ui_submit_nonce: expect.any(String),
        }),
      }),
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
    const auth = makeAuthHarness("user-1")
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
      expect.objectContaining({
        namespace: [],
        interrupt_id: "interrupt-retry",
        response: "approve",
        metadata: expect.objectContaining({
          syshin_ui_submit_nonce: expect.any(String),
        }),
      }),
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
    const auth = makeAuthHarness("user-1", {
      runListFactory: (metadata) =>
        metadata
          ? [
              {
                run_id: "late-run-id",
                status: "running",
                metadata,
              },
            ]
          : [],
    })
    const native = makeNative(fakeClient, {}, auth)
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
    const nonces: string[] = []
    const pollsByNonce = new Map<string, number>()
    const auth = makeAuthHarness("user-1", {
      runListFactory: (metadata) => {
        const nonce =
          typeof metadata?.syshin_ui_submit_nonce === "string"
            ? metadata.syshin_ui_submit_nonce
            : undefined
        if (!nonce) return []
        if (!nonces.includes(nonce)) nonces.push(nonce)
        const polls = (pollsByNonce.get(nonce) ?? 0) + 1
        pollsByNonce.set(nonce, polls)
        if (nonces.indexOf(nonce) === 1 && polls < 2) return []
        return [
          {
            run_id:
              nonces.indexOf(nonce) === 1
                ? "resumed-run-after-stop"
                : "initial-run-before-stop",
            status: "running",
            metadata,
          },
        ]
      },
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
    await waitUntil(
      () =>
        nonces.length === 2 &&
        (pollsByNonce.get(nonces[1]!) ?? 0) === 1
    )
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
    const oldReads = oldAuth.requests.filter(
      (request) => request.method === "GET"
    )
    expect(oldReads.length).toBeGreaterThan(0)
    expect(
      oldReads.every(
        (request) =>
          request.authorization === `Bearer ${oldAuth.token}` &&
          new URL(request.url).pathname === "/threads/thread-1/runs"
      )
    ).toBe(true)
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

  test("fails and cancels when a non-paused APv2 iterator ends without a terminal lifecycle", async () => {
    const fakeClient = makeClient([{ events: [] }])
    const native = makeNative(fakeClient)

    await expect(
      collect(
        native.stream(
          [{ id: "human-1", type: "human", content: "끝나면 안 돼" }],
          streamConfig()
        )
      )
    ).rejects.toThrow("에이전트 실행을 완료하지 못했습니다.")
    expect(cancellationRequests(authFor(native))).toHaveLength(1)
  })

  test("does not mistake an internal AbortError for caller cancellation", async () => {
    const fakeClient = makeClient([
      {
        events: [lifecycle("running")],
        streamError: new DOMException(
          "private reconnect exhaustion",
          "AbortError"
        ),
      },
    ])
    const observed: Error[] = []
    const native = makeNative(fakeClient, {
      onError: (error) => observed.push(error),
    })

    await expect(
      collect(
        native.stream(
          [{ id: "human-1", type: "human", content: "재연결" }],
          streamConfig()
        )
      )
    ).rejects.toThrow("에이전트 실행을 완료하지 못했습니다.")
    expect(cancellationRequests(authFor(native))).toHaveLength(1)
    expect(observed).toHaveLength(1)
    expect(observed[0]!.stack).toBeUndefined()
    expect(JSON.stringify(observed)).not.toContain("reconnect exhaustion")
  })

  test("uses the public ordering watermark to drop fresh-client Aegra history", async () => {
    const activities: AgentActivity[] = []
    const fakeClient = makeClient([
      {
        preserveSequence: true,
        appliedThroughSeq: 0,
        preDispatchEvents: [
          sequenced(lifecycle("interrupted"), 1, "historical-terminal"),
        ],
        events: [
          sequenced(lifecycle("running"), 2, "current-running"),
          sequenced(lifecycle("completed"), 3, "current-completed"),
        ],
      },
    ])
    const native = makeNative(fakeClient, {
      onActivity: (activity) => activities.push(activity),
    })

    await collect(
      native.stream(
        [{ id: "human-1", type: "human", content: "새 실행" }],
        streamConfig()
      )
    )
    expect(activities.map((activity) => activity.status)).toEqual([
      "running",
      "completed",
    ])
    expect(cancellationRequests(authFor(native))).toEqual([])
  })

  test.each([
    {
      label: "missing",
      events: [lifecycle("completed")],
    },
    {
      label: "non-monotonic",
      events: [
        sequenced(lifecycle("running"), 1, "seq-running"),
        sequenced(lifecycle("completed"), 1, "seq-completed"),
      ],
    },
  ])("fails closed and cancels on $label APv2 sequence", async ({ events }) => {
    const fakeClient = makeClient([
      { events, preserveSequence: true, appliedThroughSeq: 0 },
    ])
    const native = makeNative(fakeClient)

    await expect(
      collect(
        native.stream(
          [{ id: "human-1", type: "human", content: "순서 검증" }],
          streamConfig()
        )
      )
    ).rejects.toThrow("에이전트 실행을 완료하지 못했습니다.")
    expect(cancellationRequests(authFor(native))).toHaveLength(1)
  })

  test("deduplicates lifecycle event IDs without projecting root activity twice", async () => {
    const activities: AgentActivity[] = []
    const duplicate = sequenced(
      lifecycle("running"),
      1,
      "same-running-event"
    )
    const fakeClient = makeClient([
      {
        preserveSequence: true,
        appliedThroughSeq: 0,
        events: [
          duplicate,
          duplicate,
          sequenced(lifecycle("completed"), 2, "terminal-event"),
        ],
      },
    ])
    await collect(
      makeNative(fakeClient, {
        onActivity: (activity) => activities.push(activity),
      }).stream(
        [{ id: "human-1", type: "human", content: "중복" }],
        streamConfig()
      )
    )

    expect(
      activities.filter((activity) => activity.status === "running")
    ).toHaveLength(1)
    expect(
      activities.filter((activity) => activity.status === "completed")
    ).toHaveLength(1)
  })

  test("recovers an empty run.start result only through the exact nonce metadata", async () => {
    const fakeClient = makeClient([
      {
        events: [lifecycle("running"), lifecycle("completed")],
        startRun: async () => ({}),
      },
    ])
    const auth = makeAuthHarness("user-1", {
      runListFactory: (metadata) =>
        metadata
          ? [
              {
                run_id: "unrelated-new-run",
                status: "running",
                config: {
                  metadata: { syshin_ui_submit_nonce: "wrong" },
                },
              },
              {
                run_id: "nonce-matched-run",
                status: "running",
                config: { metadata },
              },
            ]
          : [],
    })
    const native = makeNative(fakeClient, {}, auth)

    await collect(
      native.stream(
        [{ id: "human-1", type: "human", content: "빈 응답" }],
        streamConfig()
      )
    )
    expect(cancellationRequests(auth)).toEqual([])
    expect(fakeClient.testing.lastMetadata).toMatchObject({
      syshin_ui_submit_nonce: expect.any(String),
    })
    expect(fakeClient.testing.lastConfig).toMatchObject({
      metadata: {
        syshin_ui_submit_nonce: expect.any(String),
      },
    })
  })

  test("cancels the nonce-matched run when run.start response is lost", async () => {
    const sentinel = "PRIVATE_RUN_START_FAILURE"
    const fakeClient = makeClient([
      {
        events: [],
        startRun: async () => {
          throw new Error(sentinel)
        },
      },
    ])
    const observed: Error[] = []
    const native = makeNative(fakeClient, {
      onError: (error) => observed.push(error),
    })

    await expect(
      collect(
        native.stream(
          [{ id: "human-1", type: "human", content: "응답 유실" }],
          streamConfig()
        )
      )
    ).rejects.toThrow("에이전트 실행을 완료하지 못했습니다.")
    expect(cancellationRequests(authFor(native))).toHaveLength(1)
    expect(JSON.stringify(observed)).not.toContain(sentinel)
  })

  test("merges caller metadata while overriding an untrusted submit nonce", async () => {
    const fakeClient = makeClient([
      { events: [lifecycle("completed")] },
    ])
    await collect(
      makeNative(fakeClient).stream(
        [{ id: "human-1", type: "human", content: "메타데이터" }],
        {
          ...streamConfig(),
          runConfig: {
            configurable: { mode: "hybrid" },
            metadata: {
              experiment: "rrf-v2",
              syshin_ui_submit_nonce: "attacker-controlled",
            },
          },
        }
      )
    )

    const submission = fakeClient.testing.submissions[0] as Record<
      string,
      unknown
    >
    const submittedMetadata =
      submission.metadata as Record<string, unknown>
    const submittedConfigMetadata = (
      submission.config as Record<string, unknown>
    ).metadata as Record<string, unknown>
    expect(submittedConfigMetadata.syshin_ui_submit_nonce).toBe(
      submittedMetadata.syshin_ui_submit_nonce
    )
    expect(submittedMetadata.syshin_ui_submit_nonce).not.toBe(
      "attacker-controlled"
    )
    expect(submittedConfigMetadata.syshin_ui_submit_nonce).not.toBe(
      "attacker-controlled"
    )
    expect(submission.config).toMatchObject({
      configurable: { mode: "hybrid" },
      metadata: {
        experiment: "rrf-v2",
        syshin_ui_submit_nonce: expect.any(String),
      },
    })
    expect(submission.metadata).toMatchObject({
      experiment: "rrf-v2",
      syshin_ui_submit_nonce: expect.any(String),
    })
  })

  test("redacts and cancels oversized or startless message events", async () => {
    const sentinel = `PRIVATE_OVERSIZE_${"x".repeat(300_000)}`
    const oversized = {
      type: "event",
      method: "custom",
      params: {
        namespace: [],
        timestamp: 1,
        data: { sentinel },
      },
    } as unknown as Event
    const startless = {
      type: "event",
      method: "messages",
      params: {
        namespace: [],
        timestamp: 2,
        data: {
          event: "message-error",
          error: "PRIVATE_STARTLESS_ERROR",
        },
      },
    } as unknown as Event

    for (const event of [oversized, startless]) {
      const observed: Error[] = []
      const fakeClient = makeClient([{ events: [event] }])
      const native = makeNative(fakeClient, {
        onError: (error) => observed.push(error),
      })
      await expect(
        collect(
          native.stream(
            [{ id: "human-1", type: "human", content: "경계" }],
            streamConfig()
          )
        )
      ).rejects.toThrow("에이전트 실행을 완료하지 못했습니다.")
      expect(cancellationRequests(authFor(native))).toHaveLength(1)
      expect(JSON.stringify(observed)).not.toContain("PRIVATE_")
      expect(observed[0]!.stack).toBeUndefined()
    }
  })

  test("bounds replay buffered before the dispatch barrier", async () => {
    const sentinel = `PRIVATE_PRE_BARRIER_${"가".repeat(80_000)}`
    const fakeClient = makeClient([
      {
        preDispatchEvents: Array.from({ length: 9 }, (_, index) =>
          customEvent(
            { sentinel, index },
            [`nested:${index}`]
          )
        ),
        events: [lifecycle("completed")],
      },
    ])
    const observed: Error[] = []
    const native = makeNative(fakeClient, {
      onError: (error) => observed.push(error),
    })

    await expect(
      collect(
        native.stream(
          [{ id: "human-1", type: "human", content: "재생 경계" }],
          streamConfig()
        )
      )
    ).rejects.toThrow("에이전트 실행을 완료하지 못했습니다.")
    expect(cancellationRequests(authFor(native))).toHaveLength(1)
    expect(JSON.stringify(observed)).not.toContain("PRIVATE_PRE_BARRIER")
  })

  test("fails immediately on a malformed nested watcher namespace", async () => {
    const malformed = {
      ...lifecycle("running"),
      params: {
        namespace: null,
        timestamp: 1,
        data: {
          event: "running",
          graph_name: "PRIVATE_MALFORMED_WATCHER",
        },
      },
    } as unknown as Event
    const observed: Error[] = []
    const fakeClient = makeClient([
      {
        watcherEvents: [malformed],
        events: [lifecycle("completed")],
      },
    ])
    const native = makeNative(fakeClient, {
      onError: (error) => observed.push(error),
    })

    await expect(
      collect(
        native.stream(
          [{ id: "human-1", type: "human", content: "watcher 경계" }],
          streamConfig()
        )
      )
    ).rejects.toThrow("에이전트 실행을 완료하지 못했습니다.")
    expect(cancellationRequests(authFor(native))).toHaveLength(1)
    expect(JSON.stringify(observed)).not.toContain("PRIVATE_MALFORMED")
  })

  test.each([
    {
      label: "delta without start",
      events: [
        messageEvent({ event: "message-start", role: "ai", id: "message-1" }),
        messageEvent({
          event: "content-block-delta",
          index: 0,
          delta: { type: "text-delta", text: "PRIVATE_DELTA" },
        }),
      ],
    },
    {
      label: "finish without start",
      events: [
        messageEvent({ event: "message-start", role: "ai", id: "message-1" }),
        messageEvent({
          event: "content-block-finish",
          index: 0,
          content: { type: "text", text: "PRIVATE_FINISH" },
        }),
      ],
    },
    {
      label: "duplicate start",
      events: [
        messageEvent({ event: "message-start", role: "ai", id: "message-1" }),
        messageEvent({
          event: "content-block-start",
          index: 0,
          content: { type: "text", text: "" },
        }),
        messageEvent({
          event: "content-block-start",
          index: 0,
          content: { type: "text", text: "PRIVATE_DUPLICATE" },
        }),
      ],
    },
    {
      label: "out-of-range index",
      events: [
        messageEvent({ event: "message-start", role: "ai", id: "message-1" }),
        messageEvent({
          event: "content-block-start",
          index: 256,
          content: { type: "text", text: "PRIVATE_INDEX" },
        }),
      ],
    },
    {
      label: "cumulative block overflow",
      events: [
        messageEvent({ event: "message-start", role: "ai", id: "message-1" }),
        messageEvent({
          event: "content-block-start",
          index: 0,
          content: { type: "text", text: "" },
        }),
        messageEvent({
          event: "content-block-delta",
          index: 0,
          delta: { type: "text-delta", text: "가".repeat(44_000) },
        }),
        messageEvent({
          event: "content-block-delta",
          index: 0,
          delta: {
            type: "text-delta",
            text: `PRIVATE_BLOCK_OVERFLOW_${"가".repeat(44_000)}`,
          },
        }),
      ],
    },
    {
      label: "finalized text overflow across blocks",
      events: [
        messageEvent({ event: "message-start", role: "ai", id: "message-1" }),
        ...[0, 1, 2].flatMap((index) => [
          messageEvent({
            event: "content-block-start",
            index,
            content: { type: "text", text: "" },
          }),
          messageEvent({
            event: "content-block-finish",
            index,
            content: {
              type: "text",
              text: `PRIVATE_FINAL_TEXT_${"가".repeat(60_000)}`,
            },
          }),
        ]),
      ],
    },
  ])("fails closed on $label content-block lifecycle", async ({ events }) => {
    const observed: Error[] = []
    const fakeClient = makeClient([{ events }])
    const native = makeNative(fakeClient, {
      onError: (error) => observed.push(error),
    })

    await expect(
      collect(
        native.stream(
          [{ id: "human-1", type: "human", content: "블록 경계" }],
          streamConfig()
        )
      )
    ).rejects.toThrow("에이전트 실행을 완료하지 못했습니다.")
    expect(cancellationRequests(authFor(native))).toHaveLength(1)
    expect(JSON.stringify(observed)).not.toContain("PRIVATE_")
  })
})

function sequenced(event: Event, seq: number, eventId: string): Event {
  return { ...event, seq, event_id: eventId } as Event
}

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

function messageEvent(
  data: Record<string, unknown>,
  namespace: string[] = []
): Event {
  return {
    type: "event",
    method: "messages",
    params: {
      namespace,
      timestamp: 1,
      data,
    },
  } as unknown as Event
}

function customEvent(
  data: Record<string, unknown>,
  namespace: string[] = []
): Event {
  return {
    type: "event",
    method: "custom",
    params: {
      namespace,
      timestamp: 1,
      data,
    },
  } as unknown as Event
}

interface FakeStreamPlan {
  events: readonly Event[]
  preDispatchEvents?: Event[]
  watcherEvents?: Event[]
  delayedWatcherEvents?: Event[]
  watcherDelayMs?: number
  onRespond?: (params: unknown) => unknown | Promise<unknown>
  startRun?: (params: unknown) => Promise<unknown>
  waitForClose?: (resolve: () => void) => void
  appliedThroughSeq?: number
  preserveSequence?: boolean
  streamError?: unknown
}

function isTestRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
}

function makeClient(
  plans: FakeStreamPlan[],
  options: {
    onListRuns?: () => unknown[]
  } = {}
): Client & {
  testing: {
    lastConfig?: Record<string, unknown>
    runStarts: number
    lastMetadata?: Record<string, unknown>
    responds: unknown[]
    submissions: unknown[]
    subscriptions: Array<{ channels: unknown; options: unknown }>
  }
} {
  const testing = {
    lastConfig: undefined as Record<string, unknown> | undefined,
    runStarts: 0,
    lastMetadata: undefined as Record<string, unknown> | undefined,
    responds: [] as unknown[],
    submissions: [] as unknown[],
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
        const ordering: {
          lastSeenSeq?: number
          lastAppliedThroughSeq?: number
          lastEventId?: string
        } = {}
        let nextSequence = 1
        const emit = (rawEvent: Event): Event => {
          const rawSequence = (rawEvent as Event & { seq?: number }).seq
          const sequence = plan.preserveSequence
            ? rawSequence
            : nextSequence++
          const rawEventId = (
            rawEvent as Event & { event_id?: string }
          ).event_id
          const eventId = plan.preserveSequence
            ? rawEventId
            : `fake-event-${sequence}`
          const event = {
            ...rawEvent,
            ...(sequence === undefined ? {} : { seq: sequence }),
            ...(eventId === undefined ? {} : { event_id: eventId }),
          } as Event
          if (sequence !== undefined) ordering.lastSeenSeq = sequence
          if (eventId !== undefined) ordering.lastEventId = eventId
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
          return event
        }
        let close: (() => void) | undefined
        const closed = new Promise<void>((resolve) => {
          close = resolve
          plan.waitForClose?.(resolve)
        })
        const subscription = {
          unsubscribe: async () => undefined,
          async *[Symbol.asyncIterator]() {
            for (const rawEvent of plan.events) {
              const event = emit(rawEvent)
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
              if (
                event.params.namespace.length === 0 &&
                (event.method === "messages" ||
                  event.method === "lifecycle" ||
                  event.method === "input.requested" ||
                  event.method === "tools" ||
                  event.method === "custom")
              ) {
                yield event
              }
            }
            if (plan.streamError !== undefined) throw plan.streamError
            if (plan.waitForClose) await closed
          },
        }
        return {
          ordering,
          submitRun: async (params: unknown) => {
            testing.runStarts += 1
            testing.submissions.push(params)
            testing.lastMetadata = isTestRecord(params) &&
              isTestRecord(params.metadata)
              ? params.metadata
              : undefined
            testing.lastConfig = isTestRecord(params) &&
              isTestRecord(params.config)
              ? params.config
              : undefined
            ordering.lastAppliedThroughSeq =
              plan.appliedThroughSeq ?? 0
            for (const event of plan.watcherEvents ?? []) emit(event)
            if (plan.startRun) return await plan.startRun(params)
            return { run_id: `run-${testing.runStarts}` }
          },
          respondInput: async (params: unknown) => {
            testing.responds.push(params)
            testing.lastMetadata = isTestRecord(params) &&
              isTestRecord(params.metadata)
              ? params.metadata
              : undefined
            testing.lastConfig = isTestRecord(params) &&
              isTestRecord(params.config)
              ? params.config
              : undefined
            ordering.lastAppliedThroughSeq =
              plan.appliedThroughSeq ?? 0
            for (const event of plan.watcherEvents ?? []) emit(event)
            await plan.onRespond?.(params)
          },
          interrupts,
          run: {
            start: async () => {
              testing.runStarts += 1
              if (plan.startRun) return await plan.startRun(undefined)
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
            for (const event of plan.preDispatchEvents ?? []) emit(event)
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
      lastConfig?: Record<string, unknown>
      runStarts: number
      lastMetadata?: Record<string, unknown>
      responds: unknown[]
      submissions: unknown[]
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
  runConfig?: () => Record<string, unknown> | undefined
  token: string
  runMetadata?: () => Record<string, unknown> | undefined
}

const nativeAuthHarnesses = new WeakMap<NativeAgentClient, AuthHarness>()

function jwtToken(exp: number, subject: string): string {
  const encode = (value: object) =>
    Buffer.from(JSON.stringify(value)).toString("base64url")
  return `${encode({ alg: "HS256", typ: "JWT" })}.${encode({
    exp,
    sub: subject,
    iss: "syshin0116.dev",
    aud: "agent-api",
    iat: 900,
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
    runListFactory?: (
      metadata: Record<string, unknown> | undefined,
      call: number
    ) => unknown[]
    runLists?: unknown[][]
  } = {}
): AuthHarness {
  const harness: AuthHarness = {
    broker: undefined as unknown as AgentTokenBroker,
    mintCalls: 0,
    requests: [] as AuthRequest[],
    runListCalls: 0,
    token: jwtToken(2_000, identity),
  }
  harness.broker = new AgentTokenBroker(identity, {
    agentOrigin: "https://agent.example",
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
        const metadata = harness.runMetadata?.()
        const config = harness.runConfig?.()
        const pathParts = parsedUrl.pathname.split("/")
        const listedThreadId = decodeURIComponent(pathParts[2] ?? "")
        const defaultRuns =
          metadata &&
          typeof metadata.syshin_ui_submit_nonce === "string"
            ? [
                {
                  run_id: `run-${metadata.syshin_ui_submit_nonce}`,
                  status: "running",
                  thread_id: listedThreadId,
                  config,
                  metadata,
                },
              ]
            : []
        const factoryRuns = options.runListFactory?.(
          metadata,
          harness.runListCalls
        )
        const runLists = options.runLists
        const index = runLists
          ? Math.min(harness.runListCalls, runLists.length - 1)
          : 0
        harness.runListCalls += 1
        const runs = (
          factoryRuns ??
          runLists?.[index] ??
          defaultRuns
        ).map((run) => {
          if (!isTestRecord(run)) return run
          return {
            ...run,
            ...(typeof run.thread_id === "string"
              ? {}
              : { thread_id: listedThreadId }),
          }
        })
        return new Response(JSON.stringify(runs), {
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
  const fakeTesting = (
    client as Client & {
      testing?: {
        lastConfig?: Record<string, unknown>
        lastMetadata?: Record<string, unknown>
      }
    }
  ).testing
  auth.runMetadata = () => fakeTesting?.lastMetadata
  auth.runConfig = () => fakeTesting?.lastConfig
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
    await new Promise((resolve) => setTimeout(resolve, 1))
  }
  throw new Error("Condition was not reached")
}
