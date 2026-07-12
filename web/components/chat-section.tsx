"use client"

import { useStream } from "@langchain/react"
import { useState, useEffect, useMemo, useRef } from "react"
import { useSearchParams } from "next/navigation"
import Link from "next/link"
import { useAuth } from "@/contexts/AuthContext"
import {
  ChatContainerContent,
  ChatContainerRoot,
  ChatContainerScrollAnchor,
} from "@/components/ui/chat-container"
import { Message, MessageContent } from "@/components/ui/message"
import { Tool, ToolGroup } from "@/components/ui/tool"
import type { ToolPart } from "@/components/ui/tool"
import { Steps, StepsTrigger, StepsContent, StepsItem } from "@/components/ui/steps"
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
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"
import {
  ArrowUpIcon,
  SquareIcon,
  CopyIcon,
  CheckIcon,
  CheckCircle,
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
  DatabaseIcon,
  TextSearchIcon,
  TagIcon,
  NetworkIcon,
  ListIcon,
  FileTextIcon,
  Loader2,
  Settings,
  ChevronDown,
} from "lucide-react"

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type LGMessage = any

type StreamHandle = ReturnType<typeof useStream> & {
  getMessagesMetadata: (message: any, index?: number) => any // eslint-disable-line @typescript-eslint/no-explicit-any
  switchThread: (newThreadId: string | null) => void
  joinStream: (runId: string, lastEventId?: string) => Promise<void>
  setBranch: (branch: string) => void
  queue?: {
    size: number
    entries: Array<{ id: string; values: Record<string, unknown> }>
    cancel: (id: string) => Promise<boolean>
    clear: () => Promise<void>
  }
  submit: (values: any, options?: any) => Promise<void> // eslint-disable-line @typescript-eslint/no-explicit-any
  interrupt: any // eslint-disable-line @typescript-eslint/no-explicit-any
}

const API_URL = process.env.NEXT_PUBLIC_AGENT_API_URL || "http://localhost:8000"

const SUGGESTIONS = [
  { text: "블로그에서 LangGraph 관련 글 찾아줘", icon: SearchIcon },
  { text: "어떤 프로젝트들을 진행했어?", icon: CodeIcon },
  { text: "AI 엔지니어로서의 경험을 알려줘", icon: BookOpenIcon },
]

const SEARCH_SKILLS = [
  { id: "keyword_search", label: "Keyword", icon: TextSearchIcon, description: "ripgrep 기반 정확한 키워드/정규식 매칭. 코드, 에러 메시지, 정확한 이름 검색." },
  { id: "semantic_search", label: "BM25", icon: DatabaseIcon, description: "BM25 랭킹 + 한국어 형태소 분석. 자연어 질문, 주제 탐색." },
  { id: "metadata_filter", label: "Metadata", icon: TagIcon, description: "태그, 카테고리(AI/Dev/Study/...), 날짜 범위로 필터링." },
  { id: "graph_traverse", label: "Graph", icon: NetworkIcon, description: "위키링크([[link]]) 기반 연관 글 탐색." },
  { id: "list_posts", label: "List", icon: ListIcon, description: "최신 글 목록 조회. 카테고리별 브라우징." },
  { id: "read_post", label: "Read", icon: FileTextIcon, description: "특정 글 전체 내용 읽기." },
] as const

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

// ── Tool Classification ──────────────────────────────────────

const SEARCH_TOOL_NAMES = new Set([
  "keyword_search", "semantic_search", "metadata_filter",
  "graph_traverse", "list_posts", "read_post",
])

const FILESYSTEM_TOOL_NAMES = new Set([
  "ls", "read_file", "glob", "grep", "write_file", "edit_file",
])

function isCollapsibleTool(name: string): boolean {
  return SEARCH_TOOL_NAMES.has(name) || FILESYSTEM_TOOL_NAMES.has(name)
}

function getToolSummary(toolParts: ToolPart[]): string {
  const searchCount = toolParts.filter(t => SEARCH_TOOL_NAMES.has(t.type)).length
  const fsCount = toolParts.filter(t => FILESYSTEM_TOOL_NAMES.has(t.type)).length
  const otherCount = toolParts.length - searchCount - fsCount

  const doneCount = toolParts.filter(t => t.state === "output-available").length
  const isRunning = toolParts.some(t => t.state === "input-streaming")

  const parts: string[] = []
  if (searchCount > 0) parts.push(`${searchCount} search${searchCount > 1 ? "es" : ""}`)
  if (fsCount > 0) parts.push(`${fsCount} file op${fsCount > 1 ? "s" : ""}`)
  if (otherCount > 0) parts.push(`${otherCount} other`)

  const action = isRunning ? "Running" : "Ran"
  const progress = isRunning ? ` (${doneCount}/${toolParts.length} done)` : ""
  return `${action} ${parts.join(", ")}${progress}`
}

// ── Expandable Step Item ─────────────────────────────────────

function ExpandableStepItem({ toolPart: tp }: { toolPart: ToolPart }) {
  const [expanded, setExpanded] = useState(false)
  const hasOutput = tp.state === "output-available" && tp.output
  const outputStr = hasOutput
    ? (typeof tp.output === "string" ? tp.output : JSON.stringify(tp.output, null, 2))
    : null

  return (
    <StepsItem className={cn(
      tp.state === "output-available" ? "text-foreground" : "text-muted-foreground"
    )}>
      <button
        className="flex items-center gap-1.5 w-full text-left hover:bg-muted/40 rounded px-1 -mx-1 py-0.5 transition-colors"
        onClick={() => outputStr && setExpanded(!expanded)}
      >
        {tp.state === "input-streaming" && <Loader2 className="size-3 animate-spin text-blue-500 shrink-0" />}
        {tp.state === "output-available" && <CheckCircle className="size-3 text-green-500 shrink-0" />}
        {tp.state === "input-available" && <Settings className="size-3 text-orange-500 shrink-0" />}
        <span className="font-mono text-xs">{tp.type}</span>
        {tp.input && Object.keys(tp.input).length > 0 && (
          <span className="text-xs text-muted-foreground truncate max-w-[200px]">
            ({Object.values(tp.input).map(v => typeof v === "string" ? v : JSON.stringify(v)).join(", ")})
          </span>
        )}
        {outputStr && (
          <ChevronDown className={cn(
            "size-3 ml-auto shrink-0 text-muted-foreground transition-transform",
            expanded && "rotate-180"
          )} />
        )}
      </button>
      {expanded && outputStr && (
        <div className="mt-1 ml-4.5 max-h-48 overflow-auto rounded bg-muted/30 border border-border/50 p-2">
          <pre className="text-xs text-muted-foreground whitespace-pre-wrap break-words">{outputStr}</pre>
        </div>
      )}
    </StepsItem>
  )
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

  // Split into collapsible (search/fs) and non-collapsible
  const collapsible = toolParts.filter(t => isCollapsibleTool(t.type))
  const nonCollapsible = toolParts.filter(t => !isCollapsibleTool(t.type))

  return (
    <div className="space-y-2">
      {/* Collapsed group for search/filesystem operations */}
      {collapsible.length > 0 && (
        <Steps defaultOpen={collapsible.some(t => t.state === "input-streaming")}>
          <StepsTrigger
            leftIcon={
              collapsible.every(t => t.state === "output-available")
                ? <CheckCircle className="size-4 text-green-500" />
                : collapsible.some(t => t.state === "input-streaming")
                  ? <Loader2 className="size-4 animate-spin text-blue-500" />
                  : <SearchIcon className="size-4 text-muted-foreground" />
            }
          >
            {getToolSummary(collapsible)}
          </StepsTrigger>
          <StepsContent>
            {collapsible.map((tp) => (
              <ExpandableStepItem key={tp.toolCallId} toolPart={tp} />
            ))}
          </StepsContent>
        </Steps>
      )}

      {/* Non-collapsible tools shown individually */}
      {nonCollapsible.length === 1 && <Tool toolPart={nonCollapsible[0]} />}
      {nonCollapsible.length > 1 && <ToolGroup tools={nonCollapsible} />}
    </div>
  )
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
  const { user, loading: authLoading } = useAuth()
  const authenticatedUserId = user?.id ?? user?.email
  const [input, setInput] = useState("")
  const [savedRunId, setSavedRunId] = useState<string | null>(null)
  const [models, setModels] = useState<Model[]>([])
  const [selectedModel, setSelectedModel] = useState<string>("")
  const [selectedSkills, setSelectedSkills] = useState<Set<string>>(new Set())
  const [agentToken, setAgentToken] = useState<string | null>(null)
  const [agentAuthError, setAgentAuthError] = useState<string | null>(null)
  const agentHeaders = useMemo<Record<string, string>>(() => {
    const headers: Record<string, string> = {}
    if (agentToken) headers.Authorization = `Bearer ${agentToken}`
    return headers
  }, [agentToken])

  const thread = useStream({
    apiUrl: API_URL,
    assistantId: "agent",
    defaultHeaders: agentHeaders,
    messagesKey: "messages",
    onCreated(run) {
      const runInfo = run as any // eslint-disable-line @typescript-eslint/no-explicit-any
      setSavedRunId(runInfo.runId ?? runInfo.run_id)
    },
  }) as unknown as StreamHandle

  const interrupt = thread.interrupt as any // eslint-disable-line @typescript-eslint/no-explicit-any
  const getMetadata = thread.getMessagesMetadata

  useEffect(() => {
    if (!authenticatedUserId) {
      setAgentToken(null)
      setAgentAuthError(null)
      return
    }

    let cancelled = false
    const refreshToken = async () => {
      try {
        const response = await fetch("/api/agent-token", { method: "POST" })
        if (!response.ok) throw new Error("Agent authentication failed")
        const data = (await response.json()) as { token: string }
        if (!cancelled) {
          setAgentToken(data.token)
          setAgentAuthError(null)
        }
      } catch {
        if (!cancelled) {
          setAgentToken(null)
          setAgentAuthError("Agent authentication failed")
        }
      }
    }

    void refreshToken()
    const timer = window.setInterval(refreshToken, 10 * 60 * 1000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [authenticatedUserId])

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
    if (!agentToken) return
    fetch(`${API_URL}/models`, { headers: agentHeaders })
      .then((response) => {
        if (!response.ok) throw new Error("Failed to load models")
        return response
      })
      .then((r) => r.json())
      .then((data: Model[]) => {
        setModels(data)
        setSelectedModel((current) => {
          if (current) return current
          const def = data.find((m) => m.is_default)
          return def?.model_id ?? data[0]?.model_id ?? ""
        })
      })
      .catch(() => {})
  }, [agentHeaders, agentToken])

  const submitMessage = (text: string) => {
    if (!agentToken) return
    const newMessage = { type: "human" as const, content: text, id: `optimistic-${Date.now()}` }
    const configurable: Record<string, unknown> = {}
    if (selectedModel) configurable.model = selectedModel

    // Build messages: optionally prepend skill restriction as system message
    const messages: Array<Record<string, string>> = []
    if (selectedSkills.size > 0) {
      const skills = [...selectedSkills].join(", ")
      messages.push({
        type: "system",
        content: `[User selected skills: ${skills}] Use ONLY these search tools. Do not use other search tools unless these cannot answer the query.`,
        id: `skill-hint-${Date.now()}`,
      })
    }
    messages.push(newMessage)

    thread.submit(
      { messages } as any, // eslint-disable-line @typescript-eslint/no-explicit-any
      {
        onDisconnect: "continue",
        streamResumable: true,
        ...(Object.keys(configurable).length > 0 ? { config: { configurable } } : {}),
        optimisticValues: (prev: any) => ({ // eslint-disable-line @typescript-eslint/no-explicit-any
          ...prev,
          messages: [...(prev?.messages ?? []), newMessage], // only show human message optimistically
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
        streamMode: ["values", "messages-tuple"],
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
      streamMode: ["values", "messages-tuple"],
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
                    {agentToken ? (
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
                    ) : !authLoading && !user ? (
                      <Button asChild>
                        <Link href="/login">Sign in to chat</Link>
                      </Button>
                    ) : null}
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
            {agentAuthError && (
              <div className="border-t border-destructive/30 bg-destructive/5 px-4 py-2 text-sm text-destructive">
                {agentAuthError}
              </div>
            )}

            {/* Queue */}
            {thread.queue && thread.queue.size > 0 && (
              <QueueDisplay queue={thread.queue} />
            )}

            {/* Input */}
            <div className="relative bg-background px-4 pb-4 pt-2">
              <div className="mx-auto mb-2 max-w-3xl flex items-center gap-2 flex-wrap">
                {models.length > 0 && (
                  <ModelSelector
                    models={models}
                    selectedModelId={selectedModel}
                    onModelChange={setSelectedModel}
                    disabled={thread.isLoading}
                  />
                )}
                <div className="h-4 w-px bg-border" />
                <TooltipProvider delayDuration={0}>
                  {SEARCH_SKILLS.map((tool) => {
                    const isSelected = selectedSkills.has(tool.id)
                    const Icon = tool.icon
                    return (
                      <Tooltip key={tool.id}>
                        <TooltipTrigger asChild>
                          <Button
                            variant={isSelected ? "default" : "outline"}
                            size="sm"
                            className={cn(
                              "h-7 gap-1.5 rounded-full text-xs transition-all",
                              isSelected && "shadow-sm"
                            )}
                            onClick={() => {
                              setSelectedSkills(prev => {
                                const next = new Set(prev)
                                if (next.has(tool.id)) next.delete(tool.id)
                                else next.add(tool.id)
                                return next
                              })
                            }}
                          >
                            <Icon className="size-3" />
                            <span className="hidden sm:inline">{tool.label}</span>
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent side="top" className="max-w-[200px]">
                          <p className="font-medium">{tool.label}</p>
                          <p className="text-xs text-muted-foreground">{tool.description}</p>
                        </TooltipContent>
                      </Tooltip>
                    )
                  })}
                </TooltipProvider>
                {selectedSkills.size > 0 && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 px-2 text-xs text-muted-foreground"
                    onClick={() => setSelectedSkills(new Set())}
                  >
                    Clear
                  </Button>
                )}
              </div>
              {!authLoading && !user ? (
                <div className="mx-auto flex max-w-3xl justify-center py-3">
                  <Button asChild>
                    <Link href="/login">Sign in to chat</Link>
                  </Button>
                </div>
              ) : (
                <PromptInput
                  value={input}
                  onValueChange={setInput}
                  onSubmit={handleSubmit}
                  isLoading={thread.isLoading}
                  className="mx-auto max-w-3xl shadow-sm transition-shadow focus-within:shadow-md"
                >
                  <PromptInputTextarea
                    placeholder={agentToken ? "메시지를 입력하세요..." : "Connecting..."}
                    disabled={!agentToken}
                  />
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
                        disabled={!agentToken || !input.trim()}
                        onClick={(e) => { e.stopPropagation(); handleSubmit() }}
                      >
                        <ArrowUpIcon className="size-3.5" />
                      </Button>
                    </PromptInputAction>
                  )}
                </PromptInputActions>
                </PromptInput>
              )}
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
