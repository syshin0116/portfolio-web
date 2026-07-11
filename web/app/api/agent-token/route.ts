import { NextResponse } from "next/server"
import { auth } from "@/lib/auth"
import { createAgentToken } from "@/lib/agent-auth"
import { isAdminEmail, isAllowedEmail } from "@/lib/allowed-user"

export async function POST() {
  const session = await auth()
  if (!isAllowedEmail(session?.user?.email)) {
    return NextResponse.json({ error: "Forbidden" }, { status: 403 })
  }
  const subject = session?.user?.id ?? session?.user?.email
  if (!subject) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 })
  }

  try {
    const scopes = isAdminEmail(session?.user?.email) ? ["admin"] : []
    const result = createAgentToken(subject, undefined, undefined, undefined, scopes)
    return NextResponse.json(result, {
      headers: { "Cache-Control": "no-store" },
    })
  } catch {
    return NextResponse.json(
      { error: "Agent authentication is not configured" },
      { status: 503 }
    )
  }
}
