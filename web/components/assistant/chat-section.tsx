"use client"

import { useAuth } from "@/contexts/AuthContext"

import { AgentRuntimeProvider } from "./agent-runtime-provider"
import { AnonymousChatGate } from "./anonymous-chat-gate"
import {
  ChatLoading,
  ChatShell,
} from "./chat-shell"

export default function ChatSection() {
  const { user, loading } = useAuth()
  const identity = user?.id ?? user?.email

  if (loading) return <ChatLoading />
  if (!identity) return <AnonymousChatGate />

  // The key is intentional: an auth-subject transition destroys the complete
  // assistant runtime, thread list, token cache, and active APv2 stream.
  return (
    <AgentRuntimeProvider key={identity} identity={identity}>
      <ChatShell />
    </AgentRuntimeProvider>
  )
}
