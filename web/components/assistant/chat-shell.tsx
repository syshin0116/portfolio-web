"use client"

import {
  ComposerPrimitive,
  ErrorPrimitive,
  MessagePrimitive,
  ThreadListItemPrimitive,
  ThreadListPrimitive,
  ThreadPrimitive,
  type ReasoningMessagePartProps,
  type TextMessagePartProps,
  type ToolCallMessagePartProps,
  useMessage,
  useThreadListItem,
  useThreadListItemRuntime,
} from "@assistant-ui/react"
import {
  useLangGraphInterruptState,
  useLangGraphSendCommand,
} from "@assistant-ui/react-langgraph"
import {
  Archive,
  ArrowDown,
  ArrowUp,
  Bot,
  BrainCircuit,
  Check,
  ChevronRight,
  CircleStop,
  Clock3,
  History,
  ListTree,
  LoaderCircle,
  Menu,
  Pencil,
  Plus,
  RotateCcw,
  Search,
  Sparkles,
  ToolCase,
  UserRound,
  WifiOff,
} from "lucide-react"
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
import ReactMarkdown, { type Components } from "react-markdown"
import remarkBreaks from "remark-breaks"
import remarkGfm from "remark-gfm"

import { Button } from "@/components/ui/button"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet"
import { cn } from "@/lib/utils"

import { useAgentRuntimeUi } from "./agent-runtime-provider"
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
  {
    prompt: "블로그에서 LangGraph 관련 글을 찾아줘",
    icon: Search,
  },
  {
    prompt: "최근 AI 프로젝트에서 어떤 문제를 해결했어?",
    icon: Sparkles,
  },
  {
    prompt: "Aegra와 RAG 평가 계획을 요약해줘",
    icon: BrainCircuit,
  },
] as const

const MARKDOWN_PLUGINS = [remarkGfm, remarkBreaks]
const MARKDOWN_COMPONENTS = {
  a: ({ children, href }) => (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="font-medium underline underline-offset-4"
    >
      {children}
    </a>
  ),
  code: ({ children }) => (
    <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[0.9em]">
      {children}
    </code>
  ),
  pre: ({ children }) => (
    <pre className="my-3 overflow-x-auto rounded-xl border bg-muted/60 p-4 text-sm">
      {children}
    </pre>
  ),
} satisfies Components

const MarkdownText = memo(function MarkdownText({
  text,
}: TextMessagePartProps) {
  return (
    <ReactMarkdown
      remarkPlugins={MARKDOWN_PLUGINS}
      components={MARKDOWN_COMPONENTS}
    >
      {text}
    </ReactMarkdown>
  )
})

const ReasoningPart = memo(function ReasoningPart({
  status,
}: ReasoningMessagePartProps) {
  const running = status.type === "running"
  return (
    <div className="my-2 flex items-center gap-2 rounded-lg border border-dashed px-3 py-2 text-xs text-muted-foreground">
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
  status,
}: ToolCallMessagePartProps) {
  const running =
    status.type === "running" ||
    status.type === "requires-action"
  const query = toolQueryFromArgs(argsText)
  return (
    <details className="my-2 rounded-xl border bg-muted/30" open={running}>
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-sm font-medium">
        <ToolCase
          className={cn(
            "size-4",
            running && "animate-pulse motion-reduce:animate-none"
          )}
        />
        <span className="min-w-0 flex-1 truncate">{toolName}</span>
        <span className="text-xs font-normal text-muted-foreground">
          {running
            ? "실행 중"
            : status.type === "incomplete"
              ? "완료하지 못함"
              : "완료"}
        </span>
        <ChevronRight className="size-3.5 transition-transform motion-reduce:transition-none [[open]>&]:rotate-90" />
      </summary>
      <div className="space-y-2 border-t px-3 py-3 text-xs">
        <p className="text-muted-foreground">
          질의: {query ?? "서버 미제공"}
        </p>
        <p className="text-muted-foreground">
          검증된 결과 세부 정보는 실행 상세 패널에만 표시됩니다.
        </p>
      </div>
    </details>
  )
})

function toolQueryFromArgs(argsText: string): string | undefined {
  if (!argsText) return undefined
  try {
    const parsed = JSON.parse(argsText) as unknown
    if (
      parsed &&
      typeof parsed === "object" &&
      !Array.isArray(parsed) &&
      "query" in parsed &&
      typeof parsed.query === "string" &&
      parsed.query.trim() &&
      parsed.query.length <= 1_000
    ) {
      return parsed.query.trim()
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
    <section
      aria-label="답변 인용 출처"
      className="mt-4 rounded-xl border bg-muted/30 p-3 text-xs"
    >
      <p className="mb-2 font-medium">인용 출처</p>
      <SourceItems sources={sources} />
    </section>
  )
}

function ChatMessage() {
  const role = useMessage((message) => message.role)
  const rawSources = useMessage(
    (message) => message.metadata.custom.sources
  )
  const sources = useMemo(
    () => inspectionSourcesFromUnknown(rawSources),
    [rawSources]
  )
  if (role === "system") return null

  return (
    <MessagePrimitive.Root
      className={cn(
        "group mx-auto flex w-full max-w-3xl gap-3 px-4 py-4 md:px-6",
        role === "user" && "justify-end"
      )}
    >
      {role === "assistant" ? (
        <div className="mt-1 flex size-8 shrink-0 items-center justify-center rounded-full border bg-card shadow-sm">
          <Bot className="size-4" />
        </div>
      ) : null}
      <div
        className={cn(
          "min-w-0 text-sm leading-7",
          role === "assistant" && "max-w-[calc(100%-2.75rem)] flex-1",
          role === "user" &&
            "max-w-[85%] rounded-2xl rounded-br-md bg-primary px-4 py-2.5 text-primary-foreground"
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
    </MessagePrimitive.Root>
  )
}

function EmptyConversation() {
  return (
    <ThreadPrimitive.Empty>
      <div className="mx-auto flex min-h-full max-w-3xl flex-col items-center justify-center px-6 py-14 text-center">
        <div className="mb-5 flex size-14 items-center justify-center rounded-2xl border bg-card shadow-sm">
          <BrainCircuit className="size-7" />
        </div>
        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground">
          RAG evaluation lab
        </p>
        <h1 className="mt-3 text-balance text-2xl font-semibold tracking-tight md:text-3xl">
          블로그를 아는 AI가 아니라,
          <br />
          검색 방법을 비교하는 실험실입니다.
        </h1>
        <p className="mt-4 max-w-xl text-pretty text-sm leading-6 text-muted-foreground">
          현재 선택된 검색기를 실제 블로그 글에 적용해 답합니다. 답변은 틀릴 수
          있으며, 대화와 도구 실행 기록은 품질 평가에 사용될 수 있습니다.
        </p>
        <div className="mt-8 grid w-full gap-2 sm:grid-cols-3">
          {SUGGESTIONS.map(({ prompt, icon: Icon }) => (
            <ThreadPrimitive.Suggestion
              key={prompt}
              prompt={prompt}
              send
              className="group flex min-h-24 flex-col items-start justify-between rounded-xl border bg-card p-3 text-left text-sm transition-colors motion-reduce:transition-none hover:bg-muted"
            >
              <Icon className="size-4 text-muted-foreground transition-colors motion-reduce:transition-none group-hover:text-foreground" />
              <span>{prompt}</span>
            </ThreadPrimitive.Suggestion>
          ))}
        </div>
      </div>
    </ThreadPrimitive.Empty>
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
    try {
      // Resume carries only the user's bounded decision/input. The opaque
      // interrupt value remains protocol state and is never echoed back.
      await sendCommand({ resume: normalized })
    } catch {
      setResumeError(
        "응답을 보내지 못했습니다. 승인 요청은 유지되었습니다. 다시 시도해 주세요."
      )
    } finally {
      setSending(false)
      restoreComposerFocus()
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
        className="mt-3 flex gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          void respond(response)
        }}
      >
        <label className="sr-only" htmlFor="interrupt-response">
          수정해서 재개할 응답
        </label>
        <input
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
          className="min-w-0 flex-1 rounded-lg border bg-background px-3 py-2 text-sm"
        />
        <Button
          type="submit"
          size="sm"
          variant="secondary"
          disabled={!response.trim() || sending}
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

function InterruptCard() {
  const interrupt = useLangGraphInterruptState()
  if (!interrupt) return null
  const projection = readRuntimeInterruptProjection(interrupt.value)
  return (
    <InterruptResponseCard
      key={interruptViewKey(interrupt)}
      projection={projection}
    />
  )
}

function Composer() {
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

  return (
    <div className="border-t bg-background/95 px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-3 backdrop-blur md:px-6">
      {runtimeUi.connectionStatus === "connecting" ? (
        <div
          role="status"
          className="mx-auto mb-2 flex max-w-3xl items-center gap-2 text-xs text-muted-foreground"
        >
          <LoaderCircle className="size-3.5 animate-spin motion-reduce:animate-none" />
          안전한 연결을 준비하고 있습니다.
        </div>
      ) : null}
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
        className="mx-auto flex max-w-3xl items-end gap-2 rounded-2xl border bg-card p-2 shadow-sm focus-within:ring-2 focus-within:ring-ring/20"
        onSubmitCapture={(event) => {
          const value = composerInputRef.current?.value ?? ""
          if (
            value.length > MAX_COMPOSER_CODE_UNITS ||
            composerEncoder.encode(value).byteLength >
              MAX_COMPOSER_UTF8_BYTES
          ) {
            event.preventDefault()
            event.stopPropagation()
            setComposerError(COMPOSER_LIMIT_ERROR)
            setTimeout(() => composerInputRef.current?.focus(), 0)
            return
          }
          setComposerError(undefined)
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
            ready ? "블로그와 프로젝트에 관해 물어보세요…" : "연결 중…"
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
          className="max-h-48 min-h-10 min-w-0 flex-1 resize-none bg-transparent px-2 py-2 text-sm outline-none placeholder:text-muted-foreground"
        />
        <ThreadPrimitive.If running>
          <ComposerPrimitive.Cancel
            aria-label="응답 중지"
            className="flex size-9 shrink-0 items-center justify-center rounded-full border bg-background transition-colors motion-reduce:transition-none hover:bg-muted"
          >
            <CircleStop className="size-4" />
          </ComposerPrimitive.Cancel>
        </ThreadPrimitive.If>
        <ThreadPrimitive.If running={false}>
          <ComposerPrimitive.Send
            aria-label="메시지 보내기"
            className="flex size-9 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground transition-transform motion-reduce:transition-none hover:scale-105 motion-reduce:hover:scale-100 disabled:opacity-40"
          >
            <ArrowUp className="size-4" />
          </ComposerPrimitive.Send>
        </ThreadPrimitive.If>
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
      <p className="mx-auto mt-2 max-w-3xl text-center text-[11px] text-muted-foreground">
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
        <ThreadPrimitive.Messages components={{ Message: ChatMessage }} />
        <ThreadPrimitive.If running>
          <div
            role="status"
            aria-live="polite"
            className="mx-auto flex w-full max-w-3xl items-center gap-3 px-6 py-3 text-sm text-muted-foreground"
          >
            <LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" />
            검색하고 답변을 구성하고 있습니다.
          </div>
        </ThreadPrimitive.If>
        <ThreadPrimitive.ScrollToBottom
          aria-label="최신 메시지로 이동"
          className="sticky bottom-3 left-1/2 z-10 flex size-9 -translate-x-1/2 items-center justify-center rounded-full border bg-background shadow-md"
        >
          <ArrowDown className="size-4" />
        </ThreadPrimitive.ScrollToBottom>
      </ThreadPrimitive.Viewport>
      <InterruptCard />
      <Composer />
    </ThreadPrimitive.Root>
  )
}

function ThreadListItem() {
  const item = useThreadListItem()
  const runtime = useThreadListItemRuntime()
  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState(item.title ?? "")
  const [renameError, setRenameError] = useState<string>()
  const [renaming, setRenaming] = useState(false)
  const renameInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!editing) {
      setTitle(item.title ?? "")
      setRenameError(undefined)
    }
  }, [editing, item.title])

  const submitRename = async (event: FormEvent) => {
    event.preventDefault()
    const normalized = title.trim()
    if (!normalized || renaming) return
    setRenameError(undefined)
    setRenaming(true)
    try {
      await runtime.rename(normalized)
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
          <label className="sr-only" htmlFor={`title-${item.id}`}>
            대화 제목
          </label>
          <input
            ref={renameInputRef}
            id={`title-${item.id}`}
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
              renameError ? `title-error-${item.id}` : undefined
            }
            aria-invalid={renameError !== undefined}
            className="w-full rounded border bg-background px-2 py-1.5 text-sm"
          />
          {renameError ? (
            <p
              id={`title-error-${item.id}`}
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
            {item.title || "제목을 만드는 중…"}
          </span>
          {item.lastMessageAt ? (
            <span className="mt-0.5 block text-[11px] text-muted-foreground">
              {item.lastMessageAt.toLocaleDateString("ko-KR")}
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
      {item.status === "archived" ? (
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
    <ThreadListPrimitive.Root className="flex h-full min-h-0 flex-col">
      <div className="border-b p-3">
        <ThreadListPrimitive.New className="flex w-full items-center gap-2 rounded-lg border bg-card px-3 py-2 text-sm font-medium shadow-sm transition-colors motion-reduce:transition-none hover:bg-muted data-[active=true]:bg-primary data-[active=true]:text-primary-foreground">
          <Plus className="size-4" />
          새 대화
        </ThreadListPrimitive.New>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        <p className="px-2 pb-2 pt-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          최근 대화
        </p>
        <ThreadListPrimitive.Items
          components={{ ThreadListItem }}
        />
        <ThreadListPrimitive.LoadMore className="mt-2 w-full rounded-lg px-3 py-2 text-xs text-muted-foreground hover:bg-muted">
          대화 더 보기
        </ThreadListPrimitive.LoadMore>
        <div className="mt-5 border-t pt-4">
          <p className="flex items-center gap-2 px-2 pb-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            <Archive className="size-3" />
            보관됨
          </p>
          <ThreadListPrimitive.Items
            archived
            components={{ ThreadListItem }}
          />
        </div>
      </div>
      <div className="border-t p-3 text-[11px] leading-5 text-muted-foreground">
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
                  질문을 보내면 정본 inspection 이벤트가 도착한 동안 검색
                  방법과 근거가 여기에 표시됩니다.
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
        <Button variant="ghost" size="icon" aria-label="대화 목록 열기">
          <Menu className="size-4" />
        </Button>
      </SheetTrigger>
      <SheetContent side="left" className="w-[min(88vw,320px)] p-0">
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
        <Button variant="ghost" size="icon" aria-label="실행 상세 열기">
          <ListTree className="size-4" />
        </Button>
      </SheetTrigger>
      <SheetContent side="right" className="w-[min(88vw,360px)] p-0">
        <SheetHeader className="sr-only">
          <SheetTitle>실행 상세</SheetTitle>
          <SheetDescription>
            검색, 도구, 중첩 작업 진행 상태입니다.
          </SheetDescription>
        </SheetHeader>
        <ActivityPanel />
      </SheetContent>
    </Sheet>
  )
}

function MobileControls() {
  return (
    <div className="flex items-center gap-1 md:hidden">
      <ThreadSheet />
      <DetailSheet />
    </div>
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
      className="flex h-[calc(100svh-4.5rem)] min-h-0 flex-col border-t bg-muted/20 supports-[height:100dvh]:h-[calc(100dvh-4.5rem)]"
    >
      <OnlineStatus />
      <div className="flex items-center justify-between border-b bg-background px-4 py-2 md:hidden">
        <div>
          <p className="text-sm font-medium">AI 검색 실험실</p>
          <p className="text-[11px] text-muted-foreground">Aegra APv2</p>
        </div>
        <MobileControls />
      </div>
      <div className="hidden items-center justify-between border-b bg-background px-4 py-2 md:flex xl:hidden">
        <div>
          <p className="text-sm font-medium">AI 검색 실험실</p>
          <p className="text-[11px] text-muted-foreground">
            실행 상세는 오른쪽 버튼에서 확인할 수 있습니다.
          </p>
        </div>
        <DetailSheet />
      </div>
      <div className="grid min-h-0 flex-1 md:grid-cols-[280px_minmax(0,1fr)] xl:grid-cols-[280px_minmax(0,1fr)_320px]">
        <aside
          aria-label="대화 목록"
          className="hidden min-h-0 border-r bg-muted/30 md:block"
        >
          <ThreadRail />
        </aside>
        <Conversation />
        <aside
          aria-label="실행 상세"
          className="hidden min-h-0 border-l bg-muted/20 xl:block"
        >
          <ActivityPanel />
        </aside>
      </div>
    </section>
  )
}

export function SignedOutChat() {
  return (
    <section className="flex min-h-[70svh] items-center justify-center border-t bg-muted/20 px-6 py-16">
      <div className="max-w-lg rounded-3xl border bg-card p-8 text-center shadow-sm">
        <div className="mx-auto flex size-12 items-center justify-center rounded-2xl bg-primary text-primary-foreground">
          <UserRound className="size-5" />
        </div>
        <h1 className="mt-5 text-2xl font-semibold tracking-tight">
          AI 검색 실험실
        </h1>
        <p className="mt-3 text-sm leading-6 text-muted-foreground">
          WEB-A 단계에서는 소유자 계정으로만 연결됩니다. 누구나 테스트하는
          익명 Turnstile 경로는 격리·사용량 제한이 포함된 WEB-B에서 열립니다.
        </p>
        <Button asChild className="mt-6">
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
