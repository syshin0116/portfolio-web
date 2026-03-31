"use client"

import { Button } from "@/components/ui/button"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { cn } from "@/lib/utils"
import {
  CheckCircle,
  ChevronDown,
  Loader2,
  Settings,
  XCircle,
} from "lucide-react"
import { useState } from "react"

export type ToolPart = {
  type: string
  state:
    | "input-streaming"
    | "input-available"
    | "output-available"
    | "output-error"
  input?: Record<string, unknown>
  output?: unknown
  toolCallId?: string
  errorText?: string
}

export type ToolProps = {
  toolPart: ToolPart
  defaultOpen?: boolean
  className?: string
}

function formatArgsInline(args: Record<string, unknown>): string {
  const parts = Object.entries(args).map(([k, v]) => {
    const val = typeof v === "string" ? `"${v}"` : JSON.stringify(v)
    return `${k}: ${val}`
  })
  const full = parts.join(", ")
  return full.length > 80 ? full.slice(0, 77) + "..." : full
}

function formatOutput(value: unknown): string {
  if (value === null) return "null"
  if (value === undefined) return ""
  if (typeof value === "string") return value
  if (typeof value === "object") return JSON.stringify(value, null, 2)
  return String(value)
}

function StateIcon({ state }: { state: ToolPart["state"] }) {
  switch (state) {
    case "input-streaming":
      return <Loader2 className="size-3.5 animate-spin text-blue-500" />
    case "input-available":
      return <Settings className="size-3.5 text-orange-500" />
    case "output-available":
      return <CheckCircle className="size-3.5 text-green-500" />
    case "output-error":
      return <XCircle className="size-3.5 text-red-500" />
    default:
      return <Settings className="size-3.5 text-muted-foreground" />
  }
}

const Tool = ({ toolPart, defaultOpen = false, className }: ToolProps) => {
  const [isOpen, setIsOpen] = useState(defaultOpen)
  const { state, input, output } = toolPart
  const hasArgs = input && Object.keys(input).length > 0
  const outputStr = formatOutput(output)
  const hasContent =
    outputStr ||
    (state === "output-error" && toolPart.errorText) ||
    state === "input-streaming"

  return (
    <div className={cn("overflow-hidden rounded-lg border border-border bg-muted/30", className)}>
      <Collapsible open={isOpen} onOpenChange={setIsOpen}>
        <CollapsibleTrigger asChild>
          <Button
            variant="ghost"
            className="h-auto w-full justify-between rounded-b-none px-3 py-2 font-normal hover:bg-muted/50"
          >
            <div className="flex min-w-0 items-center gap-1.5">
              <StateIcon state={state} />
              <span className="font-mono text-xs font-medium">{toolPart.type}</span>
              {hasArgs && (
                <span className="truncate font-mono text-[11px] text-muted-foreground">
                  ({formatArgsInline(input)})
                </span>
              )}
            </div>
            {hasContent && (
              <ChevronDown className={cn("size-3.5 shrink-0 text-muted-foreground transition-transform", isOpen && "rotate-180")} />
            )}
          </Button>
        </CollapsibleTrigger>
        {hasContent && (
          <CollapsibleContent className={cn("border-t border-border", "data-[state=closed]:animate-collapsible-up data-[state=open]:animate-collapsible-down overflow-hidden")}>
            <div className="max-h-60 overflow-auto p-3 font-mono text-xs">
              {state === "input-streaming" && <span className="text-muted-foreground">Running...</span>}
              {state === "output-error" && toolPart.errorText && <span className="text-red-500">{toolPart.errorText}</span>}
              {outputStr && <pre className="whitespace-pre-wrap text-foreground">{outputStr}</pre>}
            </div>
          </CollapsibleContent>
        )}
      </Collapsible>
    </div>
  )
}

function ToolGroupItem({ toolPart }: { toolPart: ToolPart }) {
  const [isOpen, setIsOpen] = useState(false)
  const { state, input, output } = toolPart
  const hasArgs = input && Object.keys(input).length > 0
  const outputStr = formatOutput(output)
  const hasContent = outputStr || (state === "output-error" && toolPart.errorText)

  return (
    <div className="border-t border-border first:border-t-0">
      <button
        onClick={() => hasContent && setIsOpen(!isOpen)}
        className="flex w-full items-center gap-1.5 px-3 py-1.5 text-left hover:bg-muted/40 transition-colors"
      >
        <StateIcon state={state} />
        <span className="font-mono text-xs font-medium">{toolPart.type}</span>
        {hasArgs && (
          <span className="truncate font-mono text-[11px] text-muted-foreground">
            ({formatArgsInline(input)})
          </span>
        )}
        {hasContent && (
          <ChevronDown className={cn("ml-auto size-3 shrink-0 text-muted-foreground transition-transform", isOpen && "rotate-180")} />
        )}
      </button>
      {isOpen && hasContent && (
        <div className="max-h-48 overflow-auto border-t border-border/50 bg-muted/20 px-3 py-2 font-mono text-xs">
          {state === "output-error" && toolPart.errorText && <span className="text-red-500">{toolPart.errorText}</span>}
          {outputStr && <pre className="whitespace-pre-wrap text-foreground">{outputStr}</pre>}
        </div>
      )}
    </div>
  )
}

function ToolGroup({ tools, className }: { tools: ToolPart[]; className?: string }) {
  const [isOpen, setIsOpen] = useState(true)
  const doneCount = tools.filter((t) => t.state === "output-available" || t.state === "output-error").length
  const isRunning = tools.some((t) => t.state === "input-streaming" || t.state === "input-available")
  const allDone = doneCount === tools.length
  const hasError = tools.some((t) => t.state === "output-error")

  return (
    <div className={cn("overflow-hidden rounded-lg border border-border bg-muted/30", className)}>
      <Collapsible open={isOpen} onOpenChange={setIsOpen}>
        <CollapsibleTrigger asChild>
          <Button variant="ghost" className="h-auto w-full justify-between px-3 py-2 font-normal hover:bg-muted/50">
            <div className="flex items-center gap-1.5">
              {isRunning ? (
                <Loader2 className="size-3.5 animate-spin text-blue-500" />
              ) : hasError ? (
                <XCircle className="size-3.5 text-red-500" />
              ) : (
                <CheckCircle className="size-3.5 text-green-500" />
              )}
              <span className="text-xs font-medium">
                {isRunning
                  ? `Running ${tools.length} tools...`
                  : allDone
                    ? `${tools.length} tools executed`
                    : `${doneCount}/${tools.length} tools completed`}
              </span>
            </div>
            <ChevronDown className={cn("size-3.5 shrink-0 text-muted-foreground transition-transform", isOpen && "rotate-180")} />
          </Button>
        </CollapsibleTrigger>
        <CollapsibleContent className="data-[state=closed]:animate-collapsible-up data-[state=open]:animate-collapsible-down overflow-hidden">
          <div className="border-t border-border">
            {tools.map((t) => (
              <ToolGroupItem key={t.toolCallId ?? t.type} toolPart={t} />
            ))}
          </div>
        </CollapsibleContent>
      </Collapsible>
    </div>
  )
}

export { Tool, ToolGroup }
