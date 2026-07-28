"use client"

import {
  Bot,
  LoaderCircle,
  RefreshCw,
  ShieldCheck,
} from "lucide-react"
import Link from "next/link"
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react"

import { Button } from "@/components/ui/button"

import { AgentRuntimeProvider } from "./agent-runtime-provider"
import { ChatShell, SignedOutChat } from "./chat-shell"
import {
  AnonymousBootstrapError,
  bootstrapAnonymousSession,
  resolveAnonymousChatConfig,
  type AnonymousCredential,
} from "./runtime/anonymous-bootstrap"
import { TurnstileWidget } from "./turnstile-widget"

type GateState =
  | { phase: "resuming" }
  | { phase: "challenge"; message?: string }
  | { phase: "verifying" }
  | { phase: "ready"; credential: AnonymousCredential }
  | { phase: "unavailable"; message: string }

function failureMessage(error: AnonymousBootstrapError): string {
  switch (error.kind) {
    case "network":
      return "네트워크 연결을 확인한 뒤 다시 시도해 주세요."
    case "rate-limited":
      return "공개 체험 요청이 잠시 많습니다. 잠시 뒤 다시 시도해 주세요."
    case "rejected":
      return "자동화 방지 확인이 만료되었거나 승인되지 않았습니다."
    case "challenge-required":
      return "자동화 방지 확인을 완료해 주세요."
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
  const config = useMemo(
    () =>
      resolveAnonymousChatConfig(
        process.env.NEXT_PUBLIC_AGENT_ANONYMOUS_ENABLED,
        process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY
      ),
    []
  )
  const [state, setState] = useState<GateState>({ phase: "resuming" })
  const [resetNonce, setResetNonce] = useState(0)
  const generationRef = useRef(0)
  const controllerRef = useRef<AbortController | undefined>(undefined)

  const runBootstrap = useCallback(async (turnstileToken?: string) => {
    controllerRef.current?.abort(
      new DOMException("Anonymous bootstrap superseded", "AbortError")
    )
    const controller = new AbortController()
    controllerRef.current = controller
    const generation = ++generationRef.current
    setState({
      phase: turnstileToken === undefined ? "resuming" : "verifying",
    })
    try {
      const credential = await bootstrapAnonymousSession({
        signal: controller.signal,
        turnstileToken,
      })
      if (
        controller.signal.aborted ||
        generation !== generationRef.current
      ) {
        return
      }
      setState({ phase: "ready", credential })
    } catch (error) {
      if (
        controller.signal.aborted ||
        generation !== generationRef.current
      ) {
        return
      }
      if (
        error instanceof AnonymousBootstrapError &&
        error.kind === "challenge-required"
      ) {
        setState({ phase: "challenge" })
        return
      }
      const sanitized =
        error instanceof AnonymousBootstrapError
          ? failureMessage(error)
          : "공개 AI 체험을 지금 연결할 수 없습니다."
      if (
        turnstileToken !== undefined &&
        error instanceof AnonymousBootstrapError &&
        error.kind === "rejected"
      ) {
        setState({ phase: "challenge", message: sanitized })
        setResetNonce((value) => value + 1)
        return
      }
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

  const handleCredentialExpired = useCallback(() => {
    generationRef.current += 1
    controllerRef.current?.abort(
      new DOMException("Anonymous credential expired", "AbortError")
    )
    setState({
      phase: "challenge",
      message: "익명 세션이 만료되었습니다. 다시 확인해 주세요.",
    })
    setResetNonce((value) => value + 1)
  }, [])

  const handleWidgetError = useCallback(() => {
    setState({
      phase: "challenge",
      message:
        "자동화 방지 확인을 불러오지 못했습니다. 차단 설정과 네트워크를 확인해 주세요.",
    })
  }, [])

  const handleWidgetExpired = useCallback(() => {
    setState({
      phase: "challenge",
      message: "자동화 방지 확인이 만료되었습니다. 다시 시도해 주세요.",
    })
  }, [])

  const handleWidgetToken = useCallback(
    (token: string) => {
      void runBootstrap(token)
    },
    [runBootstrap]
  )

  if (config.state === "disabled") return <SignedOutChat />
  if (config.state === "misconfigured") {
    return (
      <GateCard
        icon={<Bot className="size-5" />}
        title="AI 검색 실험실"
        message={config.message}
      />
    )
  }
  if (state.phase === "ready") {
    const { credential } = state
    return (
      <div className="border-t">
        <div className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 border-b bg-muted/30 px-4 py-2 text-xs text-muted-foreground">
          <span>공개 체험 · 대화 최대 14일 보관</span>
          <Link className="font-medium underline underline-offset-4" href="/login">
            소유자 로그인
          </Link>
        </div>
        <AgentRuntimeProvider
          key={credential.identity}
          identity={credential.identity}
          initialToken={credential.token}
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
        title="기존 체험 세션 확인 중"
        message="이 브라우저에서 이어 보던 대화를 안전하게 확인하고 있습니다."
      />
    )
  }
  if (state.phase === "verifying") {
    return (
      <GateCard
        icon={
          <LoaderCircle className="size-5 animate-spin motion-reduce:animate-none" />
        }
        title="공개 체험 준비 중"
        message="확인 결과를 검증하고 익명 대화를 준비하고 있습니다."
      />
    )
  }
  if (state.phase === "unavailable") {
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

  return (
    <GateCard
      icon={<ShieldCheck className="size-5" />}
      title="누구나 테스트할 수 있어요"
      message={
        state.message ??
        "한 번의 자동화 방지 확인 뒤 계정 없이 AI 검색 실험실을 사용할 수 있습니다."
      }
    >
      <div className="mt-6" aria-live="polite">
        <TurnstileWidget
          siteKey={config.siteKey}
          resetNonce={resetNonce}
          onToken={handleWidgetToken}
          onError={handleWidgetError}
          onExpired={handleWidgetExpired}
        />
      </div>
      {state.message ? (
        <Button
          className="mt-4"
          variant="outline"
          onClick={() => {
            setState({ phase: "challenge" })
            setResetNonce((value) => value + 1)
          }}
        >
          <RefreshCw className="size-4" />
          확인 다시 시도
        </Button>
      ) : null}
    </GateCard>
  )
}
