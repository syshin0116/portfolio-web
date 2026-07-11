import { describe, expect, test } from "bun:test"
import {
  isPublicAddress,
  MAX_PREVIEW_IMAGE_URL_LENGTH,
  resolvePreviewImageUrl,
  UnsafePreviewUrlError,
  validatePreviewUrl,
  type AddressResolver,
} from "./preview-url-policy"

describe("resolvePreviewImageUrl", () => {
  const pageUrl = new URL("https://example.com/posts/one")

  test("accepts bounded HTTPS image URLs", () => {
    expect(resolvePreviewImageUrl("/image.png", pageUrl)).toBe(
      "https://example.com/image.png"
    )
  })

  test("rejects non-HTTPS and oversized image URLs", () => {
    expect(resolvePreviewImageUrl("http://example.com/image.png", pageUrl)).toBeNull()
    expect(
      resolvePreviewImageUrl(
        `https://example.com/${"a".repeat(MAX_PREVIEW_IMAGE_URL_LENGTH)}`,
        pageUrl
      )
    ).toBeNull()
  })
})

const publicResolver: AddressResolver = async () => [
  { address: "93.184.216.34", family: 4 },
  { address: "2606:2800:220:1:248:1893:25c8:1946", family: 6 },
]

describe("isPublicAddress", () => {
  test.each([
    "0.0.0.0",
    "10.0.0.1",
    "100.64.0.1",
    "127.0.0.1",
    "169.254.169.254",
    "172.16.0.1",
    "192.168.1.1",
    "192.0.2.10",
    "198.18.0.1",
    "198.51.100.10",
    "203.0.113.10",
    "224.0.0.1",
    "255.255.255.255",
    "::",
    "::1",
    "::ffff:127.0.0.1",
    "2001:db8::1",
    "fc00::1",
    "fe80::1",
    "ff02::1",
  ])("rejects non-public address %s", (address) => {
    expect(isPublicAddress(address)).toBe(false)
  })

  test.each([
    "1.1.1.1",
    "8.8.8.8",
    "93.184.216.34",
    "2606:4700:4700::1111",
    "2606:2800:220:1:248:1893:25c8:1946",
  ])("accepts public address %s", (address) => {
    expect(isPublicAddress(address)).toBe(true)
  })
})

describe("validatePreviewUrl", () => {
  test("accepts an HTTP(S) URL whose DNS answers are all public", async () => {
    const url = await validatePreviewUrl("https://example.com/path", publicResolver)
    expect(url.href).toBe("https://example.com/path")
  })

  test.each(["file:///etc/passwd", "ftp://example.com/file", "javascript:alert(1)"])(
    "rejects unsupported URL %s",
    async (url) => {
      await expect(validatePreviewUrl(url, publicResolver)).rejects.toBeInstanceOf(
        UnsafePreviewUrlError
      )
    }
  )

  test("rejects credentials", async () => {
    await expect(
      validatePreviewUrl("https://user:secret@example.com", publicResolver)
    ).rejects.toBeInstanceOf(UnsafePreviewUrlError)
  })

  test.each([
    "http://localhost",
    "http://service.localhost",
    "http://127.1",
    "http://169.254.169.254/latest/meta-data",
    "http://[::1]",
  ])("rejects a direct local target %s", async (url) => {
    await expect(validatePreviewUrl(url, publicResolver)).rejects.toBeInstanceOf(
      UnsafePreviewUrlError
    )
  })

  test("rejects a hostname when any DNS answer is private", async () => {
    const mixedResolver: AddressResolver = async () => [
      { address: "93.184.216.34", family: 4 },
      { address: "10.0.0.5", family: 4 },
    ]

    await expect(
      validatePreviewUrl("https://example.com", mixedResolver)
    ).rejects.toBeInstanceOf(UnsafePreviewUrlError)
  })

  test("rejects empty DNS answers", async () => {
    await expect(
      validatePreviewUrl("https://example.com", async () => [])
    ).rejects.toBeInstanceOf(UnsafePreviewUrlError)
  })
})
