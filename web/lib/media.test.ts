import { describe, expect, test } from "bun:test"
import {
  isAllowedMediaPath,
  mediaSecurityHeaders,
  mediaTypeForPath,
} from "./media"

describe("media path policy", () => {
  test.each([
    ["images/photo.PNG", "image/png"],
    ["attachments/report.pdf", "application/pdf"],
    ["assets/diagram.svg", "image/svg+xml"],
  ])("allows %s", (filePath, contentType) => {
    expect(isAllowedMediaPath(filePath)).toBe(true)
    expect(mediaTypeForPath(filePath)).toBe(contentType)
  })

  test.each([
    ".hashes",
    ".obsidian/app.json",
    "assets/.private/image.png",
    "notes/post.md",
    "assets/source.excalidraw",
    "assets/no-extension",
  ])("rejects %s", (filePath) => {
    expect(isAllowedMediaPath(filePath)).toBe(false)
    expect(mediaTypeForPath(filePath)).toBeNull()
  })

  test("sandboxes SVG documents without affecting passive images", () => {
    expect(mediaSecurityHeaders("assets/diagram.svg")).toEqual({
      "Content-Security-Policy":
        "default-src 'none'; img-src data:; style-src 'unsafe-inline'; sandbox",
    })
    expect(mediaSecurityHeaders("assets/photo.png")).toEqual({})
  })
})
