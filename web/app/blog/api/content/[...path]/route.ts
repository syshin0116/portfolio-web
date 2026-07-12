import { NextRequest, NextResponse } from "next/server"
import fs from "node:fs/promises"
import path from "node:path"
import { CONTENT_DIR } from "@/lib/content"
import { mediaSecurityHeaders, mediaTypeForPath } from "@/lib/media"

const CONTENT_ROOT = path.resolve(CONTENT_DIR)

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path: pathParts } = await params
  const joined = pathParts.join("/")
  const contentType = mediaTypeForPath(joined)
  if (!contentType) {
    return new NextResponse("Not Found", { status: 404 })
  }

  const normalized = path.normalize(joined)
  if (normalized === "." || normalized.startsWith("..")) {
    return new NextResponse("Forbidden", { status: 403 })
  }
  const filePath = path.resolve(CONTENT_ROOT, normalized)
  if (!filePath.startsWith(CONTENT_ROOT + path.sep)) {
    return new NextResponse("Forbidden", { status: 403 })
  }
  try {
    const [realContentRoot, realFilePath] = await Promise.all([
      fs.realpath(CONTENT_ROOT),
      fs.realpath(filePath),
    ])
    if (!realFilePath.startsWith(realContentRoot + path.sep)) {
      return new NextResponse("Forbidden", { status: 403 })
    }

    const data = await fs.readFile(realFilePath)
    return new NextResponse(data, {
      headers: {
        "Content-Type": contentType,
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "public, max-age=86400",
        ...mediaSecurityHeaders(joined),
      },
    })
  } catch {
    return new NextResponse("Not Found", { status: 404 })
  }
}
