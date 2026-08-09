import { NextRequest } from "next/server"
import { createRuntimeAgentTokenPostHandler } from "@/lib/agent-token-runtime"

const postAgentToken = createRuntimeAgentTokenPostHandler("anonymous")

export async function POST(request: NextRequest) {
  return postAgentToken(request)
}
