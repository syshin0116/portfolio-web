const CONTENT_IMAGE_OVERRIDES = new Map([
  [
    "https://langchain-ai.github.io/langgraph/agents/assets/react_agent_graphs/1111.svg",
    "/images/blog/react-agent-graph.svg",
  ],
])

export function applyContentImageOverrides(html: string): string {
  let rewritten = html

  for (const [source, replacement] of CONTENT_IMAGE_OVERRIDES) {
    rewritten = rewritten.replaceAll(source, replacement)
  }

  return rewritten
}
