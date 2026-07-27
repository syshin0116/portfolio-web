import { AgentAuthenticationError } from "./token-broker"

export type AgentErrorPhase = "connection" | "turn"
export type AgentErrorAction =
  | "sign-in"
  | "retry-connection"
  | "retry-turn"

export interface AgentErrorPresentation {
  channel: "connection" | "turn"
  kind:
    | "authentication"
    | "permission"
    | "conflict"
    | "rate-limit"
    | "server"
    | "network"
    | "lifecycle"
    | "unknown"
  message: string
  action: AgentErrorAction
  actionLabel: string
}

export interface AgentErrorRoutingState {
  connectionStatus: "connecting" | "ready" | "error"
  connectionError?: AgentErrorPresentation
  turnError?: AgentErrorPresentation
}

export class AgentLifecycleError extends Error {
  constructor() {
    super("Agent lifecycle failed")
    this.name = "AgentLifecycleError"
  }
}

export class SanitizedAgentError extends Error {
  readonly status?: number

  constructor(message: string, status?: number) {
    super(message)
    this.name = "SanitizedAgentError"
    this.status = status
  }
}

function statusFromUnknown(error: unknown): number | undefined {
  if (error instanceof AgentAuthenticationError && error.status) {
    return error.status
  }
  if (error && typeof error === "object") {
    if ("status" in error && typeof error.status === "number") {
      return error.status
    }
    if (
      "response" in error &&
      error.response &&
      typeof error.response === "object" &&
      "status" in error.response &&
      typeof error.response.status === "number"
    ) {
      return error.response.status
    }
  }
  const message =
    error instanceof Error
      ? error.message
      : typeof error === "string"
        ? error
        : ""
  const match = /\b(401|403|409|429|5\d\d)\b/.exec(message)
  return match ? Number(match[1]) : undefined
}

function isNetworkFailure(error: unknown): boolean {
  if (!(error instanceof Error)) return false
  return (
    error.name === "TypeError" ||
    /failed to fetch|network(?:error| request)?|load failed/i.test(error.message)
  )
}

/**
 * Maps raw SDK/protocol failures to bounded Korean UI copy and an explicit
 * recovery channel. Backend bodies, stack traces, tokens, and routes are never
 * returned.
 */
export function classifyAgentError(
  error: unknown,
  phase: AgentErrorPhase = "turn"
): AgentErrorPresentation {
  const status = statusFromUnknown(error)
  if (status === 401) {
    return {
      channel: "connection",
      kind: "authentication",
      message: "로그인 세션이 만료되었습니다. 다시 로그인해 주세요.",
      action: "sign-in",
      actionLabel: "다시 로그인",
    }
  }
  if (status === 403) {
    return {
      channel: "connection",
      kind: "permission",
      message: "이 계정에는 AI 실험실 사용 권한이 없습니다.",
      action: "sign-in",
      actionLabel: "로그인 화면",
    }
  }
  if (
    phase === "connection" &&
    (status === 409 ||
      status === 429 ||
      (status !== undefined && status >= 500 && status <= 599))
  ) {
    return {
      channel: "connection",
      kind:
        status === 409
          ? "conflict"
          : status === 429
            ? "rate-limit"
            : "server",
      message:
        status === 429
          ? "연결 요청이 너무 많습니다. 잠시 후 다시 연결해 주세요."
          : status === 409
            ? "에이전트 연결 요청이 충돌했습니다. 잠시 후 다시 연결해 주세요."
            : "에이전트 서버가 일시적으로 응답하지 않습니다. 잠시 후 다시 연결해 주세요.",
      action: "retry-connection",
      actionLabel: "다시 연결",
    }
  }
  if (status === 409) {
    return {
      channel: "turn",
      kind: "conflict",
      message:
        "이 대화에서 다른 실행이 진행 중입니다. 완료된 뒤 다시 시도해 주세요.",
      action: "retry-turn",
      actionLabel: "같은 대화에서 다시 시도",
    }
  }
  if (status === 429) {
    return {
      channel: "turn",
      kind: "rate-limit",
      message: "요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.",
      action: "retry-turn",
      actionLabel: "같은 대화에서 다시 시도",
    }
  }
  if (status !== undefined && status >= 500 && status <= 599) {
    return {
      channel: "turn",
      kind: "server",
      message:
        "에이전트 서버가 일시적으로 응답하지 않습니다. 잠시 후 다시 시도해 주세요.",
      action: "retry-turn",
      actionLabel: "같은 대화에서 다시 시도",
    }
  }
  if (isNetworkFailure(error)) {
    return phase === "connection"
      ? {
          channel: "connection",
          kind: "network",
          message: "네트워크 연결을 확인한 뒤 다시 연결해 주세요.",
          action: "retry-connection",
          actionLabel: "다시 연결",
        }
      : {
          channel: "turn",
          kind: "network",
          message:
            "네트워크 연결을 확인한 뒤 같은 대화에서 다시 시도해 주세요.",
          action: "retry-turn",
          actionLabel: "같은 대화에서 다시 시도",
        }
  }
  if (error instanceof AgentLifecycleError) {
    return {
      channel: "turn",
      kind: "lifecycle",
      message:
        "에이전트 실행을 완료하지 못했습니다. 같은 대화에서 다시 시도해 주세요.",
      action: "retry-turn",
      actionLabel: "같은 대화에서 다시 시도",
    }
  }
  if (phase === "connection") {
    return {
      channel: "connection",
      kind: "unknown",
      message: "에이전트 연결을 준비하지 못했습니다. 다시 연결해 주세요.",
      action: "retry-connection",
      actionLabel: "다시 연결",
    }
  }
  return {
    channel: "turn",
    kind: "unknown",
    message:
      "에이전트 실행을 완료하지 못했습니다. 같은 대화에서 다시 시도해 주세요.",
    action: "retry-turn",
    actionLabel: "같은 대화에서 다시 시도",
  }
}

/**
 * Creates the only error shape allowed to cross from SDK/Aegra internals into
 * assistant-ui. Status is retained for recovery routing; response bodies,
 * URLs, stack messages, database details, and bearer material are discarded.
 */
export function sanitizeAgentError(
  error: unknown,
  phase: AgentErrorPhase = "turn"
): SanitizedAgentError {
  const presentation = classifyAgentError(error, phase)
  return new SanitizedAgentError(
    presentation.message,
    statusFromUnknown(error)
  )
}

export function reduceAgentError(
  state: AgentErrorRoutingState,
  error: unknown,
  phase: AgentErrorPhase
): AgentErrorRoutingState {
  const presentation = classifyAgentError(error, phase)
  if (presentation.channel === "connection") {
    return {
      connectionStatus: "error",
      connectionError: presentation,
      turnError: state.turnError,
    }
  }
  return {
    ...state,
    turnError: presentation,
  }
}

export function humanizeAgentError(error: unknown): string {
  return classifyAgentError(error).message
}

export const errorStateTesting = {
  isNetworkFailure,
  statusFromUnknown,
}
