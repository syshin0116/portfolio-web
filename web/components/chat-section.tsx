"use client"

import {
  ChatContainerContent,
  ChatContainerRoot,
  ChatContainerScrollAnchor,
} from "@/components/ui/chat-container"
import {
  Message,
  MessageAction,
  MessageActions,
  MessageContent,
} from "@/components/ui/message"
import {
  PromptInput,
  PromptInputAction,
  PromptInputActions,
  PromptInputTextarea,
} from "@/components/ui/prompt-input"
import { ScrollButton } from "@/components/ui/scroll-button"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuCheckboxItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"
import {
  ArrowUp,
  Copy,
  Mic,
  Plus,
  ThumbsDown,
  ThumbsUp,
  Tag,
  FolderSearch,
  Network,
  GitBranch,
  Database,
  Info,
  Zap,
  Settings,
} from "lucide-react"
import { useState, useEffect } from "react"
import { useSearchParams } from "next/navigation"
import { streamChatResponse, ToolCall, ToolResult, SourceInfo } from "@/lib/api-client"
import { SiOpenai } from "react-icons/si"
import { Loader } from "@/components/ui/loader"
import { Tool, ToolPart } from "@/components/ui/tool"
import { Source, SourceTrigger, SourceContent } from "@/components/ui/source"

interface ChatMessage {
  id: number
  role: "user" | "assistant"
  content: string
  toolCalls?: Map<string, ToolPart>
  sources?: SourceInfo[]
}

export default function ChatSection() {
  const searchParams = useSearchParams()
  const [prompt, setPrompt] = useState("")
  const [isLoading, setIsLoading] = useState(false)
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([])

  // Model selection state
  const selectedModel = "gpt-4.1-nano"

  // Search mode state
  const [searchMode, setSearchMode] = useState<"auto" | "manual">("auto")
  const [autoAgentType, setAutoAgentType] = useState<"single" | "multi">("single")

  // RAG settings state - array of selected modes (for MANUAL mode)
  const [selectedRagModes, setSelectedRagModes] = useState<string[]>([])

  // Reset chat when reset parameter is present
  useEffect(() => {
    const reset = searchParams.get('reset')
    if (reset === 'true') {
      setChatMessages([])
      setPrompt("")
      setIsLoading(false)
      // Clear the URL parameter
      window.history.replaceState({}, '', '/')
    }
  }, [searchParams])

  const handleSubmit = async () => {
    if (!prompt.trim()) return

    const userPrompt = prompt.trim()
    setPrompt("")
    setIsLoading(true)

    // Add user message immediately
    const newUserMessage: ChatMessage = {
      id: Date.now(),
      role: "user",
      content: userPrompt,
    }

    setChatMessages((prev) => [...prev, newUserMessage])

    // Create assistant message placeholder
    const assistantMessageId = Date.now() + 1
    const assistantMessage: ChatMessage = {
      id: assistantMessageId,
      role: "assistant",
      content: "",
      toolCalls: new Map(),
      sources: [],
    }

    setChatMessages((prev) => [...prev, assistantMessage])

    // Stream the response using the API client
    await streamChatResponse({
      userMessage: userPrompt,
      searchMode,
      autoAgentType,
      ragModes: selectedRagModes,
      onChunk: (fullContent) => {
        // Update the assistant message with accumulated content
        setChatMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMessageId ? { ...m, content: fullContent } : m
          )
        )
      },
      onToolCall: (toolCall: ToolCall) => {
        // Add or update tool call
        setChatMessages((prev) =>
          prev.map((m) => {
            if (m.id === assistantMessageId) {
              const newToolCalls = new Map(m.toolCalls)
              newToolCalls.set(toolCall.id, {
                type: toolCall.name,
                state: "input-available",
                input: toolCall.args,
                toolCallId: toolCall.id,
              })
              return { ...m, toolCalls: newToolCalls }
            }
            return m
          })
        )
      },
      onToolResult: (toolResult: ToolResult) => {
        // Update tool call with result
        setChatMessages((prev) =>
          prev.map((m) => {
            if (m.id === assistantMessageId) {
              const newToolCalls = new Map(m.toolCalls)
              const existingTool = newToolCalls.get(toolResult.tool_call_id)
              if (existingTool) {
                newToolCalls.set(toolResult.tool_call_id, {
                  ...existingTool,
                  state: "output-available",
                  output: { result: toolResult.content },
                })
              }
              return { ...m, toolCalls: newToolCalls }
            }
            return m
          })
        )
      },
      onSources: (sources: SourceInfo[]) => {
        // Update assistant message with sources
        setChatMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMessageId ? { ...m, sources } : m
          )
        )
      },
      onComplete: () => {
        setIsLoading(false)
      },
      onError: (error) => {
        console.error("Error streaming response:", error)

        // Update with error message
        setChatMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMessageId
              ? {
                  ...m,
                  content: "Sorry, I encountered an error. Please try again.",
                }
              : m
          )
        )

        setIsLoading(false)
      },
    })
  }

  return (
    <section className="w-full h-[calc(100dvh-8rem)] min-h-[400px] md:h-[70vh] md:min-h-[500px] flex flex-col">
      <div className="container mx-auto px-4 md:px-6 py-4 flex-1 flex flex-col min-h-0 overflow-hidden">
        <div className="flex flex-col items-center space-y-3 text-center mb-6">
          <h2 className="text-2xl font-bold tracking-tight sm:text-3xl">
            AI 어시스턴트에게 물어보세요
          </h2>
          <p className="text-muted-foreground max-w-[600px] text-sm md:text-base">
            블로그 포스트, 프로젝트, 기술 경험에 대해 무엇이든 질문하세요
          </p>
        </div>

        <div className="w-full max-w-7xl mx-auto flex-1 flex flex-col min-h-0">
          <div className="relative flex flex-col flex-1 overflow-hidden min-h-0">
            <ChatContainerRoot className="relative flex-1 space-y-0 overflow-y-auto px-4 py-8">
              <ChatContainerContent className="space-y-8">
                {chatMessages.map((message, index) => {
                  const isAssistant = message.role === "assistant"
                  const isLastMessage = index === chatMessages.length - 1

                  return (
                    <Message
                      key={message.id}
                      className={cn(
                        isAssistant ? "justify-start" : "justify-end"
                      )}
                    >
                      {isAssistant ? (
                        <div className="group flex flex-col gap-2 max-w-[85%]">
                          {/* Tool calls display */}
                          {message.toolCalls && message.toolCalls.size > 0 && (
                            <div className="mb-4 space-y-2">
                              {Array.from(message.toolCalls.values()).map((toolPart) => (
                                <Tool
                                  key={toolPart.toolCallId}
                                  toolPart={toolPart}
                                  defaultOpen={false}
                                />
                              ))}
                            </div>
                          )}

                          {/* Message content */}
                          {message.content ? (
                            <MessageContent
                              className="prose max-w-none"
                              markdown
                            >
                              {message.content}
                            </MessageContent>
                          ) : !message.toolCalls || message.toolCalls.size === 0 ? (
                            <div className="rounded-lg bg-secondary p-2">
                              <Loader variant="text-shimmer" text="Thinking" size="md" />
                            </div>
                          ) : null}

                          {/* Sources display */}
                          {message.sources && message.sources.length > 0 && (
                            <div className="mt-3 flex flex-wrap gap-2">
                              {message.sources.map((source, idx) => (
                                <Source key={idx} href={source.url}>
                                  <SourceTrigger 
                                    label={source.title}
                                    showFavicon={true}
                                  />
                                  <SourceContent
                                    title={source.title}
                                    description={source.summary || ""}
                                  />
                                </Source>
                              ))}
                            </div>
                          )}

                          <MessageActions
                            className={cn(
                              "-ml-2.5 flex gap-0 opacity-0 transition-opacity duration-150 group-hover:opacity-100",
                              isLastMessage && "opacity-100"
                            )}
                          >
                            <MessageAction tooltip="Copy" delayDuration={100}>
                              <Button
                                variant="ghost"
                                size="icon"
                                className="rounded-full"
                              >
                                <Copy />
                              </Button>
                            </MessageAction>
                            <MessageAction tooltip="Upvote" delayDuration={100}>
                              <Button
                                variant="ghost"
                                size="icon"
                                className="rounded-full"
                              >
                                <ThumbsUp />
                              </Button>
                            </MessageAction>
                            <MessageAction tooltip="Downvote" delayDuration={100}>
                              <Button
                                variant="ghost"
                                size="icon"
                                className="rounded-full"
                              >
                                <ThumbsDown />
                              </Button>
                            </MessageAction>
                          </MessageActions>
                        </div>
                      ) : (
                        <MessageContent className="bg-primary text-primary-foreground max-w-[85%]">
                          {message.content}
                        </MessageContent>
                      )}
                    </Message>
                  )
                })}
                <ChatContainerScrollAnchor />
              </ChatContainerContent>

              <div className="absolute left-1/2 -translate-x-1/2 bottom-4 z-10">
                <ScrollButton
                  className="bg-background/80 hover:bg-background/90 backdrop-blur-sm shadow-lg border border-border/50"
                  variant="outline"
                  size="icon"
                />
              </div>
            </ChatContainerRoot>

            <div className="sticky bottom-0 left-0 right-0 shrink-0 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 border-t border-border/40 p-4">
              <div className="max-w-5xl mx-auto">
                <PromptInput
                  isLoading={isLoading}
                  value={prompt}
                  onValueChange={setPrompt}
                  onSubmit={handleSubmit}
                  className="border-input bg-background relative z-10 w-full rounded-3xl border p-0 pt-1 shadow-sm"
                >
                <div className="flex flex-col">
                  <PromptInputTextarea
                    placeholder="Ask anything..."
                    className="min-h-[44px] pt-3 pl-4 text-base leading-[1.3]"
                  />

                  <PromptInputActions className="mt-3 flex w-full items-center justify-between gap-2 px-3 pb-3">
                    <div className="flex items-center gap-2 flex-wrap">
                      <PromptInputAction tooltip="Add attachment">
                        <Button
                          variant="outline"
                          size="icon"
                          className="size-9 rounded-full"
                        >
                          <Plus size={18} />
                        </Button>
                      </PromptInputAction>

                      {/* Unified Search Configuration */}
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button
                            variant="outline"
                            className="flex items-center gap-1.5 rounded-full cursor-pointer"
                          >
                            <Database size={18} />
                            <span className="hidden sm:inline text-xs text-muted-foreground">RAG Mode:</span>
                            <span className="hidden sm:inline text-xs font-medium">{searchMode === "auto" ? "AUTO" : "MANUAL"}</span>
                            {searchMode === "auto" ? (
                              <span className="hidden sm:inline ml-1 text-xs text-muted-foreground">
                                ({autoAgentType === "single" ? "Single" : "Multi"})
                              </span>
                            ) : selectedRagModes.length > 0 ? (
                              <span className="ml-1 rounded-full bg-primary px-2 py-0.5 text-xs text-primary-foreground">
                                {selectedRagModes.length}
                              </span>
                            ) : null}
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="start" className="w-72">
                          <DropdownMenuLabel>Search Configuration</DropdownMenuLabel>
                          <DropdownMenuSeparator />
                          <TooltipProvider>
                            {/* AUTO Mode Section */}
                            <DropdownMenuCheckboxItem
                              checked={searchMode === "auto"}
                              onCheckedChange={(checked) => {
                                if (checked) setSearchMode("auto")
                              }}
                              onSelect={(e) => e.preventDefault()}
                              className="cursor-pointer"
                            >
                              <Zap size={16} className="mr-2" />
                              <span className="flex-1">AUTO Mode</span>
                              <Tooltip delayDuration={0}>
                                <TooltipTrigger asChild>
                                  <div
                                    className="ml-2"
                                    onClick={(e) => e.stopPropagation()}
                                    onMouseDown={(e) => e.stopPropagation()}
                                  >
                                    <Info size={14} className="text-muted-foreground cursor-help" />
                                  </div>
                                </TooltipTrigger>
                                <TooltipContent side="right" className="max-w-[240px]" sideOffset={10}>
                                  <p className="text-balance">AI automatically selects the best search strategy for your query</p>
                                </TooltipContent>
                              </Tooltip>
                            </DropdownMenuCheckboxItem>

                            {searchMode === "auto" && (
                              <div className="ml-8 mt-1 mb-1 space-y-1">
                                <DropdownMenuCheckboxItem
                                  checked={autoAgentType === "single"}
                                  onCheckedChange={(checked) => {
                                    if (checked) setAutoAgentType("single")
                                  }}
                                  onSelect={(e) => e.preventDefault()}
                                  className="cursor-pointer text-sm"
                                >
                                  <span className="flex-1">Single Agent (tool selection)</span>
                                  <Tooltip delayDuration={0}>
                                    <TooltipTrigger asChild>
                                      <div
                                        className="ml-1"
                                        onClick={(e) => e.stopPropagation()}
                                        onMouseDown={(e) => e.stopPropagation()}
                                      >
                                        <Info size={12} className="text-muted-foreground cursor-help" />
                                      </div>
                                    </TooltipTrigger>
                                    <TooltipContent side="right" className="max-w-[200px] text-xs" sideOffset={10}>
                                      <p className="text-balance">One AI agent with multiple tools to choose from</p>
                                    </TooltipContent>
                                  </Tooltip>
                                </DropdownMenuCheckboxItem>
                                <DropdownMenuCheckboxItem
                                  checked={autoAgentType === "multi"}
                                  onCheckedChange={(checked) => {
                                    if (checked) setAutoAgentType("multi")
                                  }}
                                  onSelect={(e) => e.preventDefault()}
                                  className="cursor-pointer text-sm"
                                >
                                  <span className="flex-1">Multi Agent (agent routing)</span>
                                  <Tooltip delayDuration={0}>
                                    <TooltipTrigger asChild>
                                      <div
                                        className="ml-1"
                                        onClick={(e) => e.stopPropagation()}
                                        onMouseDown={(e) => e.stopPropagation()}
                                      >
                                        <Info size={12} className="text-muted-foreground cursor-help" />
                                      </div>
                                    </TooltipTrigger>
                                    <TooltipContent side="right" className="max-w-[200px] text-xs" sideOffset={10}>
                                      <p className="text-balance">Multiple specialized AI agents routed based on query type</p>
                                    </TooltipContent>
                                  </Tooltip>
                                </DropdownMenuCheckboxItem>
                              </div>
                            )}

                            <DropdownMenuSeparator className="my-1" />

                            {/* MANUAL Mode Section */}
                            <DropdownMenuCheckboxItem
                              checked={searchMode === "manual"}
                              onCheckedChange={(checked) => {
                                if (checked) setSearchMode("manual")
                              }}
                              onSelect={(e) => e.preventDefault()}
                              className="cursor-pointer"
                            >
                              <Settings size={16} className="mr-2" />
                              <span className="flex-1">MANUAL Mode</span>
                              <Tooltip delayDuration={0}>
                                <TooltipTrigger asChild>
                                  <div
                                    className="ml-2"
                                    onClick={(e) => e.stopPropagation()}
                                    onMouseDown={(e) => e.stopPropagation()}
                                  >
                                    <Info size={14} className="text-muted-foreground cursor-help" />
                                  </div>
                                </TooltipTrigger>
                                <TooltipContent side="right" className="max-w-[200px]" sideOffset={10}>
                                  <p className="text-balance">Manually select specific RAG modes to use</p>
                                </TooltipContent>
                              </Tooltip>
                            </DropdownMenuCheckboxItem>

                            {searchMode === "manual" && (
                              <div className="ml-8 mt-1 space-y-1">
                                <DropdownMenuCheckboxItem
                                  checked={selectedRagModes.includes("metadata_search")}
                                  onCheckedChange={(checked) => {
                                    setSelectedRagModes(prev =>
                                      checked
                                        ? [...prev, "metadata_search"]
                                        : prev.filter(m => m !== "metadata_search")
                                    )
                                  }}
                                  onSelect={(e) => e.preventDefault()}
                                  className="cursor-pointer text-sm"
                                >
                                  <Tag size={14} className="mr-2" />
                                  <span className="flex-1">Metadata Search</span>
                                  <Tooltip delayDuration={0}>
                                    <TooltipTrigger asChild>
                                      <div
                                        className="ml-1"
                                        onClick={(e) => e.stopPropagation()}
                                        onMouseDown={(e) => e.stopPropagation()}
                                      >
                                        <Info size={12} className="text-muted-foreground cursor-help" />
                                      </div>
                                    </TooltipTrigger>
                                    <TooltipContent side="right" className="max-w-[240px] text-xs" sideOffset={10}>
                                      <p className="text-balance">Search through blog post metadata including titles, tags, categories, and dates</p>
                                    </TooltipContent>
                                  </Tooltip>
                                </DropdownMenuCheckboxItem>

                                <DropdownMenuCheckboxItem
                                  checked={selectedRagModes.includes("filesystem_search")}
                                  onCheckedChange={(checked) => {
                                    setSelectedRagModes(prev =>
                                      checked
                                        ? [...prev, "filesystem_search"]
                                        : prev.filter(m => m !== "filesystem_search")
                                    )
                                  }}
                                  onSelect={(e) => e.preventDefault()}
                                  className="cursor-pointer text-sm"
                                >
                                  <FolderSearch size={14} className="mr-2" />
                                  <span className="flex-1">Filesystem Search</span>
                                  <Tooltip delayDuration={0}>
                                    <TooltipTrigger asChild>
                                      <div
                                        className="ml-1"
                                        onClick={(e) => e.stopPropagation()}
                                        onMouseDown={(e) => e.stopPropagation()}
                                      >
                                        <Info size={12} className="text-muted-foreground cursor-help" />
                                      </div>
                                    </TooltipTrigger>
                                    <TooltipContent side="right" className="max-w-[240px] text-xs" sideOffset={10}>
                                      <p className="text-balance">Search through project files and code repositories using file system structure</p>
                                    </TooltipContent>
                                  </Tooltip>
                                </DropdownMenuCheckboxItem>

                                <DropdownMenuCheckboxItem
                                  checked={selectedRagModes.includes("vector_search")}
                                  onCheckedChange={(checked) => {
                                    setSelectedRagModes(prev =>
                                      checked
                                        ? [...prev, "vector_search"]
                                        : prev.filter(m => m !== "vector_search")
                                    )
                                  }}
                                  onSelect={(e) => e.preventDefault()}
                                  className="cursor-pointer text-sm"
                                >
                                  <Network size={14} className="mr-2" />
                                  <span className="flex-1">Vector Search</span>
                                  <Tooltip delayDuration={0}>
                                    <TooltipTrigger asChild>
                                      <div
                                        className="ml-1"
                                        onClick={(e) => e.stopPropagation()}
                                        onMouseDown={(e) => e.stopPropagation()}
                                      >
                                        <Info size={12} className="text-muted-foreground cursor-help" />
                                      </div>
                                    </TooltipTrigger>
                                    <TooltipContent side="right" className="max-w-[240px] text-xs" sideOffset={10}>
                                      <p className="text-balance">Semantic search using AI embeddings to find contextually relevant content</p>
                                    </TooltipContent>
                                  </Tooltip>
                                </DropdownMenuCheckboxItem>

                                <DropdownMenuCheckboxItem
                                  checked={selectedRagModes.includes("graph_search")}
                                  onCheckedChange={(checked) => {
                                    setSelectedRagModes(prev =>
                                      checked
                                        ? [...prev, "graph_search"]
                                        : prev.filter(m => m !== "graph_search")
                                    )
                                  }}
                                  onSelect={(e) => e.preventDefault()}
                                  className="cursor-pointer text-sm"
                                >
                                  <GitBranch size={14} className="mr-2" />
                                  <span className="flex-1">Graph Search</span>
                                  <Tooltip delayDuration={0}>
                                    <TooltipTrigger asChild>
                                      <div
                                        className="ml-1"
                                        onClick={(e) => e.stopPropagation()}
                                        onMouseDown={(e) => e.stopPropagation()}
                                      >
                                        <Info size={12} className="text-muted-foreground cursor-help" />
                                      </div>
                                    </TooltipTrigger>
                                    <TooltipContent side="right" className="max-w-[240px] text-xs" sideOffset={10}>
                                      <p className="text-balance">Knowledge graph-based search to find related concepts and relationships</p>
                                    </TooltipContent>
                                  </Tooltip>
                                </DropdownMenuCheckboxItem>
                              </div>
                            )}
                          </TooltipProvider>
                        </DropdownMenuContent>
                      </DropdownMenu>

                      <PromptInputAction tooltip={`Model: ${selectedModel} (selection coming soon)`}>
                        <Button
                          variant="outline"
                          className="flex items-center gap-1.5 rounded-full"
                          disabled={true}
                        >
                          <SiOpenai size={18} />
                          <span className="hidden sm:inline text-xs text-muted-foreground">LLM Model:</span>
                          <span className="hidden sm:inline text-xs font-medium">{selectedModel}</span>
                        </Button>
                      </PromptInputAction>
                    </div>
                    <div className="flex items-center gap-2">
                      <PromptInputAction tooltip="Voice input">
                        <Button
                          variant="outline"
                          size="icon"
                          className="size-9 rounded-full"
                        >
                          <Mic size={18} />
                        </Button>
                      </PromptInputAction>

                      <Button
                        size="icon"
                        disabled={!prompt.trim() || isLoading}
                        onClick={handleSubmit}
                        className="size-9 rounded-full"
                      >
                        {!isLoading ? (
                          <ArrowUp size={18} />
                        ) : (
                          <span className="size-3 rounded-xs bg-white" />
                        )}
                      </Button>
                    </div>
                  </PromptInputActions>
                </div>
              </PromptInput>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
