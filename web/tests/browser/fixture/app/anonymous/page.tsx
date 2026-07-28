import { AnonymousChatGate } from "../../../../../components/assistant/anonymous-chat-gate"

export default function AnonymousBrowserFixturePage() {
  return (
    <main data-testid="public-anonymous-runtime-fixture">
      <h1 className="sr-only">공개 AI 검색 실험실 브라우저 검증</h1>
      <AnonymousChatGate />
    </main>
  )
}
