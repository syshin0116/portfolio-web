import { describe, expect, test } from "bun:test"

const read = async (path: string) =>
  await Bun.file(new URL(path, import.meta.url)).text()

describe("native assistant-ui architecture contract", () => {
  test("keeps the reviewed dependency pins and one SDK resolution", async () => {
    const packageJson = JSON.parse(
      await read("../../../package.json")
    ) as {
      dependencies: Record<string, string>
    }
    expect(packageJson.dependencies).toMatchObject({
      "@assistant-ui/react": "0.15.0",
      "@assistant-ui/react-langgraph": "0.14.15",
      "@langchain/core": "1.2.3",
      "@langchain/langgraph-sdk": "1.9.28",
      "@langchain/protocol": "0.0.18",
    })
    expect(packageJson.dependencies["@langchain/react"]).toBeUndefined()
    expect(packageJson.dependencies["@langchain/langgraph"]).toBeUndefined()

    const lock = await read("../../../bun.lock")
    const sdkResolutions =
      lock.match(
        /"@langchain\/langgraph-sdk": \["@langchain\/langgraph-sdk@1\.9\.28"/g
      ) ?? []
    expect(sdkResolutions).toHaveLength(1)
  })

  test("uses native runtime, APv2 stream, assembler, HITL, and cancellation APIs", async () => {
    const [provider, nativeClient] = await Promise.all([
      read("../agent-runtime-provider.tsx"),
      read("./native-client.ts"),
    ])

    expect(provider).toContain("useLangGraphRuntime({")
    expect(provider).toContain("<AssistantRuntimeProvider runtime={runtime}>")
    expect(provider).toContain("unstable_threadListAdapter: threadAdapter")
    const chatShell = await read("../chat-shell.tsx")
    expect(chatShell).toContain("useAuiState(")
    expect(chatShell).toContain("aui.threadListItem().rename")
    expect(chatShell).not.toMatch(
      /\buse(?:Message|ThreadListItem|ThreadListItemRuntime)\b/
    )
    expect(nativeClient).toContain(
      "this.client.threads.stream(boundThreadId"
    )
    expect(nativeClient).toContain("new MessageAssembler()")
    expect(nativeClient).toContain("thread.submitRun({")
    expect(nativeClient).toContain("thread.respondInput({")
    expect(nativeClient).toContain("client.runs.cancel(threadId, runId")
    expect(nativeClient.match(/thread\.subscribe\(/g) ?? []).toHaveLength(1)

    const subscriptionStart = nativeClient.indexOf(
      "subscription = await thread.subscribe("
    )
    const subscriptionEnd = nativeClient.indexOf(
      "\n      )",
      subscriptionStart
    )
    expect(subscriptionStart).toBeGreaterThanOrEqual(0)
    expect(subscriptionEnd).toBeGreaterThan(subscriptionStart)
    const subscription = nativeClient.slice(
      subscriptionStart,
      subscriptionEnd + "\n      )".length
    )
    expect(subscription).toContain('"messages"')
    expect(subscription).toContain('"lifecycle"')
    expect(subscription).toContain('"input"')
    expect(subscription).toContain('"tools"')
    expect(subscription).toContain('"custom"')
    expect(subscription).toContain("namespaces: [[]]")
    expect(subscription).toContain("depth: 0")
    expect(subscription).not.toContain('"values"')
    expect(subscription).not.toContain('"updates"')

    const production = `${provider}\n${nativeClient}`
    for (const forbidden of [
      "runs.stream(",
      "unstable_createLangGraphStream",
      "joinStream",
      "EventSource",
      "/api/chat",
      "defaultHeaders",
    ]) {
      expect(production).not.toContain(forbidden)
    }
  })

  test("does not expose unsafe edit, fork, regenerate, or delete controls", async () => {
    const [provider, shell, threadAdapter] = await Promise.all([
      read("../agent-runtime-provider.tsx"),
      read("../chat-shell.tsx"),
      read("./thread-adapter.ts"),
    ])

    expect(provider).not.toContain("getCheckpointId")
    for (const primitive of [
      "MessagePrimitive.Edit",
      "MessagePrimitive.Reload",
      "BranchPickerPrimitive",
      "ThreadListItemPrimitive.Delete",
    ]) {
      expect(shell).not.toContain(primitive)
    }
    const production = `${provider}\n${shell}\n${threadAdapter}`
    expect(production).not.toContain("allowSafeDelete")
    expect(production).not.toContain("threads.delete")
    expect(shell).toContain("현재 서버는 대화 삭제를 지원하지 않습니다.")
  })

  test("removed the legacy transport and prompt-kit entrypoints", async () => {
    const removed = [
      "./agent-protocol-v2.ts",
      "./auth.ts",
      "./protocol-types.ts",
      "./sse.ts",
      "../../chat-section.tsx",
      "../../../lib/api-client.ts",
    ]
    for (const path of removed) {
      expect(await Bun.file(new URL(path, import.meta.url)).exists()).toBe(false)
    }
  })

  test("keeps inspection, recovery, responsive, and motion boundaries explicit", async () => {
    const [provider, shell, nativeClient, inspection, ime, sheet] =
      await Promise.all([
        read("../agent-runtime-provider.tsx"),
        read("../chat-shell.tsx"),
        read("./native-client.ts"),
        read("./inspection.ts"),
        read("./ime.ts"),
        read("../../ui/sheet.tsx"),
      ])

    expect(nativeClient).toContain('"custom"')
    expect(nativeClient).not.toContain('"apv2:tool"')
    expect(inspection).toContain(
      'INSPECTION_EVENT_NAME = "syshin.rag.inspection.v1"'
    )
    expect(inspection).toContain(
      "data.name !== INSPECTION_EVENT_NAME"
    )
    expect(shell).toContain("검색 방법")
    expect(shell).toContain("코퍼스 리비전")
    expect(shell).toContain("실시간 실행 중에만")
    expect(shell).toContain("이전 실행의 검사 정보")
    expect(shell).not.toContain("QuickJS")
    expect(shell).not.toContain("서브에이전트 목적")
    expect(shell).toContain("근거 수")
    expect(shell).toContain("MARKDOWN_COMPONENTS")
    expect(shell).toContain("md:flex xl:hidden")
    expect(shell).toContain('aria-label="실행 상세 열기"')
    expect(shell).not.toContain("window.location.reload")
    expect(shell).not.toContain("min-h-[640px]")
    expect(shell).toContain("100svh")
    expect(shell).toContain("100dvh")
    expect(shell).toContain("compositionRef")
    expect(ime).toContain("isComposing")
    expect(provider).toContain("turnError")
    expect(provider).toContain("connectionStatus")
    expect(`${shell}\n${sheet}`).toContain("motion-reduce:")
  })

  test("projects opaque HITL values through the bounded UI schema only", async () => {
    const [shell, projector, nativeClient] = await Promise.all([
      read("../chat-shell.tsx"),
      read("./interrupt-projection.ts"),
      read("./native-client.ts"),
    ])

    expect(shell).toContain("readRuntimeInterruptProjection(interrupt.value)")
    expect(shell.match(/interrupt\.value/g) ?? []).toHaveLength(1)
    expect(shell).not.toContain("JSON.stringify(interrupt")
    expect(shell).not.toContain("{interrupt.value}")
    expect(shell).not.toContain("interrupt.ns")
    expect(projector).toContain(
      'INTERRUPT_UI_SCHEMA = "syshin.rag.interrupt.v1"'
    )
    expect(projector).toContain("GENERIC_INTERRUPT_PROJECTION")
    expect(nativeClient).toContain(
      "value: projectInterruptForUi(data.payload ?? data.value)"
    )
    expect(nativeClient).toContain(
      "value: projectInterruptForUi(value.payload)"
    )
    expect(nativeClient).toContain("value: pending.value")
    expect(nativeClient).not.toContain("...values")
  })
})
