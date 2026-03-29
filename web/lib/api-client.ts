import { Client } from "@langchain/langgraph-sdk"

const API_URL = "https://portfolio-ai-194616966170.asia-northeast3.run.app"

// Singleton pattern for client instance
// Client provides async methods by default
let clientInstance: Client | null = null

export function getApiClient(): Client {
  if (!clientInstance) {
    clientInstance = new Client({
      apiUrl: API_URL,
    })
  }
  return clientInstance
}

export interface ToolCall {
  name: string
  args: Record<string, unknown>
  id: string
  type?: string
}

export interface ToolResult {
  name: string
  content: string
  tool_call_id: string
}

export interface SourceInfo {
  url: string
  title: string
  summary?: string
}

interface StreamMessage {
  content?: string | unknown
  type?: string
  tool_calls?: Array<{
    name: string
    args: Record<string, unknown>
    id: string
    type?: string
  }>
  name?: string
  tool_call_id?: string
}

export interface StreamChatOptions {
  userMessage: string
  searchMode?: "auto" | "manual"
  autoAgentType?: "single" | "multi"
  ragModes?: string[]
  onChunk?: (content: string) => void
  onToolCall?: (toolCall: ToolCall) => void
  onToolResult?: (toolResult: ToolResult) => void
  onSources?: (sources: SourceInfo[]) => void
  onComplete?: (fullContent: string) => void
  onError?: (error: Error) => void
}

// Parse URLs from tool result content
export function parseSourcesFromContent(content: string): SourceInfo[] {
  const sources: SourceInfo[] = []
  
  // Match URL patterns like "URL: https://..."
  const urlRegex = /URL:\s*(https?:\/\/[^\s\n]+)/gi
  const titleRegex = /Title:\s*([^\n]+)/gi
  const summaryRegex = /Summary:\s*([^\n]+)/gi
  
  const urlMatches = Array.from(content.matchAll(urlRegex))
  const titleMatches = Array.from(content.matchAll(titleRegex))
  const summaryMatches = Array.from(content.matchAll(summaryRegex))
  
  // Combine matches
  for (let i = 0; i < urlMatches.length; i++) {
    const url = urlMatches[i][1]
    const title = titleMatches[i]?.[1]?.trim() || new URL(url).hostname
    const summary = summaryMatches[i]?.[1]?.trim()
    
    sources.push({
      url,
      title,
      summary,
    })
  }
  
  return sources
}

export async function streamChatResponse({
  userMessage,
  searchMode = "auto",
  autoAgentType = "single",
  ragModes = [],
  onChunk,
  onToolCall,
  onToolResult,
  onSources,
  onComplete,
  onError,
}: StreamChatOptions): Promise<string> {
  try {
    const client = getApiClient()

    // Prepare config based on search mode
    const config: Record<string, unknown> = {
      searchMode,
    }

    if (searchMode === "auto") {
      config.autoAgentType = autoAgentType
    } else {
      config.ragModes = ragModes
    }

    const stream = client.runs.stream(
      null, // thread_id (stateless)
      "agent",
      {
        input: { messages: [{ role: "user", content: userMessage }] },
        config,
        streamMode: "messages",
      }
    )

    let fullContent = ""
    const allSources: SourceInfo[] = []

    for await (const chunk of stream) {
      if (chunk.event === "messages/partial" && chunk.data) {
        const messageChunks = Array.isArray(chunk.data)
          ? chunk.data
          : [chunk.data]

        for (const msg of messageChunks) {
          // Handle tool calls - properly typed streaming message
          const streamMsg = msg as StreamMessage

          if (streamMsg.tool_calls && streamMsg.tool_calls.length > 0) {
            for (const toolCall of streamMsg.tool_calls) {
              if (toolCall.name && toolCall.id) {
                // Parse args if it's a string (streaming chunks)
                let parsedArgs = toolCall.args
                if (typeof toolCall.args === "string") {
                  try {
                    parsedArgs = JSON.parse(toolCall.args)
                  } catch {
                    parsedArgs = { raw: toolCall.args }
                  }
                }

                onToolCall?.({
                  name: toolCall.name,
                  args: parsedArgs || {},
                  id: toolCall.id,
                  type: toolCall.type,
                })
              }
            }
          }

          // Handle tool results
          if (streamMsg.type === "tool" && streamMsg.name && streamMsg.tool_call_id) {
            const content = typeof streamMsg.content === "string"
              ? streamMsg.content
              : JSON.stringify(streamMsg.content)

            onToolResult?.({
              name: streamMsg.name,
              content,
              tool_call_id: streamMsg.tool_call_id,
            })

            // Parse sources from tool results
            const sources = parseSourcesFromContent(content)
            if (sources.length > 0) {
              allSources.push(...sources)
              onSources?.(allSources)
            }
          }

          // Handle regular content
          if (msg.content && streamMsg.type !== "tool") {
            const content = typeof msg.content === "string"
              ? msg.content
              : ""
            fullContent += content
            onChunk?.(fullContent)
          }
        }
      }
    }

    onComplete?.(fullContent)
    return fullContent
  } catch (error) {
    const err = error instanceof Error ? error : new Error(String(error))
    onError?.(err)
    throw err
  }
}
