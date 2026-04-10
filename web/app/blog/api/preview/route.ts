import { NextRequest, NextResponse } from "next/server"
import previewIndex from "@/public/preview-index.json"

export async function GET(request: NextRequest) {
  const slug = request.nextUrl.searchParams.get("slug")
  const url = request.nextUrl.searchParams.get("url")

  if (url) {
    return handleExternalPreview(url)
  }

  if (!slug) {
    return NextResponse.json({ error: "Missing slug or url" }, { status: 400 })
  }

  return handleInternalPreview(slug)
}

function handleInternalPreview(slug: string) {
  const idx = previewIndex as Record<string, { title: string; excerpt: string }>
  const entry = idx[slug]
  if (!entry) {
    return NextResponse.json({ error: "Not found" }, { status: 404 })
  }
  return NextResponse.json({ title: entry.title, excerpt: entry.excerpt, type: "internal" })
}

async function handleExternalPreview(url: string) {
  try {
    new URL(url)
  } catch {
    return NextResponse.json({ error: "Invalid URL" }, { status: 400 })
  }

  try {
    const res = await fetch(url, {
      headers: { "User-Agent": "Mozilla/5.0 (compatible; portfolio-blog-preview/1.0)" },
      signal: AbortSignal.timeout(5000),
    })
    if (!res.ok) return NextResponse.json({ error: "Fetch failed" }, { status: 502 })

    const html = await res.text()

    const title =
      html.match(/<meta[^>]+property="og:title"[^>]+content="([^"]+)"/i)?.[1] ??
      html.match(/<meta[^>]+content="([^"]+)"[^>]+property="og:title"/i)?.[1] ??
      html.match(/<title[^>]*>([^<]+)<\/title>/i)?.[1]?.trim() ??
      url

    const description =
      html.match(/<meta[^>]+property="og:description"[^>]+content="([^"]+)"/i)?.[1] ??
      html.match(/<meta[^>]+content="([^"]+)"[^>]+property="og:description"/i)?.[1] ??
      html.match(/<meta[^>]+name="description"[^>]+content="([^"]+)"/i)?.[1] ??
      ""

    const image =
      html.match(/<meta[^>]+property="og:image"[^>]+content="([^"]+)"/i)?.[1] ??
      html.match(/<meta[^>]+content="([^"]+)"[^>]+property="og:image"/i)?.[1] ??
      null

    return NextResponse.json({
      title: title.slice(0, 120),
      excerpt: description.slice(0, 350),
      image,
      type: "external",
    })
  } catch {
    return NextResponse.json({ error: "Fetch failed" }, { status: 502 })
  }
}
