import { describe, expect, test } from "bun:test"
import { canonicalAuthSubject } from "./auth-subject"

describe("canonicalAuthSubject", () => {
  test.each([
    ["auth-user-id", "auth-user-id"],
    [0, "0"],
    [42, "42"],
  ])("canonicalizes %# to %s", (value, expected) => {
    expect(canonicalAuthSubject(value)).toBe(expected)
  })

  test.each([
    "",
    " auth-user-id",
    "auth-user-id ",
    -1,
    Number.NaN,
    Number.POSITIVE_INFINITY,
    1.5,
    null,
    undefined,
    true,
    {},
  ])("rejects a non-canonical subject %#", (value) => {
    expect(canonicalAuthSubject(value)).toBeNull()
  })
})
