import path from "node:path"

export const MEDIA_MIME_TYPES: Readonly<Record<string, string>> = {
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".webp": "image/webp",
  ".svg": "image/svg+xml",
  ".pdf": "application/pdf",
  ".mp4": "video/mp4",
  ".mp3": "audio/mpeg",
}

export function isAllowedMediaPath(filePath: string): boolean {
  const segments = filePath.split(/[\\/]/)
  if (
    segments.length === 0 ||
    segments.some((segment) => !segment || segment.startsWith("."))
  ) {
    return false
  }

  return path.extname(filePath).toLowerCase() in MEDIA_MIME_TYPES
}

export function mediaTypeForPath(filePath: string): string | null {
  if (!isAllowedMediaPath(filePath)) return null
  return MEDIA_MIME_TYPES[path.extname(filePath).toLowerCase()] ?? null
}

export function mediaSecurityHeaders(filePath: string): Record<string, string> {
  if (path.extname(filePath).toLowerCase() !== ".svg") return {}

  return {
    "Content-Security-Policy":
      "default-src 'none'; img-src data:; style-src 'unsafe-inline'; sandbox",
  }
}
