"use client"

import Script from "next/script"
import { useEffect, useRef, useState } from "react"

export const TURNSTILE_SCRIPT_URL =
  "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit"

interface TurnstileWidgetProps {
  onError: () => void
  onExpired: () => void
  onToken: (token: string) => void
  resetNonce: number
  siteKey: string
}

export function TurnstileWidget({
  onError,
  onExpired,
  onToken,
  resetNonce,
  siteKey,
}: TurnstileWidgetProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const widgetIdRef = useRef<string | undefined>(undefined)
  const callbacksRef = useRef({ onError, onExpired, onToken })
  const [scriptReady, setScriptReady] = useState(false)

  useEffect(() => {
    callbacksRef.current = { onError, onExpired, onToken }
  }, [onError, onExpired, onToken])

  useEffect(() => {
    const container = containerRef.current
    const turnstile = window.turnstile
    if (!scriptReady || !container || !turnstile) return

    let active = true
    widgetIdRef.current = turnstile.render(container, {
      sitekey: siteKey,
      action: "agent-token",
      theme: "auto",
      size: "flexible",
      retry: "never",
      "refresh-expired": "never",
      "response-field": false,
      callback: (token) => {
        if (active) callbacksRef.current.onToken(token)
      },
      "expired-callback": () => {
        if (active) callbacksRef.current.onExpired()
      },
      "timeout-callback": () => {
        if (active) callbacksRef.current.onExpired()
      },
      "error-callback": () => {
        if (active) callbacksRef.current.onError()
        return true
      },
    })

    return () => {
      active = false
      const widgetId = widgetIdRef.current
      widgetIdRef.current = undefined
      if (widgetId !== undefined) {
        window.turnstile?.remove(widgetId)
      }
    }
  }, [scriptReady, siteKey])

  useEffect(() => {
    const widgetId = widgetIdRef.current
    if (resetNonce > 0 && widgetId !== undefined) {
      window.turnstile?.reset(widgetId)
    }
  }, [resetNonce])

  return (
    <>
      <Script
        id="cloudflare-turnstile-explicit"
        src={TURNSTILE_SCRIPT_URL}
        strategy="afterInteractive"
        referrerPolicy="no-referrer"
        onReady={() => setScriptReady(true)}
        onError={() => callbacksRef.current.onError()}
      />
      <div
        ref={containerRef}
        aria-label="자동화 방지 확인"
        className="mx-auto min-h-[65px] w-full max-w-[300px]"
      />
    </>
  )
}
