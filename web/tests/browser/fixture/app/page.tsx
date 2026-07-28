import { AgentRuntimeProvider } from "../../../../components/assistant/agent-runtime-provider"
import { ChatShell } from "../../../../components/assistant/chat-shell"

export default function BrowserFixturePage() {
  return (
    <main data-testid="production-native-runtime-fixture">
      <h1 className="sr-only">AI 검색 실험실 브라우저 검증</h1>
      <span className="sr-only" data-testid="fixture-revision">
        {process.env.GITHUB_SHA ?? "local"}
      </span>
      <AgentRuntimeProvider identity="browser-fixture-user">
        <ChatShell />
      </AgentRuntimeProvider>
    </main>
  )
}
