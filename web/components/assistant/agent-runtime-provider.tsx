"use client"

import {
  AssistantRuntimeProvider,
  type RemoteThreadListAdapter,
} from "@assistant-ui/react"
import { useLangGraphRuntime } from "@assistant-ui/react-langgraph"
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react"

import {
  NativeAgentClient,
  type AgentActivity,
} from "./runtime/native-client"
import { normalizeAgentApiUrl } from "./runtime/agent-config"
import {
  reduceAgentError,
  type AgentErrorRoutingState,
} from "./runtime/error-state"
import { AegraThreadAdapter } from "./runtime/thread-adapter"

const MAX_VISIBLE_ACTIVITIES = 24
type InspectionAvailability = "waiting" | "live" | "past-unavailable"

type AgentRuntimeUiState = AgentErrorRoutingState & {
  activities: readonly AgentActivity[]
  activeThreadId?: string
  inspectionAvailability: InspectionAvailability
  dismissTurnError: () => void
  retryConnection: () => void
}

const AgentRuntimeUiContext = createContext<AgentRuntimeUiState | null>(null)

export function useAgentRuntimeUi(): AgentRuntimeUiState {
  const context = useContext(AgentRuntimeUiContext)
  if (!context) {
    throw new Error("useAgentRuntimeUi must be used inside AgentRuntimeProvider")
  }
  return context
}

interface AgentRuntimeProviderProps {
  identity: string
  children: React.ReactNode
}

function resolveAgentConfig():
  | { apiUrl: string; assistantId: string }
  | { error: string } {
  const parsed = normalizeAgentApiUrl(process.env.NEXT_PUBLIC_AGENT_API_URL)
  if ("error" in parsed) return parsed
  return {
    apiUrl: parsed.apiUrl,
    assistantId:
      process.env.NEXT_PUBLIC_AGENT_ASSISTANT_ID?.trim() || "agent",
  }
}

function ConfiguredAgentRuntimeProvider({
  identity,
  apiUrl,
  assistantId,
  children,
}: AgentRuntimeProviderProps & { apiUrl: string; assistantId: string }) {
  const [activities, setActivities] = useState<AgentActivity[]>([])
  const [activeThreadId, setActiveThreadId] = useState<string>()
  const activeThreadIdRef = useRef<string | undefined>(undefined)
  const [inspectionAvailability, setInspectionAvailability] =
    useState<InspectionAvailability>("waiting")
  const [connectionAttempt, setConnectionAttempt] = useState(0)
  const [errorRouting, setErrorRouting] = useState<AgentErrorRoutingState>({
    connectionStatus: "connecting",
  })
  const handleActivity = useCallback((activity: AgentActivity) => {
    setInspectionAvailability("live")
    setActivities((current) => {
      const withoutCurrent = current.filter(
        (candidate) => candidate.id !== activity.id
      )
      return [
        ...withoutCurrent.slice(-(MAX_VISIBLE_ACTIVITIES - 1)),
        activity,
      ]
    })
    if (
      activity.namespace.length === 0 &&
      activity.kind === "lifecycle" &&
      (activity.status === "started" || activity.status === "running")
    ) {
      setErrorRouting((current) => ({
        ...current,
        turnError: undefined,
      }))
    }
  }, [])
  const handleRuntimeError = useCallback((error: unknown) => {
    setErrorRouting((current) =>
      reduceAgentError(current, error, "turn")
    )
  }, [])
  const native = useMemo(
    () =>
      new NativeAgentClient({
        apiUrl,
        assistantId,
        identity,
        onActivity: handleActivity,
        onError: handleRuntimeError,
      }),
    [apiUrl, assistantId, handleActivity, handleRuntimeError, identity]
  )
  const threadAdapter = useMemo<RemoteThreadListAdapter & AegraThreadAdapter>(
    () =>
      new AegraThreadAdapter(native.client, {
        assistantId,
        onPendingInterrupt: (threadId, pending) =>
          native.setPendingInterrupt(threadId, pending),
      }),
    [assistantId, native]
  )
  const dismissTurnError = useCallback(() => {
    setErrorRouting((current) => ({
      ...current,
      turnError: undefined,
    }))
  }, [])
  const retryConnection = useCallback(() => {
    native.tokenBroker.clear()
    setErrorRouting({
      connectionStatus: "connecting",
    })
    setConnectionAttempt((attempt) => attempt + 1)
  }, [native])
  const runtime = useLangGraphRuntime({
    stream: native.stream,
    load: async (threadId, config) => {
      const loaded = await threadAdapter.load(
        threadId,
        config?.signal ?? new AbortController().signal
      )
      if (
        activeThreadIdRef.current === undefined ||
        activeThreadIdRef.current === threadId
      ) {
        setInspectionAvailability(
          loaded.messages.length > 0 ? "past-unavailable" : "waiting"
        )
      }
      return loaded
    },
    unstable_threadListAdapter: threadAdapter,
    unstable_allowCancellation: true,
    unstable_enableMessageQueue: false,
    onThreadIdChange: (threadId) => {
      activeThreadIdRef.current = threadId
      setActiveThreadId(threadId)
      setActivities([])
      setInspectionAvailability("waiting")
      dismissTurnError()
    },
    eventHandlers: {
      onError: handleRuntimeError,
    },
  })

  useEffect(() => {
    const controller = new AbortController()
    setErrorRouting({
      connectionStatus: "connecting",
    })
    void native.tokenBroker
      .get(controller.signal)
      .then(() =>
        setErrorRouting({
          connectionStatus: "ready",
        })
      )
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setErrorRouting((current) =>
          reduceAgentError(
            current,
            error instanceof Error
              ? error
              : new Error("Agent authentication preparation failed"),
            "connection"
          )
        )
      })
    return () => {
      controller.abort()
    }
  }, [connectionAttempt, native])

  useEffect(
    () => () => {
      void native.dispose()
    },
    [native]
  )

  const context = useMemo<AgentRuntimeUiState>(
    () => ({
      ...errorRouting,
      activities,
      activeThreadId,
      inspectionAvailability,
      dismissTurnError,
      retryConnection,
    }),
    [
      activeThreadId,
      activities,
      dismissTurnError,
      errorRouting,
      inspectionAvailability,
      retryConnection,
    ]
  )

  return (
    <AgentRuntimeUiContext.Provider value={context}>
      <AssistantRuntimeProvider runtime={runtime}>
        {children}
      </AssistantRuntimeProvider>
    </AgentRuntimeUiContext.Provider>
  )
}

export function AgentRuntimeProvider({
  identity,
  children,
}: AgentRuntimeProviderProps) {
  const config = resolveAgentConfig()
  if ("error" in config) {
    return (
      <section className="flex min-h-[70svh] items-center justify-center px-6">
        <div
          role="alert"
          className="max-w-md rounded-2xl border bg-card p-6 text-center shadow-sm"
        >
          <p className="font-medium">AI 실험실을 열 수 없습니다.</p>
          <p className="mt-2 text-sm text-muted-foreground">{config.error}</p>
        </div>
      </section>
    )
  }

  return (
    <ConfiguredAgentRuntimeProvider
      identity={identity}
      apiUrl={config.apiUrl}
      assistantId={config.assistantId}
    >
      {children}
    </ConfiguredAgentRuntimeProvider>
  )
}

export const agentRuntimeProviderTesting = {
  resolveAgentConfig,
}
