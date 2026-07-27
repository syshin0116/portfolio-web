import { randomUUID } from "node:crypto"
import { NextRequest } from "next/server"
import { auth } from "@/lib/auth"
import { createAgentToken } from "@/lib/agent-auth"
import {
  createAgentTokenPostHandler,
} from "@/lib/agent-token-route"
import { SITEVERIFY_TIMEOUT_MS } from "@/lib/anonymous-agent-token"
import { isAdminEmail, isAllowedEmail } from "@/lib/allowed-user"

const postAgentToken = createAgentTokenPostHandler({
  authenticate: async () => auth(),
  createToken: createAgentToken,
  isAllowed: isAllowedEmail,
  isAdmin: isAdminEmail,
  env: process.env,
  fetchImpl: (input, init) => fetch(input, init),
  nowSeconds: () => Math.floor(Date.now() / 1_000),
  randomUUID,
  nodeEnv: process.env.NODE_ENV,
  turnstileTimeoutMs: SITEVERIFY_TIMEOUT_MS,
})

export async function POST(request: NextRequest) {
  return postAgentToken(request)
}
