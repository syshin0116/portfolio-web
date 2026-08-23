"use client"

import {
  ActionBarPrimitive,
  AuiIf,
  ComposerPrimitive,
  ErrorPrimitive,
  MessagePrimitive,
  ThreadListItemPrimitive,
  ThreadListPrimitive,
  ThreadPrimitive,
  type ReasoningMessagePartProps,
  type ToolCallMessagePartProps,
  useAui,
  useAuiState,
} from "@assistant-ui/react"
import {
  useLangGraphInterruptState,
  useLangGraphSendCommand,
} from "@assistant-ui/react-langgraph"
import {
  Archive,
  ArrowDown,
  ArrowUp,
  BrainCircuit,
  Check,
  ChevronRight,
  CircleStop,
  Clock3,
  Copy,
  History,
  ListTree,
  LoaderCircle,
  Menu,
  Pencil,
  Plus,
  RotateCcw,
  ToolCase,
  UserRound,
  WifiOff,
} from "lucide-react"
import Image from "next/image"
import Link from "next/link"
import {
  memo,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react"

import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { isAgentModel, type AgentModel } from "@/lib/agent-model"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet"
import { cn } from "@/lib/utils"

import {
  toolArgumentSummary,
  toolResultText,
} from "./runtime/tool-arguments"

import { useAgentRuntimeUi } from "./agent-runtime-provider"
import { MarkdownText } from "./markdown-text"
import {
  inspectionSourcesFromUnknown,
  safeSourceUrl,
  type AgentActivity,
  type InspectionSource,
} from "./runtime/inspection"
import {
  readRuntimeInterruptProjection,
  type InterruptUiProjection,
} from "./runtime/interrupt-projection"
import { createImeEnterGuard } from "./runtime/ime"
import {
  COMPOSER_ACCESSIBLE_NAME,
  restoreComposerFocus,
} from "./runtime/focus-restoration"

const SUGGESTIONS = [
  { prompt: "LangGraph 관련 글을 찾아줘" },
  { prompt: "최근 AI 프로젝트를 요약해줘" },
  { prompt: "RAG 평가 계획을 설명해줘" },
] as const

const ReasoningPart = memo(function ReasoningPart({
  status,
}: ReasoningMessagePartProps) {
  const running = status.type === "running"
  return (
    <div className="my-3 flex items-center gap-2 text-xs text-muted-foreground">
      <BrainCircuit
        className={cn(
          "size-3.5",
          running && "animate-pulse motion-reduce:animate-none"
        )}
      />
      <span>
        {running
          ? "응답 계획을 정리하고 있습니다."
          : "응답 계획을 반영했습니다. 내부 추론 내용은 표시하지 않습니다."}
      </span>
    </div>
  )
})

const ToolPart = memo(function ToolPart({
  toolName,
  argsText,
  result,
  isError,
  status,
}: ToolCallMessagePartProps) {
  const running =
    status.type === "running" ||
    status.type === "requires-action"
  // Opens while the call is in flight, then follows the reader. Binding `open`
  // to `running` would reopen on every streaming re-render and slam the panel
  // shut the moment the call finishes.
  const [open, setOpen] = useState(running)
  const argumentSummary = toolArgumentSummary(argsText)
  const resultText = toolResultText(result)
  const subagentType =
    toolName === "task" ? taskSubagentTypeFromArgs(argsText) : undefined
  const label =
    toolName === "task"
      ? subagentType
        ? `서브에이전트 · ${subagentType}`
        : "서브에이전트"
      : toolName
  return (
    <details
      className="my-3 rounded-xl bg-muted/50"
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-sm">
        <ToolCase
          className={cn(
            "size-4",
            running && "animate-pulse motion-reduce:animate-none"
          )}
        />
        <span className="min-w-0 flex-1 truncate">{label}</span>
        <span className="text-xs font-normal text-muted-foreground">
          {running
            ? "실행 중"
            : isError || status.type === "incomplete"
              ? "완료하지 못함"
              : "완료"}
        </span>
        <ChevronRight className="size-3.5 transition-transform motion-reduce:transition-none [[open]>&]:rotate-90" />
      </summary>
      <div className="space-y-2 border-t border-border/60 px-3 py-3 text-xs">
        <p className="text-muted-foreground">
          입력: {argumentSummary ?? "인자 없음"}
        </p>
        {resultText ? (
          <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-background/60 p-2 font-mono text-[11px] leading-5 text-muted-foreground">
            {resultText}
          </pre>
        ) : (
          <p className="text-muted-foreground">
            {running ? "결과를 기다리는 중입니다." : "결과가 없습니다."}
          </p>
        )}
      </div>
    </details>
  )
})

function taskSubagentTypeFromArgs(argsText: string): string | undefined {
  if (!argsText) return undefined
  try {
    const parsed = JSON.parse(argsText) as unknown
    if (
      parsed &&
      typeof parsed === "object" &&
      !Array.isArray(parsed) &&
      "subagent_type" in parsed &&
      typeof parsed.subagent_type === "string" &&
      /^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/.test(parsed.subagent_type)
    ) {
      return parsed.subagent_type
    }
  } catch {
    return undefined
  }
  return undefined
}

const MESSAGE_COMPONENTS = {
  Text: MarkdownText,
  Reasoning: ReasoningPart,
  tools: { Fallback: ToolPart },
}

function SourceItems({ sources }: { sources: readonly InspectionSource[] }) {
  return (
    <ol className="space-y-2">
      {sources.map((source) => {
        const url = safeSourceUrl(source.url)
        const label =
          source.title ?? source.path ?? source.docId ?? url ?? source.key
        const reactKey = [
          source.key,
          source.url ?? "",
          source.path ?? "",
          source.title ?? "",
        ].join("\u0000")
        return (
          <li key={reactKey} className="rounded-lg border bg-background p-2">
            <div className="flex items-start gap-2">
              {source.rank !== undefined ? (
                <span className="shrink-0 font-mono text-[10px] text-muted-foreground">
                  #{source.rank}
                </span>
              ) : null}
              <div className="min-w-0 flex-1">
                {url ? (
                  <a
                    href={url}
                    target="_blank"
                    rel="noreferrer"
                    className="break-words font-medium underline underline-offset-4"
                  >
                    {label}
                  </a>
                ) : (
                  <p className="break-words font-medium">{label}</p>
                )}
                {source.path && source.path !== label ? (
                  <p className="mt-1 break-all font-mono text-[10px] text-muted-foreground">
                    {source.path}
                  </p>
                ) : null}
                {source.score !== undefined ? (
                  <p className="mt-1 text-[10px] text-muted-foreground">
                    점수 {source.score}
                  </p>
                ) : null}
                {source.citedText ? (
                  <p className="mt-1 line-clamp-3 text-xs text-muted-foreground">
                    {source.citedText}
                  </p>
                ) : null}
              </div>
            </div>
          </li>
        )
      })}
    </ol>
  )
}

function AnswerSources({ sources }: { sources: readonly InspectionSource[] }) {
  return (
    <details className="mt-5 rounded-xl border border-border/70 bg-muted/30 text-xs">
      <summary className="cursor-pointer list-none px-3 py-2.5 font-medium">
        인용 출처 {sources.length}개
      </summary>
      <div aria-label="답변 인용 출처" className="border-t px-3 py-3">
        <SourceItems sources={sources} />
      </div>
    </details>
  )
}

function MessageActions() {
  return (
    <ActionBarPrimitive.Root
      hideWhenRunning
      className="mt-1 flex h-8 items-center"
    >
      <ActionBarPrimitive.Copy
        aria-label="메시지 복사"
        copiedDuration={2_000}
        className="group/copy flex size-8 items-center justify-center rounded-lg text-muted-foreground transition-colors motion-reduce:transition-none hover:bg-muted hover:text-foreground"
      >
        <Copy className="size-3.5 group-data-[copied]/copy:hidden" />
        <Check className="hidden size-3.5 group-data-[copied]/copy:block" />
      </ActionBarPrimitive.Copy>
    </ActionBarPrimitive.Root>
  )
}

function ChatMessage() {
  const role = useAuiState((state) => state.message.role)
  const rawSources = useAuiState(
    (state) => state.message.metadata.custom.sources
  )
  const sources = useMemo(
    () => inspectionSourcesFromUnknown(rawSources),
    [rawSources]
  )
  if (role === "system") return null

  return (
    <MessagePrimitive.Root
      className={cn(
        "group/message mx-auto flex w-full max-w-3xl flex-col px-4 py-5 md:px-6",
        role === "user" ? "items-end" : "items-start"
      )}
    >
      <div
        className={cn(
          "min-w-0 text-[15px] leading-7",
          role === "assistant" && "w-full",
          role === "user" &&
            "max-w-[82%] rounded-[22px] rounded-br-lg bg-muted px-4 py-2.5 text-foreground sm:max-w-[75%]"
        )}
      >
        <MessagePrimitive.Parts components={MESSAGE_COMPONENTS} />
        {role === "assistant" && sources.length > 0 ? (
          <AnswerSources sources={sources} />
        ) : null}
        <MessagePrimitive.Error>
          <ErrorPrimitive.Root className="mt-3 rounded-xl border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
            <ErrorPrimitive.Message>
              응답을 완료하지 못했습니다. 같은 대화에서 다시 시도해 주세요.
            </ErrorPrimitive.Message>
          </ErrorPrimitive.Root>
        </MessagePrimitive.Error>
      </div>
      {role === "assistant" ? <MessageActions /> : null}
    </MessagePrimitive.Root>
  )
}

function EmptyConversation() {
  return (
    <AuiIf condition={(state) => state.thread.isEmpty}>
      <div className="mx-auto flex min-h-full w-full max-w-3xl flex-col justify-center px-4 py-10 md:px-6 md:py-16">
        <h1 className="text-balance text-center text-3xl font-medium tracking-[-0.035em] sm:text-4xl">
          무엇이 궁금하세요?
        </h1>
        <p className="mx-auto mt-3 max-w-md text-pretty text-center text-sm leading-6 text-muted-foreground">
          블로그와 프로젝트를 검색하고, 사용된 방법과 출처를 함께 확인할 수
          있어요.
        </p>
        {/* Above the composer, the way every familiar chat app places them:
            a starting point to pick from, then the box you type in. */}
        <div className="mt-8 flex w-full flex-wrap justify-center gap-2">
          {SUGGESTIONS.map(({ prompt }) => (
            <ThreadPrimitive.Suggestion
              key={prompt}
              prompt={prompt}
              send
              className="min-h-9 rounded-full border border-border/70 bg-background px-3.5 py-2 text-left text-[13px] text-muted-foreground transition-colors motion-reduce:transition-none hover:border-border hover:bg-muted hover:text-foreground"
            >
              {prompt}
            </ThreadPrimitive.Suggestion>
          ))}
        </div>
        <Composer centered />
      </div>
    </AuiIf>
  )
}

type InterruptState = NonNullable<
  ReturnType<typeof useLangGraphInterruptState>
>
const MAX_INTERRUPT_RESPONSE_CODE_UNITS = 1_000
const MAX_INTERRUPT_RESPONSE_UTF8_BYTES = 3_000
const MAX_COMPOSER_CODE_UNITS = 8_000
const MAX_COMPOSER_UTF8_BYTES = 16_000
const COMPOSER_LIMIT_ERROR =
  "메시지가 너무 깁니다. 16KB 이하로 줄여 주세요."
const interruptResponseEncoder = new TextEncoder()
const composerEncoder = new TextEncoder()
const interruptViewKeys = new WeakMap<object, number>()
let nextInterruptViewKey = 1

function InterruptResponseCard({
  projection,
}: {
  projection: InterruptUiProjection
}) {
  const sendCommand = useLangGraphSendCommand()
  const [response, setResponse] = useState("")
  const [sending, setSending] = useState(false)
  const [resumeError, setResumeError] = useState<string>()
  const responseInputRef = useRef<HTMLInputElement>(null)
  useEffect(() => responseInputRef.current?.focus(), [])
  const respond = async (answer: string) => {
    const normalized = answer.trim()
    if (
      !normalized ||
      normalized.length > MAX_INTERRUPT_RESPONSE_CODE_UNITS ||
      interruptResponseEncoder.encode(normalized).byteLength >
        MAX_INTERRUPT_RESPONSE_UTF8_BYTES ||
      sending
    ) {
      return
    }
    setResumeError(undefined)
    setSending(true)
    let resumed = false
    try {
      // Resume carries only the user's bounded decision/input. The opaque
      // interrupt value remains protocol state and is never echoed back.
      await sendCommand({ resume: normalized })
      resumed = true
    } catch {
      setResumeError(
        "응답을 보내지 못했습니다. 승인 요청은 유지되었습니다. 다시 시도해 주세요."
      )
      responseInputRef.current?.focus()
    } finally {
      setSending(false)
      if (resumed) restoreComposerFocus()
    }
  }

  return (
    <div className="mx-auto mb-3 w-[calc(100%-2rem)] max-w-3xl rounded-2xl border border-amber-500/40 bg-amber-500/5 p-4 shadow-sm">
      <div className="flex items-start gap-3">
        <Clock3 className="mt-0.5 size-5 text-amber-700 dark:text-amber-300" />
        <div className="min-w-0 flex-1">
          <p className="font-medium">{projection.title}</p>
          <p className="mt-2 whitespace-pre-wrap break-words text-xs text-muted-foreground">
            {projection.prompt}
          </p>
        </div>
      </div>
      {projection.kind === "approval" ? (
        <div className="mt-4 flex flex-wrap gap-2">
          <Button
            size="sm"
            disabled={sending}
            onClick={() => void respond("approve")}
          >
            <Check className="size-4" />
            승인
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={sending}
            onClick={() => void respond("reject")}
          >
            거절
          </Button>
        </div>
      ) : null}
      <form
        className="mt-3 flex min-w-0 flex-col gap-2 sm:flex-row"
        onSubmit={(event) => {
          event.preventDefault()
          void respond(response)
        }}
      >
        <label className="sr-only" htmlFor="interrupt-response">
          수정해서 재개할 응답
        </label>
        <input
          ref={responseInputRef}
          id="interrupt-response"
          value={response}
          onChange={(event) => {
            setResponse(event.target.value)
            setResumeError(undefined)
          }}
          maxLength={MAX_INTERRUPT_RESPONSE_CODE_UNITS}
          placeholder={projection.inputHint}
          aria-describedby={
            resumeError ? "interrupt-response-error" : undefined
          }
          aria-invalid={resumeError !== undefined}
          className="w-full min-w-0 flex-1 rounded-lg border bg-background px-3 py-2 text-sm"
        />
        <Button
          type="submit"
          size="sm"
          variant="secondary"
          disabled={!response.trim() || sending}
          className="w-full sm:w-auto"
        >
          수정 후 재개
        </Button>
      </form>
      {resumeError ? (
        <p
          id="interrupt-response-error"
          role="alert"
          className="mt-2 text-xs text-destructive"
        >
          {resumeError}
        </p>
      ) : null}
    </div>
  )
}

function interruptViewKey(interrupt: InterruptState): number {
  const current = interruptViewKeys.get(interrupt)
  if (current !== undefined) return current
  const created = nextInterruptViewKey
  nextInterruptViewKey += 1
  interruptViewKeys.set(interrupt, created)
  return created
}

function ConversationFooter() {
  const interrupt = useLangGraphInterruptState()
  if (interrupt) {
    const projection = readRuntimeInterruptProjection(interrupt.value)
    return (
      <InterruptResponseCard
        key={interruptViewKey(interrupt)}
        projection={projection}
      />
    )
  }
  return (
    <AuiIf condition={(state) => !state.thread.isEmpty}>
      <Composer />
    </AuiIf>
  )
}

function Composer({ centered = false }: { centered?: boolean }) {
  const runtimeUi = useAgentRuntimeUi()
  const compositionRef = useRef(false)
  const composerInputRef = useRef<HTMLTextAreaElement>(null)
  const [composerError, setComposerError] = useState<string>()
  const guardImeEnter = createImeEnterGuard(() => compositionRef.current)
  const ready = runtimeUi.connectionStatus === "ready"
  const connectionError = runtimeUi.connectionError
  const turnError = ready ? runtimeUi.turnError : undefined
  const runConnectionAction = () => {
    if (connectionError?.action === "sign-in") {
      window.location.assign("/login")
      return
    }
    runtimeUi.retryConnection()
  }
  const dismissTurnError = () => {
    runtimeUi.dismissTurnError()
    restoreComposerFocus()
  }
  useEffect(() => {
    if (!centered) composerInputRef.current?.focus()
  }, [centered])
  const rejectOversizedComposer = () => {
    const value = composerInputRef.current?.value ?? ""
    if (
      value.length <= MAX_COMPOSER_CODE_UNITS &&
      composerEncoder.encode(value).byteLength <= MAX_COMPOSER_UTF8_BYTES
    ) {
      setComposerError(undefined)
      return false
    }
    setComposerError(COMPOSER_LIMIT_ERROR)
    setTimeout(() => composerInputRef.current?.focus(), 0)
    return true
  }

  return (
    <div
      className={cn(
        "w-full px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] md:px-6",
        centered
          ? "mt-4 px-0 pb-0 md:px-0"
          : "bg-gradient-to-t from-background via-background to-transparent pt-6"
      )}
    >
      {runtimeUi.connectionStatus === "error" && connectionError ? (
        <div
          role="alert"
          className="mx-auto mb-2 flex max-w-3xl items-center justify-between gap-3 rounded-lg border border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive"
        >
          <span>{connectionError.message}</span>
          <button
            type="button"
            className="shrink-0 font-medium underline underline-offset-4"
            onClick={runConnectionAction}
          >
            {connectionError.actionLabel}
          </button>
        </div>
      ) : null}
      {turnError ? (
        <div
          role="alert"
          className="mx-auto mb-2 flex max-w-3xl items-center justify-between gap-3 rounded-lg border border-amber-500/40 bg-amber-500/5 px-3 py-2 text-xs text-amber-900 dark:text-amber-200"
        >
          <span>{turnError.message}</span>
          <button
            type="button"
            className="shrink-0 font-medium underline underline-offset-4"
            onClick={dismissTurnError}
          >
            {turnError.actionLabel}
          </button>
        </div>
      ) : null}
      <ComposerPrimitive.Root
        className="mx-auto flex max-w-3xl items-end gap-2 rounded-[28px] border border-border/80 bg-background p-2 shadow-[0_8px_30px_rgb(0_0_0/0.06)] transition-shadow motion-reduce:transition-none focus-within:border-foreground/30 focus-within:shadow-[0_12px_40px_rgb(0_0_0/0.1)] dark:bg-muted/60"
        onSubmitCapture={(event) => {
          if (rejectOversizedComposer()) {
            event.preventDefault()
            event.stopPropagation()
          }
        }}
      >
        <ComposerPrimitive.Input
          ref={composerInputRef}
          aria-label={COMPOSER_ACCESSIBLE_NAME}
          aria-describedby={
            composerError ? "composer-size-error" : undefined
          }
          aria-invalid={composerError !== undefined}
          placeholder={
            ready
              ? "블로그와 프로젝트에 관해 물어보세요…"
              : runtimeUi.connectionStatus === "error"
                ? "연결을 확인해 주세요"
                : "AI를 깨우는 중…"
          }
          disabled={!ready}
          rows={1}
          maxRows={8}
          maxLength={MAX_COMPOSER_CODE_UNITS}
          submitMode="enter"
          onInput={(event) => {
            if (
              composerEncoder.encode(event.currentTarget.value).byteLength <=
              MAX_COMPOSER_UTF8_BYTES
            ) {
              setComposerError(undefined)
            } else {
              setComposerError(COMPOSER_LIMIT_ERROR)
            }
          }}
          onCompositionStart={() => {
            compositionRef.current = true
          }}
          onCompositionEnd={() => {
            compositionRef.current = false
          }}
          onKeyDownCapture={guardImeEnter}
          className="max-h-48 min-h-11 min-w-0 flex-1 resize-none bg-transparent px-3 py-2.5 text-[15px] outline-none placeholder:text-muted-foreground"
        />
        <AuiIf condition={(state) => state.thread.isRunning}>
          <ComposerPrimitive.Cancel
            aria-label="응답 중지"
            className="flex size-10 shrink-0 items-center justify-center rounded-full border bg-background transition-colors motion-reduce:transition-none hover:bg-muted"
          >
            <CircleStop className="size-4" />
          </ComposerPrimitive.Cancel>
        </AuiIf>
        <AuiIf condition={(state) => !state.thread.isRunning}>
          <ComposerPrimitive.Send
            aria-label="메시지 보내기"
            onClick={(event) => {
              if (rejectOversizedComposer()) {
                // ComposerPrimitive.Send invokes the runtime directly instead
                // of submitting its parent form. Cancelling this first handler
                // prevents assistant-ui's composed send callback from running.
                event.preventDefault()
              }
            }}
            className="flex size-10 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground transition-transform motion-reduce:transition-none hover:scale-105 motion-reduce:hover:scale-100 disabled:opacity-40"
          >
            <ArrowUp className="size-4" />
          </ComposerPrimitive.Send>
        </AuiIf>
      </ComposerPrimitive.Root>
      {composerError ? (
        <p
          id="composer-size-error"
          role="alert"
          className="mx-auto mt-2 max-w-3xl text-xs text-destructive"
        >
          {composerError}
        </p>
      ) : null}
      <p className="mx-auto mt-2 max-w-3xl text-center text-[11px] text-muted-foreground max-sm:hidden">
        AI 답변은 부정확할 수 있습니다. Enter로 전송 · Shift+Enter로 줄바꿈
      </p>
    </div>
  )
}

function Conversation() {
  return (
    <ThreadPrimitive.Root className="flex min-h-0 flex-1 flex-col bg-background">
      <ThreadPrimitive.Viewport className="relative min-h-0 flex-1 overflow-y-auto">
        <EmptyConversation />
        {/* Every familiar chat app grows the transcript upward from the
            composer. Top-anchored messages left a single question stranded
            above hundreds of pixels of nothing. */}
        <AuiIf condition={(state) => !state.thread.isEmpty}>
        <div className="flex min-h-full flex-col justify-end">
          <ThreadPrimitive.Messages>
            {() => <ChatMessage />}
          </ThreadPrimitive.Messages>
          <AuiIf condition={(state) => state.thread.isRunning}>
            <div
              role="status"
              aria-live="polite"
              className="mx-auto flex w-full max-w-3xl items-center gap-2.5 px-4 py-3 text-sm text-muted-foreground md:px-6"
            >
              <LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" />
              검색하고 답변을 구성하고 있습니다.
            </div>
          </AuiIf>
        </div>
        </AuiIf>
        <AuiIf condition={(state) => !state.thread.isEmpty}>
          <ThreadPrimitive.ScrollToBottom
            aria-label="최신 메시지로 이동"
            className="sticky bottom-3 left-1/2 z-10 flex size-9 -translate-x-1/2 items-center justify-center rounded-full border bg-background shadow-md disabled:invisible"
          >
            <ArrowDown className="size-4" />
          </ThreadPrimitive.ScrollToBottom>
        </AuiIf>
      </ThreadPrimitive.Viewport>
      <ConversationFooter />
    </ThreadPrimitive.Root>
  )
}

function ThreadListItem() {
  const aui = useAui()
  const itemId = useAuiState((state) => state.threadListItem.id)
  const itemTitle = useAuiState(
    (state) => state.threadListItem.title
  )
  const itemStatus = useAuiState(
    (state) => state.threadListItem.status
  )
  const itemLastMessageAt = useAuiState(
    (state) => state.threadListItem.lastMessageAt
  )
  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState(itemTitle ?? "")
  const [renameError, setRenameError] = useState<string>()
  const [renaming, setRenaming] = useState(false)
  const renameInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!editing) {
      setTitle(itemTitle ?? "")
      setRenameError(undefined)
    }
  }, [editing, itemTitle])

  const submitRename = async (event: FormEvent) => {
    event.preventDefault()
    const normalized = title.trim()
    if (!normalized || renaming) return
    setRenameError(undefined)
    setRenaming(true)
    try {
      // assistant-ui 0.15 types AssistantClient commands as fire-and-forget,
      // while the pinned remote runtime still returns the adapter Promise.
      // Keep that reviewed compatibility assertion at this one UX boundary so
      // a rejected remote rename remains visible and retryable.
      const rename = aui.threadListItem().rename as unknown as (
        newTitle: string
      ) => Promise<void>
      await rename(normalized)
    } catch {
      setRenaming(false)
      setRenameError(
        "대화 제목을 바꾸지 못했습니다. 잠시 후 다시 시도해 주세요."
      )
      requestAnimationFrame(() => renameInputRef.current?.focus())
      return
    }
    setRenaming(false)
    setEditing(false)
  }

  return (
    <ThreadListItemPrimitive.Root className="group flex items-center gap-1 rounded-lg data-[active=true]:bg-accent">
      {editing ? (
        <form className="min-w-0 flex-1 p-1" onSubmit={submitRename}>
          <label className="sr-only" htmlFor={`title-${itemId}`}>
            대화 제목
          </label>
          <input
            ref={renameInputRef}
            id={`title-${itemId}`}
            autoFocus
            value={title}
            onChange={(event) => {
              setTitle(event.target.value)
              setRenameError(undefined)
            }}
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                setEditing(false)
              }
            }}
            disabled={renaming}
            aria-describedby={
              renameError ? `title-error-${itemId}` : undefined
            }
            aria-invalid={renameError !== undefined}
            className="w-full rounded border bg-background px-2 py-1.5 text-sm"
          />
          {renameError ? (
            <p
              id={`title-error-${itemId}`}
              role="alert"
              className="px-1 pt-1 text-xs text-destructive"
            >
              {renameError}
            </p>
          ) : null}
        </form>
      ) : (
        <ThreadListItemPrimitive.Trigger className="min-w-0 flex-1 rounded-lg px-3 py-2 text-left text-sm">
          <span className="block truncate">
            {itemTitle || "제목을 만드는 중…"}
          </span>
          {itemLastMessageAt ? (
            <span className="mt-0.5 block text-[11px] text-foreground">
              {itemLastMessageAt.toLocaleDateString("ko-KR")}
            </span>
          ) : null}
        </ThreadListItemPrimitive.Trigger>
      )}
      {!editing ? (
        <button
          type="button"
          aria-label="대화 제목 변경"
          className="flex size-8 shrink-0 items-center justify-center rounded-md text-muted-foreground opacity-0 transition-opacity motion-reduce:transition-none hover:bg-background hover:text-foreground group-hover:opacity-100 group-focus-within:opacity-100"
          onClick={() => {
            setRenameError(undefined)
            setEditing(true)
          }}
        >
          <Pencil className="size-3.5" />
        </button>
      ) : null}
      {itemStatus === "archived" ? (
        <ThreadListItemPrimitive.Unarchive
          aria-label="대화 복원"
          className="mr-1 flex size-8 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-background hover:text-foreground"
        >
          <RotateCcw className="size-3.5" />
        </ThreadListItemPrimitive.Unarchive>
      ) : (
        <ThreadListItemPrimitive.Archive
          aria-label="대화 보관"
          className="mr-1 flex size-8 shrink-0 items-center justify-center rounded-md text-muted-foreground opacity-0 transition-opacity motion-reduce:transition-none hover:bg-background hover:text-foreground group-hover:opacity-100 group-focus-within:opacity-100"
        >
          <Archive className="size-3.5" />
        </ThreadListItemPrimitive.Archive>
      )}
    </ThreadListItemPrimitive.Root>
  )
}

function ThreadRail() {
  return (
    <ThreadListPrimitive.Root className="flex h-full min-h-0 flex-col bg-background">
      <div className="border-b p-4">
        <ThreadListPrimitive.New className="flex min-h-11 w-full items-center justify-center gap-2 rounded-xl bg-primary px-3 py-2 text-sm font-medium text-primary-foreground transition-none hover:opacity-90 data-[active=true]:opacity-70">
          <Plus className="size-4" />
          새 대화
        </ThreadListPrimitive.New>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        <p className="px-2 pb-2 pt-1 text-xs font-medium text-muted-foreground">
          최근 대화
        </p>
        <ThreadListPrimitive.Items>
          {() => <ThreadListItem />}
        </ThreadListPrimitive.Items>
        <ThreadListPrimitive.LoadMore className="mt-2 w-full rounded-lg px-3 py-2 text-xs text-muted-foreground hover:bg-muted">
          대화 더 보기
        </ThreadListPrimitive.LoadMore>
        <div className="mt-5 border-t pt-4">
          <p className="flex items-center gap-2 px-2 pb-2 text-xs font-medium text-muted-foreground">
            <Archive className="size-3" />
            보관됨
          </p>
          <ThreadListPrimitive.Items archived>
            {() => <ThreadListItem />}
          </ThreadListPrimitive.Items>
        </div>
      </div>
      <div className="border-t p-4 text-[11px] leading-5 text-muted-foreground">
        현재 서버는 대화 삭제를 지원하지 않습니다. 보관과 복원은 가능합니다.
      </div>
    </ThreadListPrimitive.Root>
  )
}

const UNKNOWN_SERVER_VALUE = "서버 미제공"

function statusLabel(status: string): string {
  switch (status) {
    case "started":
    case "running":
    case "streaming":
      return "실행 중"
    case "completed":
    case "success":
      return "완료"
    case "failed":
    case "error":
      return "완료하지 못함"
    case "interrupted":
      return "입력 대기"
    case "reconnecting":
      return "재연결 중"
    default:
      return status
  }
}

function ActivityField({
  label,
  value,
}: {
  label: string
  value: ReactNode | undefined
}) {
  return (
    <div className="min-w-0">
      <dt className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </dt>
      <dd className="mt-0.5 break-words text-xs">
        {value ?? UNKNOWN_SERVER_VALUE}
      </dd>
    </div>
  )
}

function ActivitySources({
  sources,
  known,
}: {
  sources: readonly InspectionSource[]
  known: boolean
}) {
  return (
    <div className="mt-3 border-t pt-3">
      <p className="mb-2 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
        출처 목록
      </p>
      {!known ? (
        <p className="text-xs text-muted-foreground">
          {UNKNOWN_SERVER_VALUE}
        </p>
      ) : sources.length === 0 ? (
        <p className="text-xs text-muted-foreground">제공된 출처 없음</p>
      ) : (
        <SourceItems sources={sources} />
      )}
    </div>
  )
}

function ActivityDetails({ activity }: { activity: AgentActivity }) {
  if (activity.kind === "retrieval") {
    const stage = activity.stages[0]
    return (
      <>
        <dl className="mt-3 grid grid-cols-2 gap-3 border-t pt-3">
          <ActivityField label="질의" value={activity.query} />
          <ActivityField
            label="질의 잘림"
            value={activity.queryTruncated ? "예" : "아니요"}
          />
          <ActivityField label="검색 방법" value={activity.methodId} />
          <ActivityField
            label="구현"
            value={activity.methodIdentity.implementationId}
          />
          <ActivityField
            label="검색 결과 수"
            value={activity.hitCount.toLocaleString("ko-KR")}
          />
          <ActivityField
            label="근거 수"
            value={activity.sources.length.toLocaleString("ko-KR")}
          />
          <ActivityField
            label="코퍼스 문서 수"
            value={activity.corpusDocumentCount.toLocaleString("ko-KR")}
          />
          <ActivityField
            label="코퍼스 리비전"
            value={activity.corpusRevision}
          />
          <ActivityField
            label="검색기 fingerprint"
            value={activity.methodIdentity.fingerprint}
          />
          <ActivityField
            label="실행 시간"
            value={`${stage.elapsedMs.toLocaleString("ko-KR")}ms`}
          />
          <ActivityField
            label="적용 결과"
            value={`${stage.application.inputCount.toLocaleString("ko-KR")} → ${stage.application.outputCount.toLocaleString("ko-KR")}`}
          />
          <ActivityField
            label="출처 잘림"
            value={activity.sourcesTruncated ? "예" : "아니요"}
          />
          <ActivityField label="전달 방식" value="실시간 실행 전용" />
        </dl>
        <ActivitySources sources={activity.sources} known />
      </>
    )
  }
  if (activity.kind === "nested") {
    return (
      <dl className="mt-3 grid grid-cols-2 gap-3 border-t pt-3">
        <ActivityField label="중첩 작업" value={activity.name} />
        <ActivityField
          label="소요 시간"
          value={
            activity.elapsedMs !== undefined
              ? `${activity.elapsedMs.toLocaleString("ko-KR")}ms`
              : undefined
          }
        />
      </dl>
    )
  }
  if (activity.kind === "sources") {
    return <ActivitySources sources={activity.sources} known />
  }
  if (activity.kind === "tool") {
    return (
      <dl className="mt-3 border-t pt-3">
        <ActivityField label="도구" value={activity.toolName} />
      </dl>
    )
  }
  return null
}

function ActivityPanel() {
  const { activities, inspectionAvailability } = useAgentRuntimeUi()
  const visible = useMemo(() => [...activities].reverse(), [activities])

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="border-b px-4 py-3">
        <p className="font-medium">실행 상세</p>
        <p className="mt-1 text-xs text-muted-foreground">
          검색·도구·중첩 작업 상태
        </p>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {visible.length === 0 ? (
          <div className="rounded-xl border border-dashed p-4 text-sm text-muted-foreground">
            {inspectionAvailability === "past-unavailable" ? (
              <>
                <p className="font-medium text-foreground">
                  이전 실행의 검사 정보는 다시 불러올 수 없습니다.
                </p>
                <p className="mt-2 text-xs leading-5">
                  답변은 저장되지만 검색 방법·출처·실행 시간은 보존하지
                  않습니다. 새 질문을 보내면 실시간 실행 중에만 확인할 수
                  있습니다.
                </p>
              </>
            ) : (
              <>
                <p className="font-medium text-foreground">
                  실행 상세는 실시간 실행 중에만 제공됩니다.
                </p>
                <p className="mt-2 text-xs leading-5">
                  질문을 보내면 어떤 검색을 어떤 순서로 했는지, 무엇을 근거로
                  삼았는지가 실행되는 동안 여기에 표시됩니다.
                </p>
              </>
            )}
          </div>
        ) : (
          <ol className="space-y-2">
            {visible.map((activity) => (
              <li
                key={activity.id}
                className="rounded-xl border bg-card p-3 text-sm"
              >
                <div className="flex items-start gap-2">
                  {activity.kind === "tool" ? (
                    <ToolCase className="mt-0.5 size-4 shrink-0" />
                  ) : activity.kind === "connection" ? (
                    <History className="mt-0.5 size-4 shrink-0" />
                  ) : (
                    <ListTree className="mt-0.5 size-4 shrink-0" />
                  )}
                  <div className="min-w-0">
                    <p>{activity.label}</p>
                    <p className="mt-1 text-[10px] font-medium text-muted-foreground">
                      {statusLabel(activity.status)}
                    </p>
                    {activity.namespace.length > 0 ? (
                      <p className="mt-1 truncate font-mono text-[10px] text-muted-foreground">
                        {activity.namespace.join(" / ")}
                      </p>
                    ) : null}
                  </div>
                </div>
                <ActivityDetails activity={activity} />
              </li>
            ))}
          </ol>
        )}
      </div>
    </div>
  )
}

function ThreadSheet() {
  return (
    <Sheet>
      <SheetTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          aria-label="대화 목록 열기"
          className="gap-2 rounded-xl px-2.5 sm:px-3"
        >
          <Menu className="size-4" />
          <span className="hidden sm:inline">대화</span>
        </Button>
      </SheetTrigger>
      <SheetContent
        side="left"
        className="w-[min(90vw,340px)] px-0 pb-0 pt-10"
      >
        <SheetHeader className="sr-only">
          <SheetTitle>대화 목록</SheetTitle>
          <SheetDescription>대화를 만들거나 전환합니다.</SheetDescription>
        </SheetHeader>
        <ThreadRail />
      </SheetContent>
    </Sheet>
  )
}

function DetailSheet() {
  return (
    <Sheet>
      <SheetTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          aria-label="실행 상세 열기"
          className="gap-2 rounded-xl px-2.5 sm:px-3"
        >
          <ListTree className="size-4" />
          <span className="hidden sm:inline">실행</span>
        </Button>
      </SheetTrigger>
      <SheetContent side="right" className="w-[min(92vw,420px)] p-0">
        <SheetHeader className="sr-only">
          <SheetTitle>실행 상세</SheetTitle>
          <SheetDescription>
            검색과 도구 실행 상태입니다.
          </SheetDescription>
        </SheetHeader>
        <ActivityPanel />
      </SheetContent>
    </Sheet>
  )
}

function NewThreadButton() {
  return (
    <ThreadListPrimitive.Root>
      <ThreadListPrimitive.New
        aria-label="새 대화"
        className="flex min-h-9 items-center gap-2 rounded-xl border border-border/70 px-2.5 text-sm font-medium transition-colors motion-reduce:transition-none hover:bg-muted data-[active=true]:opacity-60 sm:px-3"
      >
        <Plus className="size-4" />
        <span className="hidden sm:inline">새 대화</span>
      </ThreadListPrimitive.New>
    </ThreadListPrimitive.Root>
  )
}

const MODEL_LABELS: Record<AgentModel, string> = {
  "gpt-5.6-luna": "Luna",
  "gpt-5.6-terra": "Terra",
  "gpt-5.6-sol": "Sol",
}

function ModelSelector() {
  const { modelSelection, selectedModel, setSelectedModel } =
    useAgentRuntimeUi()
  const running = useAuiState((state) => state.thread.isRunning)
  if (!modelSelection) return null
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          aria-label="모델 선택"
          disabled={running}
          className="max-w-28 gap-1.5 rounded-xl px-2.5 sm:max-w-none sm:px-3"
        >
          <span className="truncate">{MODEL_LABELS[selectedModel]}</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuLabel>응답 모델</DropdownMenuLabel>
        <DropdownMenuRadioGroup
          value={selectedModel}
          onValueChange={(value) => {
            if (isAgentModel(value)) setSelectedModel(value)
          }}
        >
          {(Object.keys(MODEL_LABELS) as AgentModel[]).map((model) => (
            <DropdownMenuRadioItem key={model} value={model}>
              <span>{MODEL_LABELS[model]}</span>
              <span className="text-xs text-muted-foreground">{model}</span>
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function WorkspaceHeader() {
  const { connectionStatus } = useAgentRuntimeUi()
  // The agent scales to zero, so this state lasts as long as a container boot -
  // measured near a minute. Naming it tells the visitor why nothing is ready yet.
  const status =
    connectionStatus === "ready"
      ? "연결됨"
      : connectionStatus === "error"
        ? "연결 확인 필요"
        : "AI 깨우는 중"

  return (
    <header className="flex min-h-14 items-center justify-between gap-3 border-b border-border/70 px-3 sm:px-4">
      <div className="flex min-w-0 items-center gap-3">
        <Image
          src="/logo.png"
          alt=""
          width={64}
          height={64}
          priority
          className="size-8 shrink-0 rounded-xl object-cover"
        />
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold tracking-tight">Syshin AI</p>
          <p className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
            <span
              aria-hidden="true"
              className={cn(
                "size-1.5 rounded-full",
                connectionStatus === "ready"
                  ? "bg-emerald-500"
                  : connectionStatus === "error"
                    ? "bg-destructive"
                    : "animate-pulse bg-amber-500 motion-reduce:animate-none"
              )}
            />
            {status}
          </p>
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-0.5">
        <ModelSelector />
        <NewThreadButton />
        <ThreadSheet />
        <DetailSheet />
      </div>
    </header>
  )
}

function OnlineStatus() {
  const [online, setOnline] = useState(true)
  useEffect(() => {
    const update = () => setOnline(navigator.onLine)
    update()
    window.addEventListener("online", update)
    window.addEventListener("offline", update)
    return () => {
      window.removeEventListener("online", update)
      window.removeEventListener("offline", update)
    }
  }, [])
  if (online) return null
  return (
    <div
      role="status"
      className="flex items-center gap-2 bg-amber-500/10 px-4 py-2 text-xs text-amber-900 dark:text-amber-200"
    >
      <WifiOff className="size-3.5" />
      오프라인입니다. 연결이 복구되면 다시 전송해 주세요.
    </div>
  )
}

export function ChatShell() {
  return (
    <section
      aria-label="RAG 평가 챗봇"
      className="relative flex h-[calc(100svh-4.5rem)] min-h-0 bg-muted/20 p-0 sm:p-3 md:p-4 supports-[height:100dvh]:h-[calc(100dvh-4.5rem)]"
    >
      <div className="mx-auto flex h-full min-h-0 w-full max-w-5xl flex-col overflow-hidden bg-background sm:rounded-2xl sm:border sm:border-border/60 sm:shadow-[0_1px_3px_rgb(0_0_0/0.04),0_8px_24px_-12px_rgb(0_0_0/0.10)]">
        <OnlineStatus />
        <WorkspaceHeader />
        <Conversation />
      </div>
    </section>
  )
}

export function SignedOutChat() {
  return (
    <section className="flex min-h-[70svh] items-center justify-center bg-muted/30 px-6 py-16">
      <div className="w-full max-w-lg text-center">
        <div className="mx-auto flex size-11 items-center justify-center rounded-2xl bg-primary text-primary-foreground">
          <UserRound className="size-5" />
        </div>
        <h1 className="mt-6 text-3xl font-medium tracking-[-0.035em]">
          AI 검색 실험실
        </h1>
        <p className="mx-auto mt-3 max-w-md text-sm leading-6 text-muted-foreground">
          공개 체험은 현재 비활성 상태입니다. 소유자 계정으로 로그인하면
          AI 검색 실험실을 계속 테스트할 수 있습니다.
        </p>
        <Button asChild className="mt-7 rounded-xl px-5">
          <Link href="/login">로그인해서 테스트</Link>
        </Button>
      </div>
    </section>
  )
}

export function ChatLoading() {
  return (
    <section
      aria-label="AI 검색 실험실 불러오는 중"
      className="flex min-h-[70svh] items-center justify-center border-t"
    >
      <div
        role="status"
        className="flex items-center gap-2 text-sm text-muted-foreground"
      >
        <LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" />
        세션을 확인하고 있습니다.
      </div>
    </section>
  )
}
