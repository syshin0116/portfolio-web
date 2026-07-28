type JsonRecord = Record<string, unknown>

interface ThreadRow {
  thread_id: string
  metadata: JsonRecord
  created_at: string
  updated_at: string
  state_updated_at: string
  status: "idle" | "busy" | "interrupted"
  messages: JsonRecord[]
}

interface RunRow {
  run_id: string
  thread_id: string
  status:
    | "pending"
    | "running"
    | "error"
    | "success"
    | "timeout"
    | "interrupted"
  metadata: JsonRecord
}

interface Subscriber {
  body: JsonRecord
  controller: ReadableStreamDefaultController<Uint8Array>
  closed: boolean
  id: number
  threadId: string
}

interface FixtureState {
  cancellations: Array<{ runId: string; threadId: string }>
  commands: JsonRecord[]
  errors: string[]
  nextRun: number
  nextSequence: number
  nextSubscriber: number
  renameAttempts: number
  reconnectDisconnects: number
  responses: JsonRecord[]
  scenario:
    | "cancel-auth-failure"
    | "default"
    | "delayed-replay"
    | "load-error"
    | "reconnect"
    | "stale-source"
  staleSourceDeliveries: number
  streamSubscriptions: Array<{
    authorization: boolean
    body: JsonRecord
    threadId: string
  }>
  subscribers: Map<number, Subscriber>
  threads: Map<string, ThreadRow>
  runs: Map<string, RunRow[]>
}

const encoder = new TextEncoder()
const browserOrigin = "http://127.0.0.1:3128"
const corsHeaders = {
  "access-control-allow-headers": "authorization, content-type, prefer",
  "access-control-allow-methods": "GET, POST, PATCH, OPTIONS",
  "access-control-allow-origin": browserOrigin,
  "access-control-expose-headers": "content-location",
}

function fixtureThread(): ThreadRow {
  const now = new Date().toISOString()
  return {
    thread_id: "browser-thread-1",
    metadata: {
      archived: false,
      graph_id: "agent",
      title: "브라우저 테스트 대화",
      title_status: "manual",
    },
    created_at: now,
    updated_at: now,
    state_updated_at: now,
    status: "idle",
    messages: [],
  }
}

function resetState(
  scenario: FixtureState["scenario"] = "default"
): FixtureState {
  const thread = fixtureThread()
  return {
    cancellations: [],
    commands: [],
    errors: [],
    nextRun: 1,
    nextSequence: 1,
    nextSubscriber: 1,
    renameAttempts: 0,
    reconnectDisconnects: 0,
    responses: [],
    scenario,
    staleSourceDeliveries: 0,
    streamSubscriptions: [],
    subscribers: new Map(),
    threads: new Map([[thread.thread_id, thread]]),
    runs: new Map([[thread.thread_id, []]]),
  }
}

let state = resetState()

function responseJson(body: unknown, status = 200): Response {
  return Response.json(body, {
    status,
    headers: corsHeaders,
  })
}

function emptyResponse(status = 204): Response {
  return new Response(null, {
    status,
    headers: corsHeaders,
  })
}

function channelFor(event: JsonRecord): string | undefined {
  if (event.method === "input.requested") return "input"
  return typeof event.method === "string" ? event.method : undefined
}

function namespaceFor(event: JsonRecord): string[] {
  const params = event.params
  if (
    params &&
    typeof params === "object" &&
    !Array.isArray(params) &&
    Array.isArray((params as JsonRecord).namespace)
  ) {
    return (params as JsonRecord).namespace as string[]
  }
  return []
}

function subscriberMatches(
  subscriber: Subscriber,
  event: JsonRecord
): boolean {
  const channels = subscriber.body.channels
  const channel = channelFor(event)
  if (!Array.isArray(channels) || !channel || !channels.includes(channel)) {
    return false
  }
  const namespaces = subscriber.body.namespaces
  if (namespaces === undefined) return true
  if (
    !Array.isArray(namespaces) ||
    namespaces.length !== 1 ||
    !Array.isArray(namespaces[0])
  ) {
    return false
  }
  const prefix = namespaces[0] as string[]
  const namespace = namespaceFor(event)
  if (
    prefix.length > namespace.length ||
    prefix.some((part, index) => namespace[index] !== part)
  ) {
    return false
  }
  const depth =
    typeof subscriber.body.depth === "number"
      ? subscriber.body.depth
      : undefined
  return depth === undefined || namespace.length - prefix.length <= depth
}

function writeEvent(
  subscriber: Subscriber,
  event: JsonRecord
): boolean {
  if (subscriber.closed) return false
  try {
    subscriber.controller.enqueue(
      encoder.encode(`data: ${JSON.stringify(event)}\n\n`)
    )
    return true
  } catch {
    subscriber.closed = true
    state.subscribers.delete(subscriber.id)
    return false
  }
}

function emit(
  threadId: string,
  event: JsonRecord,
  audience: "all" | "content" | "watcher" = "all"
): number {
  let deliveries = 0
  for (const subscriber of state.subscribers.values()) {
    if (
      subscriber.threadId !== threadId ||
      !subscriberMatches(subscriber, event)
    ) {
      continue
    }
    const isWatcher =
      Array.isArray(subscriber.body.channels) &&
      subscriber.body.channels.length === 2 &&
      subscriber.body.channels[0] === "lifecycle" &&
      subscriber.body.channels[1] === "input" &&
      subscriber.body.namespaces === undefined &&
      subscriber.body.depth === undefined
    if (
      (audience === "watcher" && !isWatcher) ||
      (audience === "content" && isWatcher)
    ) {
      continue
    }
    if (writeEvent(subscriber, event)) deliveries += 1
  }
  return deliveries
}

function protocolEvent(
  method: string,
  namespace: string[],
  data: JsonRecord,
  sequence = state.nextSequence++,
  runId?: string
): JsonRecord {
  const rootRunning =
    runId !== undefined &&
    method === "lifecycle" &&
    namespace.length === 0 &&
    data.event === "running"
  return {
    type: "event",
    event_id:
      runId === undefined
        ? `browser-event-${sequence}`
        : rootRunning
          ? `${runId}:running:0`
          : `${runId}_event_${sequence}:0`,
    seq: sequence,
    method,
    params: {
      namespace,
      timestamp: Date.now(),
      data,
    },
  }
}

async function waitForStreams(threadId: string): Promise<void> {
  for (let attempt = 0; attempt < 2_000; attempt += 1) {
    const streams = [...state.subscribers.values()].filter(
      (subscriber) => subscriber.threadId === threadId
    )
    if (streams.length >= 2) return
    await Bun.sleep(5)
  }
  throw new Error("browser fixture streams were not opened")
}

function messageEvents(
  runId: string,
  text = "브라우저 fixture 응답이 완료되었습니다.",
  messageId = `browser-answer-${state.nextSequence}`
): JsonRecord[] {
  return [
    protocolEvent("messages", [], {
      event: "message-start",
      role: "ai",
      id: messageId,
    }, undefined, runId),
    protocolEvent("messages", [], {
      event: "content-block-start",
      index: 0,
      content: { type: "text", text: "" },
    }, undefined, runId),
    protocolEvent("messages", [], {
      event: "content-block-delta",
      index: 0,
      delta: {
        type: "text-delta",
        text,
      },
    }, undefined, runId),
    protocolEvent("messages", [], {
      event: "content-block-finish",
      index: 0,
      content: {
        type: "text",
        text,
      },
    }, undefined, runId),
    protocolEvent("messages", [], {
      event: "message-finish",
    }, undefined, runId),
  ]
}

async function emitDelayedReplayThenInitial(
  threadId: string,
  run: RunRow
): Promise<void> {
  const staleRunId = "browser-stale-run"
  await waitForStreams(threadId)
  await Bun.sleep(300)
  emit(
    threadId,
    protocolEvent(
      "lifecycle",
      [],
      { event: "running", graph_name: "agent" },
      undefined,
      staleRunId
    )
  )
  for (const event of messageEvents(
    staleRunId,
    "STALE_BROWSER_HISTORY_MUST_NOT_RENDER",
    "stale-browser-answer"
  )) {
    emit(threadId, event)
  }
  emit(
    threadId,
    protocolEvent(
      "lifecycle",
      [],
      { event: "completed", graph_name: "agent" },
      undefined,
      staleRunId
    )
  )
  await Bun.sleep(50)
  await emitInitialRun(threadId, run)
}

async function emitStaleSourceFailure(
  threadId: string,
  run: RunRow
): Promise<void> {
  await waitForStreams(threadId)
  emit(
    threadId,
    protocolEvent(
      "lifecycle",
      [],
      { event: "running", graph_name: "agent" },
      undefined,
      run.run_id
    )
  )
  await Bun.sleep(80)
  state.staleSourceDeliveries += emit(
    threadId,
    protocolEvent(
      "lifecycle",
      ["nested_subgraph:stale-source"],
      { event: "running", graph_name: "nested" },
      undefined,
      run.run_id
    ),
    "watcher"
  )
  state.staleSourceDeliveries += emit(
    threadId,
    protocolEvent(
      "lifecycle",
      [],
      {
        event: "failed",
        graph_name: "agent",
        error: "PRIVATE_STALE_SOURCE_ERROR",
      },
      undefined,
      run.run_id
    )
  )
  run.status = "error"
}

async function emitInitialRun(threadId: string, run: RunRow): Promise<void> {
  await waitForStreams(threadId)
  emit(
    threadId,
    protocolEvent("lifecycle", [], {
      event: "running",
      graph_name: "agent",
    }, undefined, run.run_id)
  )
  emit(
    threadId,
    protocolEvent("lifecycle", ["nested_subgraph:browser-task"], {
      event: "running",
      graph_name: "nested",
    }, undefined, run.run_id),
    "watcher"
  )
  const nestedInput = protocolEvent(
    "input.requested",
    ["nested_subgraph:browser-task"],
    {
      interrupt_id: "browser-interrupt-1",
      payload: {
        schema: "syshin.rag.interrupt.v1",
        kind: "approval",
        title: "브라우저 검색 승인",
        prompt: "브라우저 fixture 검색을 계속할까요?",
        input_hint: "수정할 내용을 입력해 재개",
      },
    },
    undefined,
    run.run_id
  )
  const rootInterrupted = protocolEvent(
    "lifecycle",
    [],
    {
      event: "interrupted",
      graph_name: "agent",
    },
    undefined,
    run.run_id
  )
  // Deliberately deliver the terminal over the root content SSE before the
  // earlier nested input reaches the independent SDK watcher SSE.
  emit(threadId, rootInterrupted, "content")
  await Bun.sleep(40)
  emit(threadId, nestedInput, "watcher")
  emit(
    threadId,
    protocolEvent("lifecycle", ["nested_subgraph:browser-task"], {
      event: "interrupted",
      graph_name: "nested",
    }, undefined, run.run_id),
    "watcher"
  )
  emit(threadId, rootInterrupted, "watcher")
  run.status = "interrupted"
  const thread = state.threads.get(threadId)
  if (thread) thread.status = "interrupted"
}

async function emitCompletedRun(
  threadId: string,
  run: RunRow
): Promise<void> {
  await waitForStreams(threadId)
  emit(
    threadId,
    protocolEvent("lifecycle", [], {
      event: "running",
      graph_name: "agent",
    }, undefined, run.run_id)
  )
  emit(
    threadId,
    protocolEvent("lifecycle", ["nested_subgraph:browser-task"], {
      event: "running",
      graph_name: "nested",
    }, undefined, run.run_id),
    "watcher"
  )
  for (const event of messageEvents(run.run_id)) emit(threadId, event)
  emit(
    threadId,
    protocolEvent("lifecycle", ["nested_subgraph:browser-task"], {
      event: "completed",
      graph_name: "nested",
    }, undefined, run.run_id),
    "watcher"
  )
  emit(
    threadId,
    protocolEvent("lifecycle", [], {
      event: "completed",
      graph_name: "agent",
    }, undefined, run.run_id)
  )
  run.status = "success"
  const thread = state.threads.get(threadId)
  if (thread) {
    thread.status = "idle"
    thread.messages = [
      {
        id: "browser-persisted-answer",
        role: "assistant",
        content: [
          {
            type: "text",
            text: "브라우저 fixture 응답이 완료되었습니다.",
          },
        ],
      },
    ]
  }
}

function newRun(threadId: string, metadata: JsonRecord): RunRow {
  const run: RunRow = {
    run_id: `browser-run-${state.nextRun++}`,
    thread_id: threadId,
    status: "running",
    metadata,
  }
  const runs = state.runs.get(threadId) ?? []
  runs.push(run)
  state.runs.set(threadId, runs)
  const thread = state.threads.get(threadId)
  if (thread) thread.status = "busy"
  return run
}

function threadState(threadId: string): JsonRecord {
  const thread = state.threads.get(threadId)
  return {
    values: { messages: thread?.messages ?? [] },
    next: [],
    checkpoint: {
      thread_id: threadId,
      checkpoint_ns: "",
      checkpoint_id: "browser-checkpoint-1",
      checkpoint_map: null,
    },
    metadata: {},
    created_at: new Date().toISOString(),
    parent_checkpoint: null,
    tasks: [],
    interrupts: [],
  }
}

async function jsonBody(request: Request): Promise<JsonRecord> {
  const value = (await request.json()) as unknown
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as JsonRecord)
    : {}
}

function publicState(): JsonRecord {
  return {
    cancellations: state.cancellations,
    commands: state.commands,
    errors: state.errors,
    renameAttempts: state.renameAttempts,
    reconnectDisconnects: state.reconnectDisconnects,
    responses: state.responses,
    revision: process.env.GITHUB_SHA ?? "local",
    scenario: state.scenario,
    staleSourceDeliveries: state.staleSourceDeliveries,
    streamSubscriptions: state.streamSubscriptions,
  }
}

const server = Bun.serve({
  hostname: "127.0.0.1",
  idleTimeout: 0,
  port: 3130,
  async fetch(request) {
    const url = new URL(request.url)
    if (request.method === "OPTIONS") return emptyResponse()
    if (url.pathname === "/__fixture/state" && request.method === "GET") {
      return responseJson(publicState())
    }
    if (url.pathname === "/__fixture/reset" && request.method === "POST") {
      const body = await jsonBody(request)
      state = resetState(
        body.scenario === "cancel-auth-failure" ||
          body.scenario === "delayed-replay" ||
          body.scenario === "load-error" ||
          body.scenario === "reconnect" ||
          body.scenario === "stale-source"
          ? body.scenario
          : "default"
      )
      return responseJson(publicState())
    }
    if (url.pathname === "/threads/search" && request.method === "POST") {
      return responseJson([...state.threads.values()])
    }
    if (url.pathname === "/threads" && request.method === "POST") {
      const body = await jsonBody(request)
      const threadId =
        typeof body.thread_id === "string"
          ? body.thread_id
          : `browser-thread-${state.threads.size + 1}`
      const now = new Date().toISOString()
      const row: ThreadRow = {
        thread_id: threadId,
        metadata:
          body.metadata &&
          typeof body.metadata === "object" &&
          !Array.isArray(body.metadata)
            ? (body.metadata as JsonRecord)
            : {},
        created_at: now,
        updated_at: now,
        state_updated_at: now,
        status: "idle",
        messages: [],
      }
      state.threads.set(threadId, row)
      state.runs.set(threadId, [])
      return responseJson(row)
    }

    const streamMatch =
      /^\/threads\/([^/]+)\/stream\/events$/.exec(url.pathname)
    if (streamMatch && request.method === "POST") {
      const threadId = streamMatch[1]!
      const body = await jsonBody(request)
      state.streamSubscriptions.push({
        authorization: request.headers
          .get("authorization")
          ?.startsWith("Bearer ") === true,
        body,
        threadId,
      })
      if (
        state.scenario === "reconnect" &&
        state.reconnectDisconnects === 0 &&
        Array.isArray(body.namespaces)
      ) {
        state.reconnectDisconnects += 1
        return responseJson({ error: "temporary stream failure" }, 503)
      }
      const id = state.nextSubscriber++
      let subscriber: Subscriber
      const stream = new ReadableStream<Uint8Array>({
        start(controller) {
          subscriber = {
            body,
            controller,
            closed: false,
            id,
            threadId,
          }
          state.subscribers.set(id, subscriber)
          controller.enqueue(encoder.encode(": ready\n\n"))
          request.signal.addEventListener(
            "abort",
            () => {
              subscriber.closed = true
              state.subscribers.delete(id)
              try {
                controller.close()
              } catch {
                // The browser may already have closed the response body.
              }
            },
            { once: true }
          )
        },
        cancel() {
          const current = state.subscribers.get(id)
          if (current) current.closed = true
          state.subscribers.delete(id)
        },
      })
      return new Response(stream, {
        headers: {
          ...corsHeaders,
          "cache-control": "no-cache, no-transform",
          connection: "keep-alive",
          "content-type": "text/event-stream",
        },
      })
    }

    const commandsMatch =
      /^\/threads\/([^/]+)\/commands$/.exec(url.pathname)
    if (commandsMatch && request.method === "POST") {
      const threadId = commandsMatch[1]!
      const command = await jsonBody(request)
      state.commands.push(command)
      const params =
        command.params &&
        typeof command.params === "object" &&
        !Array.isArray(command.params)
          ? (command.params as JsonRecord)
          : {}
      if (command.method === "run.start") {
        const metadata =
          params.metadata &&
          typeof params.metadata === "object" &&
          !Array.isArray(params.metadata)
            ? (params.metadata as JsonRecord)
            : {}
        const run = newRun(threadId, metadata)
        const serialized = JSON.stringify(params.input ?? "")
        if (state.scenario === "delayed-replay") {
          void emitDelayedReplayThenInitial(threadId, run).catch(
            (error: unknown) => {
              state.errors.push(
                error instanceof Error
                  ? error.message
                  : "delayed replay emit failed"
              )
            }
          )
        } else if (state.scenario === "stale-source") {
          void emitStaleSourceFailure(threadId, run).catch(
            (error: unknown) => {
              state.errors.push(
                error instanceof Error
                  ? error.message
                  : "stale source emit failed"
              )
            }
          )
        } else if (serialized.includes("취소")) {
          void waitForStreams(threadId)
            .then(() => {
              emit(
                threadId,
                protocolEvent("lifecycle", [], {
                  event: "running",
                  graph_name: "agent",
                }, undefined, run.run_id)
              )
            })
            .catch((error: unknown) => {
              state.errors.push(
                error instanceof Error ? error.message : "stream wait failed"
              )
            })
        } else {
          void emitInitialRun(threadId, run).catch((error: unknown) => {
            state.errors.push(
              error instanceof Error ? error.message : "initial emit failed"
            )
          })
        }
        return responseJson({
          type: "success",
          id: command.id,
          result: { run_id: run.run_id },
          meta: { applied_through_seq: state.nextSequence - 1 },
        })
      }
      if (command.method === "input.respond") {
        state.responses.push(params)
        if (state.responses.length === 1) {
          return responseJson(
            {
              type: "error",
              id: command.id,
              error: "unknown_error",
              message:
                "postgres://owner:fixture-secret@db.internal input.respond failed",
            },
            200
          )
        }
        const metadata =
          params.metadata &&
          typeof params.metadata === "object" &&
          !Array.isArray(params.metadata)
            ? (params.metadata as JsonRecord)
            : {}
        const run = newRun(threadId, metadata)
        void emitCompletedRun(threadId, run).catch((error: unknown) => {
          state.errors.push(
            error instanceof Error ? error.message : "resume emit failed"
          )
        })
        return responseJson({
          type: "success",
          id: command.id,
          result: { run_id: run.run_id },
          meta: { applied_through_seq: state.nextSequence - 1 },
        })
      }
      return responseJson(
        {
          type: "error",
          id: command.id,
          error: { message: "unsupported fixture command" },
        },
        400
      )
    }

    const stateMatch = /^\/threads\/([^/]+)\/state$/.exec(url.pathname)
    if (stateMatch && request.method === "GET") {
      if (state.scenario === "load-error") {
        return new Response('{"fixture_secret":', {
          status: 200,
          headers: {
            ...corsHeaders,
            "content-type": "application/json",
          },
        })
      }
      return responseJson(threadState(stateMatch[1]!))
    }
    const historyMatch =
      /^\/threads\/([^/]+)\/history$/.exec(url.pathname)
    if (historyMatch && request.method === "POST") return responseJson([])

    const cancelMatch =
      /^\/threads\/([^/]+)\/runs\/([^/]+)\/cancel$/.exec(url.pathname)
    if (cancelMatch && request.method === "POST") {
      const [, threadId, runId] = cancelMatch
      state.cancellations.push({ threadId: threadId!, runId: runId! })
      if (state.scenario === "cancel-auth-failure") {
        return responseJson(
          { error: "PRIVATE_CANCEL_AUTH_BODY_MUST_NOT_RENDER" },
          401
        )
      }
      const run = (state.runs.get(threadId!) ?? []).find(
        (candidate) => candidate.run_id === runId
      )
      if (run) run.status = "interrupted"
      return emptyResponse()
    }
    const runMatch =
      /^\/threads\/([^/]+)\/runs\/([^/]+)$/.exec(url.pathname)
    if (runMatch && request.method === "GET") {
      const run = (state.runs.get(runMatch[1]!) ?? []).find(
        (candidate) => candidate.run_id === runMatch[2]
      )
      return run
        ? responseJson(run)
        : responseJson({ error: "run not found" }, 404)
    }
    const runsMatch = /^\/threads\/([^/]+)\/runs$/.exec(url.pathname)
    if (runsMatch && request.method === "GET") {
      return responseJson(state.runs.get(runsMatch[1]!) ?? [])
    }

    const threadMatch = /^\/threads\/([^/]+)$/.exec(url.pathname)
    if (threadMatch && request.method === "GET") {
      const thread = state.threads.get(threadMatch[1]!)
      return thread
        ? responseJson(thread)
        : responseJson({ error: "thread not found" }, 404)
    }
    if (threadMatch && request.method === "PATCH") {
      const thread = state.threads.get(threadMatch[1]!)
      if (!thread) return responseJson({ error: "thread not found" }, 404)
      const body = await jsonBody(request)
      const metadata =
        body.metadata &&
        typeof body.metadata === "object" &&
        !Array.isArray(body.metadata)
          ? (body.metadata as JsonRecord)
          : {}
      if (metadata.title_status === "manual") {
        state.renameAttempts += 1
        if (state.renameAttempts === 1) {
          return new Response('{"fixture_secret":', {
            status: 200,
            headers: {
              ...corsHeaders,
              "content-type": "application/json",
            },
          })
        }
      }
      thread.metadata = { ...thread.metadata, ...metadata }
      thread.updated_at = new Date().toISOString()
      return request.headers.get("prefer") === "return=minimal"
        ? emptyResponse()
        : responseJson(thread)
    }

    return responseJson({ error: "fixture route not found" }, 404)
  },
})

console.log(`APv2 browser fixture listening on ${server.url}`)
