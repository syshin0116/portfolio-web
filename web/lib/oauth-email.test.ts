import { describe, expect, test } from "bun:test"
import { hasVerifiedProviderEmail } from "./oauth-email"

describe("hasVerifiedProviderEmail", () => {
  test("accepts only Google's verified matching email", async () => {
    expect(
      await hasVerifiedProviderEmail({
        provider: "google",
        email: "owner@example.com",
        accessToken: undefined,
        profile: {
          email: "Owner@Example.com",
          email_verified: true,
        },
      })
    ).toBe(true)
    expect(
      await hasVerifiedProviderEmail({
        provider: "google",
        email: "owner@example.com",
        accessToken: undefined,
        profile: {
          email: "owner@example.com",
          email_verified: false,
        },
      })
    ).toBe(false)
    expect(
      await hasVerifiedProviderEmail({
        provider: "google",
        email: "owner@example.com",
        accessToken: undefined,
        profile: {
          email: "different@example.com",
          email_verified: true,
        },
      })
    ).toBe(false)
  })

  test("accepts only GitHub's primary verified matching email", async () => {
    const fetchImpl = async () =>
      Response.json([
        {
          email: "secondary@example.com",
          primary: false,
          verified: true,
        },
        {
          email: "Owner@Example.com",
          primary: true,
          verified: true,
        },
      ])

    expect(
      await hasVerifiedProviderEmail({
        provider: "github",
        email: "owner@example.com",
        accessToken: "provider-token",
        profile: {},
        fetchImpl,
      })
    ).toBe(true)
  })

  test.each([
    [{ email: "owner@example.com", primary: true, verified: false }],
    [{ email: "owner@example.com", primary: false, verified: true }],
    [{ email: "different@example.com", primary: true, verified: true }],
  ])("rejects an untrusted GitHub email response %#", async (payload) => {
    expect(
      await hasVerifiedProviderEmail({
        provider: "github",
        email: "owner@example.com",
        accessToken: "provider-token",
        profile: {},
        fetchImpl: async () => Response.json(payload),
      })
    ).toBe(false)
  })

  test("fails closed on provider API errors", async () => {
    expect(
      await hasVerifiedProviderEmail({
        provider: "github",
        email: "owner@example.com",
        accessToken: "provider-token",
        profile: {},
        fetchImpl: async () => {
          throw new Error("network details")
        },
      })
    ).toBe(false)
  })

  test("rejects GitHub without a token or with an invalid response", async () => {
    expect(
      await hasVerifiedProviderEmail({
        provider: "github",
        email: "owner@example.com",
        accessToken: undefined,
        profile: {},
      })
    ).toBe(false)
    expect(
      await hasVerifiedProviderEmail({
        provider: "github",
        email: "owner@example.com",
        accessToken: "provider-token",
        profile: {},
        fetchImpl: async () =>
          Response.json({ error: "denied" }, { status: 403 }),
      })
    ).toBe(false)
    expect(
      await hasVerifiedProviderEmail({
        provider: "github",
        email: "owner@example.com",
        accessToken: "provider-token",
        profile: {},
        fetchImpl: async () =>
          new Response("{", {
            headers: { "Content-Type": "application/json" },
          }),
      })
    ).toBe(false)
  })
})
