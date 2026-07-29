import { describe, expect, test } from "bun:test"

import { getBlogSlug } from "./blog-path"

describe("getBlogSlug", () => {
  test("decodes an encoded blog path before sidebar matching", () => {
    expect(
      getBlogSlug(
        "/blog/AI/2025-06-04-Agent%20Architecture%20Comparison"
      )
    ).toBe("AI/2025-06-04-Agent Architecture Comparison")
  })

  test("decodes non-ASCII blog path segments", () => {
    expect(getBlogSlug("/blog/AI/%ED%95%9C%EA%B8%80%20%EA%B8%80")).toBe(
      "AI/한글 글"
    )
  })

  test("returns an undecodable path without throwing", () => {
    expect(getBlogSlug("/blog/AI/broken%2")).toBe("AI/broken%2")
  })

  test("returns an empty slug on the blog home page", () => {
    expect(getBlogSlug("/blog")).toBe("")
  })
})
