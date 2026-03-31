"use client"

import { useStream } from "@langchain/react"
import { useState, useEffect, useRef } from "react"
import { useSearchParams } from "next/navigation"
import {
  ChatContainerContent,
  ChatContainerRoot,
  ChatContainerScrollAnchor,
} from "@/components/ui/chat-container"
import { Message, MessageContent } from "@/components/ui/message"
import { Tool, ToolGroup } from "@/components/ui/tool"
import type { ToolPart } from "@/components/ui/tool"
import {
  Reasoning,
  ReasoningTrigger,
  ReasoningContent,
} from "@/components/ui/reasoning"
import {
  PromptInput,
  PromptInputTextarea,
  PromptInputActions,
  PromptInputAction,
} from "@/components/ui/prompt-input"
import { PromptSuggestion } from "@/components/ui/prompt-suggestion"
import { ModelSelector, type Model } from "@/components/ui/model-selector"
import { ScrollButton } from "@/components/ui/scroll-button"
import { Loader } from "@/components/ui/loader"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"
import {
  ArrowUpIcon,
  SquareIcon,
  CopyIcon,
  CheckIcon,
  RefreshCwIcon,
  PencilIcon,
  PlusIcon,
  ShieldCheckIcon,
  SparklesIcon,
  SearchIcon,
  BookOpenIcon,
  CodeIcon,
  WifiOffIcon,
  PlugIcon,
  XIcon,
} from "lucide-react"

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type LGMessage = any

const API_URL = process.env.NEXT_PUBLIC_AGENT_API_URL || "http://localhost:8000"

const SUGGESTIONS = [
  { text: "블로그에서 LangGraph 관련 글 찾아줘", icon: SearchIcon },
  { text: "어떤 프로젝트들을 진행했어?", icon: CodeIcon },
  { text: "AI 엔지니어로서의 경험을 알려줘", icon: BookOpenIcon },
]

// ── Message Grouping ────────────────────────────────────────

type MessageTurn =
  | { type: "human"; messages: LGMessage[] }
  | { type: "ai"; messages: LGMessage[] }

function groupMessagesIntoTurns(messages: LGMessage[]): MessageTurn[] {
  const turns: MessageTurn[] = []
  for (const msg of messages) {
    if (msg.type === "human") {
      turns.push({ type: "human", messages: [msg] })
    } else if (msg.type === "ai" || msg.type === "tool") {
      const last = turns[turns.length - 1]
      if (last?.type === "ai") {
        last.messages.push(msg)
      } else {
        turns.push({ type: "ai", messages: [msg] })
      }
    }
  }
  return turns
}

function extractTextFromMessage(msg: LGMessage): string {
  return (
    msg.text ??
    (typeof msg.content === "string"
      ? msg.content
      : Array.isArray(msg.content)
        ? msg.content
            .filter((b: { type: string }) => b.type === "text")
            .map((b: { text?: string }) => b.text ?? "")
            .join("")
        : "")
  )
}

function isTurnEmpty(turn: MessageTurn): boolean {
  if (turn.type === "human") return false
  return turn.messages.every((msg) => {
    if (msg.type === "tool") return true
    if (msg.type !== "ai") return true
    const hasToolCalls = (msg.tool_calls ?? []).length > 0
    if (hasToolCalls) return false
    const text = extractTextFromMessage(msg)
    return !text.trim()
  })
}

// ── Tool Calls Renderer ─────────────────────────────────────

function ToolCallsRenderer({
  toolCalls,
  allMessages,
  isStreaming,
}: {
  toolCalls: Array<{ id: string; name: string; args: Record<string, unknown> }>
  allMessages: LGMessage[]
  isStreaming?: boolean
}) {
  const toolParts: ToolPart[] = toolCalls.map((tc) => {
    const resultMsg = allMessages.find(
      (m: LGMessage) => m.type === "tool" && m.tool_call_id === tc.id
    )
    return {
      type: tc.name,
      state: (resultMsg
        ? "output-available"
        : isStreaming
          ? "input-streaming"
          : "input-available") as ToolPart["state"],
      input: tc.args,
      output: resultMsg?.content,
      toolCallId: tc.id,
    }
  })

  if (toolParts.length === 1) return <Tool toolPart={toolParts[0]} />
  return <ToolGroup tools={toolParts} />
}

// ── Human Message ───────────────────────────────────────────

function HumanMessageItem({
  message,
  isStreaming,
  metadata,
  onEdit,
  onBranchSwitch,
}: {
  message: LGMessage
  isStreaming?: boolean
  metadata?: any // eslint-disable-line @typescript-eslint/no-explicit-any
  onEdit?: (text: string, metadata: any) => void // eslint-disable-line @typescript-eslint/no-explicit-any
  onBranchSwitch?: (branchId: string) => void
}) {
  const [isEditing, setIsEditing] = useState(false)
  const [editText, setEditText] = useState("")
  const [copied, setCopied] = useState(false)
  const wasStreamingRef = useRef(false)
  if (isStreaming) wasStreamingRef.current = true
  const skipAnimation = wasStreamingRef.current
  const textContent = extractTextFromMessage(message)

  return (
    <div className={`group ${skipAnimation ? "" : "animate-in fade-in-0 duration-300"} flex justify-end`}>
      <div className="max-w-[80%]">
        <Message className="flex-row-reverse">
          <div className="flex-1 space-y-1">
            {isEditing ? (
              <div className="space-y-2 rounded-xl border bg-card p-3">
                <textarea
                  className="w-full resize-none rounded-lg border bg-background p-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
                  value={editText}
                  onChange={(e) => setEditText(e.target.value)}
                  rows={3}
                />
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    onClick={() => {
                      if (metadata && onEdit) onEdit(editText, metadata)
                      setIsEditing(false)
                    }}
                  >
                    Save & Rerun
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => setIsEditing(false)}>
                    Cancel
                  </Button>
                </div>
              </div>
            ) : textContent ? (
              <MessageContent className="rounded-2xl bg-foreground px-4 py-2.5 shadow-sm whitespace-pre-wrap [&_*]:!text-background [&]:!text-background">
                {textContent}
              </MessageContent>
            ) : null}
            {!isEditing && (
              <div className="flex h-7 items-center gap-0.5 justify-end opacity-0 transition-opacity duration-150 group-hover:opacity-100">
                {textContent && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="size-7 text-muted-foreground hover:text-foreground"
                    onClick={() => {
                      navigator.clipboard.writeText(textContent)
                      setCopied(true)
                      setTimeout(() => setCopied(false), 2000)
                    }}
                  >
                    {copied ? <CheckIcon className="size-3.5 text-green-500" /> : <CopyIcon className="size-3.5" />}
                  </Button>
                )}
                {metadata?.firstSeenState?.parent_checkpoint && onEdit && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="size-7 text-muted-foreground hover:text-foreground"
                    onClick={() => { setEditText(textContent); setIsEditing(true) }}
                  >
                    <PencilIcon className="size-3.5" />
                  </Button>
                )}
                {metadata?.branchOptions?.length > 1 && onBranchSwitch && (
                  <BranchSwitcher metadata={metadata} onSwitch={onBranchSwitch} />
                )}
              </div>
            )}
          </div>
        </Message>
      </div>
    </div>
  )
}

// ── AI Turn ─────────────────────────────────────────────────

function AITurnItem({
  turn,
  allMessages,
  isStreaming,
  metadata,
  onRegenerate,
  onBranchSwitch,
}: {
  turn: MessageTurn
  allMessages: LGMessage[]
  isStreaming?: boolean
  metadata?: any // eslint-disable-line @typescript-eslint/no-explicit-any
  onRegenerate?: (metadata: any) => void // eslint-disable-line @typescript-eslint/no-explicit-any
  onBranchSwitch?: (branchId: string) => void
}) {
  const [copied, setCopied] = useState(false)
  const wasStreamingRef = useRef(false)
  if (isStreaming) wasStreamingRef.current = true
  const skipAnimation = wasStreamingRef.current

  const allToolCalls: Array<{ id: string; name: string; args: Record<string, unknown> }> = []
  const textParts: string[] = []
  let reasoningText = ""

  for (const msg of turn.messages) {
    if (msg.type === "ai") {
      const tc = msg.tool_calls ?? []
      allToolCalls.push(...tc)
      const text = extractTextFromMessage(msg)
      if (text.trim()) textParts.push(text)
      const contentBlocks = msg.contentBlocks ?? (Array.isArray(msg.content) ? msg.content : undefined)
      const r = contentBlocks
        ?.filter((b: { type: string; reasoning?: string }) => b.type === "reasoning" && b.reasoning?.trim())
        .map((b: { reasoning: string }) => b.reasoning)
        .join("") ?? ""
      if (r) reasoningText += r
    }
  }

  const combinedText = textParts.join("")

  return (
    <div className={`group ${skipAnimation ? "" : "animate-in fade-in-0 duration-300"}`}>
      <div className="w-full">
        <Message>
          <div className="flex-1 space-y-1">
            {reasoningText && (
              <Reasoning isStreaming={isStreaming}>
                <ReasoningTrigger>{isStreaming ? "Thinking..." : "View reasoning"}</ReasoningTrigger>
                <ReasoningContent markdown>{reasoningText}</ReasoningContent>
              </Reasoning>
            )}
            {allToolCalls.length > 0 && (
              <ToolCallsRenderer toolCalls={allToolCalls} allMessages={allMessages} isStreaming={isStreaming && !combinedText} />
            )}
            {combinedText ? (
              <MessageContent markdown className="rounded-2xl bg-secondary/60 px-4 py-3">
                {combinedText}
              </MessageContent>
            ) : null}
            {isStreaming && !combinedText && allToolCalls.length === 0 && !reasoningText && (
              <Loader variant="typing" size="sm" />
            )}
            <div className="flex h-7 items-center gap-0.5 opacity-0 transition-opacity duration-150 group-hover:opacity-100">
              {combinedText && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="size-7 text-muted-foreground hover:text-foreground"
                  onClick={() => {
                    navigator.clipboard.writeText(combinedText)
                    setCopied(true)
                    setTimeout(() => setCopied(false), 2000)
                  }}
                >
                  {copied ? <CheckIcon className="size-3.5 text-green-500" /> : <CopyIcon className="size-3.5" />}
                </Button>
              )}
              {metadata?.firstSeenState?.parent_checkpoint && onRegenerate && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="size-7 text-muted-foreground hover:text-foreground"
                  onClick={() => onRegenerate(metadata)}
                >
                  <RefreshCwIcon className="size-3.5" />
                </Button>
              )}
              {metadata?.branchOptions?.length > 1 && onBranchSwitch && (
                <BranchSwitcher metadata={metadata} onSwitch={onBranchSwitch} />
              )}
            </div>
          </div>
        </Message>
      </div>
    </div>
  )
}

// ── Branch Switcher ─────────────────────────────────────────

function BranchSwitcher({ metadata, onSwitch }: { metadata: any; onSwitch: (id: string) => void }) { // eslint-disable-line @typescript-eslint/no-explicit-any
  const branch = metadata?.branch
  const branchOptions = metadata?.branchOptions as string[] | undefined
  if (!branchOptions || branchOptions.length <= 1) return null
  const idx = branch != null ? branchOptions.indexOf(branch) : -1
  const current = idx >= 0 ? idx + 1 : 1

  return (
    <span className="inline-flex items-center gap-0.5 rounded-full bg-muted px-1 py-0.5 text-xs font-medium text-muted-foreground">
      <Button variant="ghost" size="sm" disabled={idx <= 0} onClick={(e) => { e.stopPropagation(); onSwitch(branchOptions[idx - 1]) }} className="size-6 rounded-full text-muted-foreground hover:text-foreground">&lt;</Button>
      <span className="px-1">{current}/{branchOptions.length}</span>
      <Button variant="ghost" size="sm" disabled={idx >= branchOptions.length - 1} onClick={(e) => { e.stopPropagation(); onSwitch(branchOptions[idx + 1]) }} className="size-6 rounded-full text-muted-foreground hover:text-foreground">&gt;</Button>
    </span>
  )
}

// ── HITL Card ───────────────────────────────────────────────

function HitlCard({ interrupt, onRespond }: {
  interrupt: any // eslint-disable-line @typescript-eslint/no-explicit-any
  onRespond: (r: { decision: string; reason?: string; args?: Record<string, unknown> }) => void
}) {
  const [mode, setMode] = useState<"review" | "edit" | "reject">("review")
  const [rejectReason, setRejectReason] = useState("")
  const [editedArgs, setEditedArgs] = useState<Record<string, unknown>>({})

  const request = interrupt.value
  const actions = (request?.actionRequests ?? []) as any[] // eslint-disable-line @typescript-eslint/no-explicit-any
  const configs = (request?.reviewConfigs ?? []) as any[] // eslint-disable-line @typescript-eslint/no-explicit-any
  const config = configs[0]
  if (actions.length === 0 || !config) return null

  return (
    <div className="mx-auto my-2 w-full animate-in fade-in-0 slide-in-from-bottom-2 duration-300">
      <div className="rounded-xl border border-border bg-card shadow-sm">
        <div className="flex items-center gap-2.5 border-b border-border px-4 py-3">
          <div className="flex size-8 items-center justify-center rounded-lg bg-amber-500/10">
            <ShieldCheckIcon className="size-4 text-amber-500" />
          </div>
          <div className="flex-1">
            <h3 className="text-sm font-semibold">Review Required</h3>
            <p className="text-xs text-muted-foreground">
              {actions.length === 1
                ? `Agent wants to execute: ${actions[0].action}`
                : `Agent wants to execute ${actions.length} actions`}
            </p>
          </div>
        </div>
        <div className="divide-y divide-border">
          {actions.map((action: { action: string; args: Record<string, unknown>; description?: string }, i: number) => (
            <div key={i} className="px-4 py-3">
              <div className="flex items-center gap-2">
                <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs font-medium">{action.action}</span>
                {action.description && <span className="text-xs text-muted-foreground">{action.description}</span>}
              </div>
              {action.args && Object.keys(action.args).length > 0 && (
                <pre className="mt-2 overflow-auto rounded-lg bg-muted/50 p-2.5 font-mono text-xs text-muted-foreground">
                  {JSON.stringify(action.args, null, 2)}
                </pre>
              )}
            </div>
          ))}
        </div>
        <div className="border-t border-border px-4 py-3">
          {mode === "review" && (
            <div className="flex gap-2">
              {config.allowedDecisions.includes("approve") && (
                <Button size="sm" onClick={() => onRespond({ decision: "approve" })}>Approve</Button>
              )}
              {config.allowedDecisions.includes("reject") && (
                <Button variant="destructive" size="sm" onClick={() => setMode("reject")}>Reject</Button>
              )}
              {actions.length === 1 && config.allowedDecisions.includes("edit") && (
                <Button variant="outline" size="sm" onClick={() => { setEditedArgs(actions[0].args); setMode("edit") }}>Edit</Button>
              )}
            </div>
          )}
          {mode === "reject" && (
            <div className="space-y-3">
              <Textarea placeholder="Reason..." value={rejectReason} onChange={(e) => setRejectReason(e.target.value)} rows={2} className="min-h-0 text-sm" />
              <div className="flex gap-2">
                <Button variant="destructive" size="sm" onClick={() => onRespond({ decision: "reject", reason: rejectReason })}>Confirm</Button>
                <Button variant="ghost" size="sm" onClick={() => setMode("review")}>Back</Button>
              </div>
            </div>
          )}
          {mode === "edit" && (
            <div className="space-y-3">
              <Textarea value={JSON.stringify(editedArgs, null, 2)} onChange={(e) => { try { setEditedArgs(JSON.parse(e.target.value)) } catch { /* editing */ } }} rows={6} className="min-h-0 font-mono text-xs" />
              <div className="flex gap-2">
                <Button size="sm" onClick={() => onRespond({ decision: "edit", args: editedArgs })}>Submit</Button>
                <Button variant="ghost" size="sm" onClick={() => setMode("review")}>Back</Button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Connection Dot ──────────────────────────────────────────

function ConnectionDot({ isConnected, savedRunId, onDisconnect, onRejoin }: {
  isConnected: boolean; savedRunId: string | null; onDisconnect: () => void; onRejoin: (id: string) => void
}) {
  return (
    <div className="flex items-center gap-1.5">
      <span className={`inline-block size-1.5 rounded-full transition-colors ${isConnected ? "bg-green-500" : "bg-muted-foreground/30"}`} />
      <span className="text-[11px] text-muted-foreground">{isConnected ? "Active" : "Idle"}</span>
      {isConnected ? (
        <Button variant="ghost" size="sm" className="size-5 rounded" onClick={onDisconnect}><WifiOffIcon className="size-3" /></Button>
      ) : savedRunId ? (
        <Button variant="ghost" size="sm" className="size-5 rounded" onClick={() => onRejoin(savedRunId)}><PlugIcon className="size-3" /></Button>
      ) : null}
    </div>
  )
}

// ── Queue Display ───────────────────────────────────────────

function QueueDisplay({ queue }: { queue: any }) { // eslint-disable-line @typescript-eslint/no-explicit-any
  return (
    <div className="border-t bg-muted/30 px-4 py-2.5">
      <div className="mx-auto max-w-3xl">
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>Queued ({queue.size})</span>
          <Button variant="ghost" size="sm" className="h-auto px-1 py-0 text-xs text-destructive hover:text-destructive" onClick={() => queue.clear()}>Clear</Button>
        </div>
        <div className="mt-1.5 space-y-1">
          {queue.entries.slice(0, 3).map((entry: { id: string; values: Record<string, unknown> }) => {
            const msgs = entry.values?.messages as Array<{ content: string }> | undefined
            return (
              <div key={entry.id} className="flex items-center justify-between text-xs">
                <span className="truncate text-muted-foreground">{msgs?.[0]?.content ?? "..."}</span>
                <Button variant="ghost" size="sm" className="ml-2 size-5 shrink-0 text-muted-foreground hover:text-destructive" onClick={() => queue.cancel(entry.id)}>
                  <XIcon className="size-3" />
                </Button>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

// ── Main Chat Section ───────────────────────────────────────

export default function ChatSection() {
  const searchParams = useSearchParams()
  const [input, setInput] = useState("")
  const [savedRunId, setSavedRunId] = useState<string | null>(null)
  const [models, setModels] = useState<Model[]>([])
  const [selectedModel, setSelectedModel] = useState<string>("")

  const thread = useStream({
    apiUrl: API_URL,
    assistantId: "agent",
    messagesKey: "messages",
    onCreated(run) {
      setSavedRunId(run.run_id)
    },
  })

  const interrupt = thread.interrupt as any // eslint-disable-line @typescript-eslint/no-explicit-any
  const getMetadata = thread.getMessagesMetadata

  // Reset chat
  useEffect(() => {
    if (searchParams.get("reset") === "true") {
      thread.switchThread(null)
      setInput("")
      window.history.replaceState({}, "", "/")
    }
  }, [searchParams]) // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch models
  useEffect(() => {
    fetch(`${API_URL}/models`)
      .then((r) => r.json())
      .then((data: Model[]) => {
        setModels(data)
        if (!selectedModel) {
          const def = data.find((m) => m.is_default)
          setSelectedModel(def?.model_id ?? data[0]?.model_id ?? "")
        }
      })
      .catch(() => {})
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const submitMessage = (text: string) => {
    const newMessage = { type: "human" as const, content: text, id: `optimistic-${Date.now()}` }
    thread.submit(
      { messages: [newMessage] } as any, // eslint-disable-line @typescript-eslint/no-explicit-any
      {
        onDisconnect: "continue",
        streamResumable: true,
        ...(selectedModel ? { config: { configurable: { model: selectedModel } } } : {}),
        optimisticValues: (prev: any) => ({ // eslint-disable-line @typescript-eslint/no-explicit-any
          ...prev,
          messages: [...(prev?.messages ?? []), newMessage],
        }),
      }
    )
  }

  const handleSubmit = () => {
    if (!input.trim()) return
    submitMessage(input)
    setInput("")
  }

  const handleEdit = (text: string, metadata: any) => { // eslint-disable-line @typescript-eslint/no-explicit-any
    const checkpoint = metadata.firstSeenState?.parent_checkpoint
    if (!checkpoint) return
    const newMessage = { type: "human" as const, content: text }
    thread.submit(
      { messages: [newMessage] } as any, // eslint-disable-line @typescript-eslint/no-explicit-any
      {
        checkpoint,
        streamMode: ["values"],
        streamSubgraphs: true,
        streamResumable: true,
        optimisticValues: (prev: any) => { // eslint-disable-line @typescript-eslint/no-explicit-any
          const values = metadata.firstSeenState?.values
          if (!values) return prev
          return { ...values, messages: [...(values.messages ?? []), newMessage] }
        },
      }
    )
  }

  const handleRegenerate = (metadata: any) => { // eslint-disable-line @typescript-eslint/no-explicit-any
    const checkpoint = metadata.firstSeenState?.parent_checkpoint
    if (!checkpoint) return
    thread.submit(undefined, {
      checkpoint,
      streamMode: ["values"],
      streamSubgraphs: true,
      streamResumable: true,
    })
  }

  const isEmpty = thread.messages.length === 0 && !thread.isLoading

  return (
    <section className="w-full h-[calc(100dvh-8rem)] min-h-[400px] md:h-[70vh] md:min-h-[500px] flex flex-col">
      <div className="container mx-auto px-4 md:px-6 py-4 flex-1 flex flex-col min-h-0 overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <h2 className="text-2xl font-bold tracking-tight">AI Assistant</h2>
            <ConnectionDot
              isConnected={thread.isLoading}
              savedRunId={savedRunId}
              onDisconnect={() => thread.stop()}
              onRejoin={(id) => thread.joinStream(id)}
            />
          </div>
          <div className="flex items-center gap-1">
            {thread.queue && thread.queue.size > 0 && (
              <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
                {thread.queue.size} queued
              </span>
            )}
            <Button
              variant="ghost"
              size="sm"
              className="size-8 rounded-md"
              onClick={() => thread.switchThread(null)}
              title="New thread"
            >
              <PlusIcon className="size-4" />
            </Button>
          </div>
        </div>

        <div className="w-full max-w-7xl mx-auto flex-1 flex flex-col min-h-0">
          <div className="relative flex flex-col flex-1 overflow-hidden min-h-0">
            <ChatContainerRoot className="relative flex-1 px-4">
              <ChatContainerContent className="mx-auto max-w-3xl gap-3 py-6">
                {/* Empty state */}
                {isEmpty && (
                  <div className="flex flex-1 flex-col items-center justify-center gap-6 pt-24">
                    <div className="flex size-16 items-center justify-center rounded-2xl bg-gradient-to-br from-primary/20 to-primary/5">
                      <SparklesIcon className="size-8 text-primary" />
                    </div>
                    <div className="space-y-2 text-center">
                      <h2 className="text-2xl font-semibold tracking-tight">
                        무엇이든 물어보세요
                      </h2>
                      <p className="text-sm text-muted-foreground">
                        블로그 포스트, 프로젝트, 기술 경험에 대해 질문하세요
                      </p>
                    </div>
                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                      {SUGGESTIONS.map((s) => (
                        <PromptSuggestion
                          key={s.text}
                          className="h-auto gap-2 px-4 py-3 text-left transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md"
                          onClick={() => submitMessage(s.text)}
                        >
                          <s.icon className="size-4 shrink-0 text-primary/70" />
                          <span className="text-sm">{s.text}</span>
                        </PromptSuggestion>
                      ))}
                    </div>
                  </div>
                )}

                {/* Messages */}
                {(() => {
                  const turns = groupMessagesIntoTurns(thread.messages)
                  const filtered = turns.filter((t, i) => {
                    if (!isTurnEmpty(t)) return true
                    if (thread.isLoading && t.type === "ai" && i === turns.length - 1) return true
                    return false
                  })
                  return filtered.map((turn, idx) => {
                    const isLast = idx === filtered.length - 1
                    const firstMsg = turn.messages[0]
                    const lastMsg = turn.messages[turn.messages.length - 1]
                    const meta = getMetadata ? (getMetadata(lastMsg) as any) : null // eslint-disable-line @typescript-eslint/no-explicit-any

                    if (turn.type === "human") {
                      return (
                        <HumanMessageItem
                          key={firstMsg.id}
                          message={firstMsg}
                          isStreaming={thread.isLoading && isLast}
                          metadata={meta}
                          onEdit={handleEdit}
                          onBranchSwitch={(id) => thread.setBranch(id)}
                        />
                      )
                    }
                    return (
                      <AITurnItem
                        key={firstMsg.id}
                        turn={turn}
                        allMessages={thread.messages}
                        isStreaming={thread.isLoading && isLast}
                        metadata={meta}
                        onRegenerate={handleRegenerate}
                        onBranchSwitch={(id) => thread.setBranch(id)}
                      />
                    )
                  })
                })()}

                {/* HITL interrupt */}
                {interrupt && (
                  <HitlCard
                    interrupt={interrupt}
                    onRespond={(response) =>
                      thread.submit(null, { command: { resume: response } })
                    }
                  />
                )}

                <ChatContainerScrollAnchor />
              </ChatContainerContent>

              <ScrollButton className="absolute bottom-4 right-4 z-10 shadow-md" />
            </ChatContainerRoot>

            {/* Error */}
            {thread.error != null && (
              <div className="border-t border-destructive/30 bg-destructive/5 px-4 py-2 text-sm text-destructive">
                {String((thread.error as Error)?.message ?? thread.error)}
              </div>
            )}

            {/* Queue */}
            {thread.queue && thread.queue.size > 0 && (
              <QueueDisplay queue={thread.queue} />
            )}

            {/* Input */}
            <div className="relative bg-background px-4 pb-4 pt-2">
              {models.length > 0 && (
                <div className="mx-auto mb-1 max-w-3xl">
                  <ModelSelector
                    models={models}
                    selectedModelId={selectedModel}
                    onModelChange={setSelectedModel}
                    disabled={thread.isLoading}
                  />
                </div>
              )}
              <PromptInput
                value={input}
                onValueChange={setInput}
                onSubmit={handleSubmit}
                isLoading={thread.isLoading}
                className="mx-auto max-w-3xl shadow-sm transition-shadow focus-within:shadow-md"
              >
                <PromptInputTextarea placeholder="메시지를 입력하세요..." />
                <PromptInputActions className="justify-end px-2 pb-2">
                  {thread.isLoading ? (
                    <PromptInputAction tooltip="Stop">
                      <Button
                        variant="outline"
                        size="sm"
                        className="size-8 rounded-full"
                        onClick={(e) => { e.stopPropagation(); thread.stop() }}
                      >
                        <SquareIcon className="size-3.5" />
                      </Button>
                    </PromptInputAction>
                  ) : (
                    <PromptInputAction tooltip="Send">
                      <Button
                        size="sm"
                        className="size-8 rounded-full bg-primary transition-transform active:scale-90"
                        disabled={!input.trim()}
                        onClick={(e) => { e.stopPropagation(); handleSubmit() }}
                      >
                        <ArrowUpIcon className="size-3.5" />
                      </Button>
                    </PromptInputAction>
                  )}
                </PromptInputActions>
              </PromptInput>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
