"use client"

import {
  Bot,
  LoaderCircle,
  RefreshCw,
} from "lucide-react"
import Link from "next/link"
import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react"

import { Button } from "@/components/ui/button"
import { ANONYMOUS_AGENT_TOKEN_INTENT } from "@/lib/agent-token-intent"

import { AgentRuntimeProvider } from "./agent-runtime-provider"
import { ChatShell, SignedOutChat } from "./chat-shell"
import {
  AnonymousBootstrapError,
  bootstrapAnonymousSession,
  resolveAnonymousChatConfig,
  type AnonymousCredential,
} from "./runtime/anonymous-bootstrap"

type GateState =
  | { phase: "resuming" }
  | {
      phase: "ready"
      credential: AnonymousCredential
      generation: number
    }
  | { phase: "unavailable"; message: string }

function failureMessage(error: AnonymousBootstrapError): string {
  switch (error.kind) {
    case "network":
      return "네트워크 연결을 확인한 뒤 다시 시도해 주세요."
    case "rate-limited":
      return "공개 체험 요청이 잠시 많습니다. 잠시 뒤 다시 시도해 주세요."
    case "unavailable":
      return "공개 AI 체험을 지금 연결할 수 없습니다."
  }
}

function GateCard({
  children,
  icon,
  message,
  title,
}: {
  children?: React.ReactNode
  icon: React.ReactNode
  message: string
  title: string
}) {
  return (
    <section className="flex min-h-[70svh] items-center justify-center border-t bg-muted/20 px-6 py-16">
      <div className="w-full max-w-lg rounded-3xl border bg-card p-6 text-center shadow-sm sm:p-8">
        <div className="mx-auto flex size-12 items-center justify-center rounded-2xl bg-primary text-primary-foreground">
          {icon}
        </div>
        <h1 className="mt-5 break-keep text-xl font-semibold tracking-tight sm:text-2xl">
          {title}
        </h1>
        <p className="mt-3 text-sm leading-6 text-muted-foreground">
          {message}
        </p>
        {children}
        <p className="mt-6 text-xs leading-5 text-muted-foreground">
          대화는 이 브라우저에서 이어지며 최대 14일 뒤 삭제됩니다. AI
          답변은 부정확할 수 있고 공개 체험에는 요청·일일 비용 한도가
          적용됩니다.
        </p>
        <Button asChild variant="link" className="mt-2">
          <Link href="/login">소유자 계정으로 로그인</Link>
        </Button>
      </div>
    </section>
  )
}

export function AnonymousChatGate() {
  const config = resolveAnonymousChatConfig(
    process.env.NEXT_PUBLIC_AGENT_ANONYMOUS_ENABLED
  )
  const [state, setState] = useState<GateState>({ phase: "resuming" })
  const generationRef = useRef(0)
  const controllerRef = useRef<AbortController | undefined>(undefined)

  const runBootstrap = useCallback(async () => {
    controllerRef.current?.abort(
      new DOMException("Anonymous bootstrap superseded", "AbortError")
    )
    const controller = new AbortController()
    controllerRef.current = controller
    const generation = ++generationRef.current
    setState({ phase: "resuming" })
    try {
      const credential = await bootstrapAnonymousSession({
        signal: controller.signal,
      })
      if (
        controller.signal.aborted ||
        generation !== generationRef.current
      ) {
        return
      }
      setState({ phase: "ready", credential, generation })
    } catch (error) {
      if (
        controller.signal.aborted ||
        generation !== generationRef.current
      ) {
        return
      }
      const sanitized =
        error instanceof AnonymousBootstrapError
          ? failureMessage(error)
          : "공개 AI 체험을 지금 연결할 수 없습니다."
      setState({ phase: "unavailable", message: sanitized })
    }
  }, [])

  useEffect(() => {
    if (config.state !== "enabled") return
    void runBootstrap()
    return () => {
      generationRef.current += 1
      controllerRef.current?.abort(
        new DOMException("Anonymous bootstrap unmounted", "AbortError")
      )
    }
  }, [config.state, runBootstrap])

  const readyGeneration =
    state.phase === "ready" ? state.generation : undefined
  const handleCredentialExpired = useCallback(() => {
    if (
      readyGeneration !== undefined &&
      generationRef.current === readyGeneration
    ) {
      void runBootstrap()
    }
  }, [readyGeneration, runBootstrap])

  if (config.state === "disabled") return <SignedOutChat />
  if (state.phase === "ready") {
    const { credential } = state
    return (
      <div className="border-t">
        <div className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 border-b bg-muted/30 px-4 py-2 text-xs text-muted-foreground">
          <span>공개 체험 · Luna · 대화 최대 14일 보관</span>
          <Link className="font-medium underline underline-offset-4" href="/login">
            소유자 로그인
          </Link>
        </div>
        <AgentRuntimeProvider
          key={credential.identity}
          identity={credential.identity}
          initialToken={credential.token}
          tokenIntent={ANONYMOUS_AGENT_TOKEN_INTENT}
          onAuthenticationExpired={handleCredentialExpired}
        >
          <ChatShell />
        </AgentRuntimeProvider>
      </div>
    )
  }
  if (state.phase === "resuming") {
    return (
      <GateCard
        icon={
          <LoaderCircle className="size-5 animate-spin motion-reduce:animate-none" />
        }
        title="공개 체험 준비 중"
        message="이 브라우저에서 사용할 익명 대화를 안전하게 준비하고 있습니다."
      />
    )
  }
  return (
    <GateCard
      icon={<Bot className="size-5" />}
      title="공개 체험에 연결하지 못했습니다"
      message={state.message}
    >
      <Button
        className="mt-6"
        variant="outline"
        onClick={() => void runBootstrap()}
      >
        <RefreshCw className="size-4" />
        다시 연결
      </Button>
    </GateCard>
  )
}
