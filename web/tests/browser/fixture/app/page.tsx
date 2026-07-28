import { AgentRuntimeProvider } from "../../../../components/assistant/agent-runtime-provider"
import { ChatShell } from "../../../../components/assistant/chat-shell"
import { FIXTURE_OWNER_IDENTITY } from "../anonymous-credential"

export default function BrowserFixturePage() {
  return (
    <main data-testid="production-native-runtime-fixture">
      <h1 className="sr-only">AI 검색 실험실 브라우저 검증</h1>
      <span className="sr-only" data-testid="fixture-revision">
        {process.env.GITHUB_SHA ?? "local"}
      </span>
      <AgentRuntimeProvider identity={FIXTURE_OWNER_IDENTITY}>
        <ChatShell />
      </AgentRuntimeProvider>
    </main>
  )
}
