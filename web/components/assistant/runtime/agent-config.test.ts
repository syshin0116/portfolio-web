import { describe, expect, test } from "bun:test"

import { normalizeAgentApiUrl } from "./agent-config"

describe("normalizeAgentApiUrl", () => {
  test.each([
    ["https://agent.example", "https://agent.example"],
    ["https://agent.example:8443/", "https://agent.example:8443"],
    ["http://localhost:8000", "http://localhost:8000"],
    ["https://localhost:8000/", "https://localhost:8000"],
    ["http://127.0.0.1:8000", "http://127.0.0.1:8000"],
    ["http://[::1]:8000", "http://[::1]:8000"],
  ])("accepts reviewed origin %s", (candidate, expected) => {
    expect(normalizeAgentApiUrl(candidate)).toEqual({ apiUrl: expected })
  })

  test.each([
    "http://agent.example",
    "ftp://localhost",
    "ws://127.0.0.1:8000",
    "http://service.localhost:8000",
    "http://127.0.0.2:8000",
    "http://[::ffff:127.0.0.1]:8000",
    "http://2130706433:8000",
    "http://0x7f000001:8000",
    "http://localhost.:8000",
    "HTTP://localhost:8000",
  ])("rejects unreviewed scheme or hostname %s", (candidate) => {
    expect(normalizeAgentApiUrl(candidate)).toHaveProperty("error")
  })

  test.each([
    "https://user@agent.example",
    "https://user:secret@agent.example",
    "https://agent.example?token=secret",
    "https://agent.example#secret",
    "https://agent.example/api",
    "http://localhost:8000/api/",
  ])("rejects URL components outside the origin policy %s", (candidate) => {
    expect(normalizeAgentApiUrl(candidate)).toHaveProperty("error")
  })

  test.each([undefined, "", "   ", "not a URL"])(
    "rejects missing or malformed input %s",
    (candidate) => {
      expect(normalizeAgentApiUrl(candidate)).toHaveProperty("error")
    }
  )
})
