import { auth } from "@/lib/auth"
import { NextRequest, NextResponse } from "next/server"

async function markdownForAgents(request: NextRequest) {
  const accept = request.headers.get("accept") || "";
  if (
    request.nextUrl.pathname === "/" &&
    accept.includes("text/markdown") &&
    !accept.includes("text/html")
  ) {
    const llmsUrl = new URL("/llms.txt", request.url);
    return NextResponse.rewrite(llmsUrl, {
      headers: { "Content-Type": "text/markdown" },
    });
  }
  return null;
}

export async function proxy(request: NextRequest) {
  // Check Markdown for Agents content negotiation first
  const mdResponse = await markdownForAgents(request);
  if (mdResponse) return mdResponse;

  // Then run auth middleware
  return (auth as any)(request);
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
}
