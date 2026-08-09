import { randomUUID } from "node:crypto"
import { checkBotId } from "botid/server"
import { auth } from "@/lib/auth"
import { createAgentToken } from "@/lib/agent-auth"
import { createAgentTokenPostHandler } from "@/lib/agent-token-route"
import { isAdminEmail, isAllowedEmail } from "@/lib/allowed-user"

export function createRuntimeAgentTokenPostHandler(
  mode: "anonymous" | "owner"
) {
  return createAgentTokenPostHandler(
    {
      authenticate: async () => auth(),
      checkBot: () =>
        checkBotId({ advancedOptions: { checkLevel: "basic" } }),
      createToken: createAgentToken,
      isAllowed: isAllowedEmail,
      isAdmin: isAdminEmail,
      env: process.env,
      nowSeconds: () => Math.floor(Date.now() / 1_000),
      randomUUID,
      nodeEnv: process.env.NODE_ENV,
    },
    mode
  )
}
