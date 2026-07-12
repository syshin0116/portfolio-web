import { describe, expect, test } from "bun:test"
import { isAdminEmail, isAllowedEmail } from "./allowed-user"

describe("isAllowedEmail", () => {
  test("matches configured emails case-insensitively", () => {
    expect(isAllowedEmail("Owner@Example.com", "other@example.com,owner@example.com", "production")).toBe(true)
  })

  test("denies unlisted and missing emails", () => {
    expect(isAllowedEmail("guest@example.com", "owner@example.com", "production")).toBe(false)
    expect(isAllowedEmail(null, "owner@example.com", "production")).toBe(false)
  })

  test("fails closed in production when the allowlist is empty", () => {
    expect(isAllowedEmail("owner@example.com", "", "production")).toBe(false)
    expect(isAllowedEmail("owner@example.com", "", "development")).toBe(true)
  })
})

describe("isAdminEmail", () => {
  test("matches the explicit admin list case-insensitively", () => {
    expect(isAdminEmail("Owner@Example.com", "owner@example.com")).toBe(true)
  })

  test("fails closed when the admin list is empty", () => {
    expect(isAdminEmail("owner@example.com", "")).toBe(false)
    expect(isAdminEmail(null, "owner@example.com")).toBe(false)
  })
})
