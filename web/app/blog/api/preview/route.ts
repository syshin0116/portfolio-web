import { NextRequest, NextResponse } from "next/server"
import type { IncomingMessage } from "node:http"
import { request as requestHttp } from "node:http"
import { request as requestHttps } from "node:https"
import { isIP } from "node:net"
import previewIndex from "@/public/preview-index.json"
import {
  BoundedTtlCache,
  ConcurrencyGate,
  FixedWindowRateLimiter,
} from "@/lib/preview-abuse"
import {
  resolvePreviewImageUrl,
  resolvePreviewTarget,
  UnsafePreviewUrlError,
  type PreviewTarget,
} from "@/lib/preview-url-policy"

const MAX_REDIRECTS = 3
const MAX_RESPONSE_BYTES = 512 * 1024
const FETCH_TIMEOUT_MS = 5000
const MAX_URL_LENGTH = 2048
const CACHE_TTL_MS = 10 * 60 * 1000
const EXTERNAL_CACHE_CONTROL =
  "public, max-age=60, s-maxage=600, stale-while-revalidate=3600"
const REDIRECT_STATUSES = new Set([301, 302, 303, 307, 308])
const clientRateLimiter = new FixedWindowRateLimiter(20, 60_000, 2048)
const instanceRateLimiter = new FixedWindowRateLimiter(100, 60_000, 1)
const fetchGate = new ConcurrencyGate(4)

interface ExternalPreview {
  title: string
  excerpt: string
  image: string | null
  type: "external"
}

const externalPreviewCache = new BoundedTtlCache<Promise<ExternalPreview>>(
  256,
  CACHE_TTL_MS
)

export async function GET(request: NextRequest) {
  const slug = request.nextUrl.searchParams.get("slug")
  const url = request.nextUrl.searchParams.get("url")

  if (url) {
    return handleExternalPreview(request, url)
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

async function handleExternalPreview(request: NextRequest, url: string) {
  const clientLimit = clientRateLimiter.check(previewClientKey(request))
  const instanceLimit = instanceRateLimiter.check("instance")
  if (!clientLimit.allowed || !instanceLimit.allowed) {
    return rateLimitedResponse(
      Math.max(clientLimit.retryAfterSeconds, instanceLimit.retryAfterSeconds)
    )
  }

  try {
    const cacheKey = canonicalPreviewUrl(url)
    let preview = externalPreviewCache.get(cacheKey)

    if (!preview) {
      const release = fetchGate.tryAcquire()
      if (!release) return rateLimitedResponse(1)

      preview = buildExternalPreview(cacheKey)
        .catch((error) => {
          externalPreviewCache.delete(cacheKey)
          throw error
        })
        .finally(release)
      externalPreviewCache.set(cacheKey, preview)
    }

    return NextResponse.json(await preview, {
      headers: { "Cache-Control": EXTERNAL_CACHE_CONTROL },
    })
  } catch (error) {
    if (error instanceof UnsafePreviewUrlError) {
      return NextResponse.json({ error: "URL is not allowed" }, { status: 400 })
    }
    return NextResponse.json({ error: "Fetch failed" }, { status: 502 })
  }
}

async function buildExternalPreview(url: string): Promise<ExternalPreview> {
  const { html, finalUrl } = await fetchExternalHtml(url)

  const title =
    html.match(/<meta[^>]+property="og:title"[^>]+content="([^"]+)"/i)?.[1] ??
    html.match(/<meta[^>]+content="([^"]+)"[^>]+property="og:title"/i)?.[1] ??
    html.match(/<title[^>]*>([^<]+)<\/title>/i)?.[1]?.trim() ??
    finalUrl.href

  const description =
    html.match(/<meta[^>]+property="og:description"[^>]+content="([^"]+)"/i)?.[1] ??
    html.match(/<meta[^>]+content="([^"]+)"[^>]+property="og:description"/i)?.[1] ??
    html.match(/<meta[^>]+name="description"[^>]+content="([^"]+)"/i)?.[1] ??
    ""

  const rawImage =
    html.match(/<meta[^>]+property="og:image"[^>]+content="([^"]+)"/i)?.[1] ??
    html.match(/<meta[^>]+content="([^"]+)"[^>]+property="og:image"/i)?.[1] ??
    null
  const image = resolvePreviewImageUrl(rawImage, finalUrl)

  return {
    title: title.slice(0, 120),
    excerpt: description.slice(0, 350),
    image,
    type: "external",
  }
}

function canonicalPreviewUrl(rawUrl: string) {
  if (rawUrl.length > MAX_URL_LENGTH) {
    throw new UnsafePreviewUrlError("URL is too long")
  }

  try {
    const url = new URL(rawUrl)
    url.hash = ""
    return url.href
  } catch {
    throw new UnsafePreviewUrlError("Invalid URL")
  }
}

function previewClientKey(request: NextRequest) {
  const forwardedFor =
    request.headers.get("x-vercel-forwarded-for") ??
    request.headers.get("cf-connecting-ip") ??
    request.headers.get("x-real-ip") ??
    request.headers.get("x-forwarded-for") ??
    "unknown"
  return (forwardedFor.split(",")[0]?.trim() || "unknown").slice(0, 128)
}

function rateLimitedResponse(retryAfterSeconds: number) {
  return NextResponse.json(
    { error: "Too many preview requests" },
    {
      status: 429,
      headers: {
        "Cache-Control": "no-store",
        "Retry-After": String(Math.max(1, retryAfterSeconds)),
      },
    }
  )
}

async function fetchExternalHtml(rawUrl: string) {
  let target = await resolvePreviewTarget(rawUrl)

  for (let redirectCount = 0; redirectCount <= MAX_REDIRECTS; redirectCount++) {
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS)
    let response: IncomingMessage
    try {
      response = await requestPinned(target, controller.signal)
    } catch (error) {
      clearTimeout(timeout)
      throw error
    }

    if (REDIRECT_STATUSES.has(response.statusCode ?? 0)) {
      const location = firstHeader(response.headers.location)
      if (!location || redirectCount === MAX_REDIRECTS) {
        response.destroy()
        clearTimeout(timeout)
        throw new Error("Invalid redirect response")
      }
      response.destroy()
      clearTimeout(timeout)
      target = await resolvePreviewTarget(new URL(location, target.url).href)
      continue
    }

    if (!response.statusCode || response.statusCode < 200 || response.statusCode >= 300) {
      response.destroy()
      clearTimeout(timeout)
      throw new Error("Remote response was not successful")
    }

    const contentType = firstHeader(response.headers["content-type"])?.toLowerCase() ?? ""
    if (
      !contentType.startsWith("text/html") &&
      !contentType.startsWith("application/xhtml+xml")
    ) {
      response.destroy()
      clearTimeout(timeout)
      throw new Error("Remote response is not HTML")
    }

    const declaredLength = Number(firstHeader(response.headers["content-length"]))
    if (Number.isFinite(declaredLength) && declaredLength > MAX_RESPONSE_BYTES) {
      response.destroy()
      clearTimeout(timeout)
      throw new Error("Remote response is too large")
    }

    try {
      return {
        html: await readLimitedBody(response),
        finalUrl: target.url,
      }
    } finally {
      clearTimeout(timeout)
    }
  }

  throw new Error("Too many redirects")
}

function requestPinned(target: PreviewTarget, signal: AbortSignal) {
  const request = target.url.protocol === "https:" ? requestHttps : requestHttp
  const hostname = target.url.hostname.replace(/^\[|\]$/g, "")

  return new Promise<IncomingMessage>((resolve, reject) => {
    const outgoingRequest = request(
      {
        protocol: target.url.protocol,
        hostname: target.address,
        port: target.url.port || undefined,
        path: `${target.url.pathname}${target.url.search}`,
        method: "GET",
        headers: {
          Accept: "text/html,application/xhtml+xml",
          Host: target.url.host,
          "User-Agent": "Mozilla/5.0 (compatible; portfolio-blog-preview/1.0)",
        },
        servername: isIP(hostname) === 0 ? hostname : undefined,
        signal,
      },
      resolve
    )
    outgoingRequest.on("error", reject)
    outgoingRequest.end()
  })
}

async function readLimitedBody(response: IncomingMessage): Promise<string> {
  const chunks: Buffer[] = []
  let totalBytes = 0

  for await (const chunk of response) {
    const bytes = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk)
    totalBytes += bytes.byteLength
    if (totalBytes > MAX_RESPONSE_BYTES) {
      response.destroy()
      throw new Error("Remote response is too large")
    }
    chunks.push(bytes)
  }

  return Buffer.concat(chunks, totalBytes).toString("utf8")
}

function firstHeader(value: string | string[] | undefined) {
  return Array.isArray(value) ? value[0] : value
}
