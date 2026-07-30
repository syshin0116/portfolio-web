import { describe, expect, test } from "bun:test"
import {
  createVercelProductionRevisionResponse,
  readVercelProductionRevision,
} from "./vercel-production-revision"

const SHA = "49e3349a5f4bfc7a7664c9924c842b2a16ce2e53"

const VALID_ENVIRONMENT = {
  VERCEL: "1",
  VERCEL_ENV: "production",
  VERCEL_TARGET_ENV: "production",
  VERCEL_PROJECT_ID: "prj_myD2BGgGc5oWtVPbb6rQc9hzfklS",
  VERCEL_GIT_PROVIDER: "github",
  VERCEL_GIT_REPO_OWNER: "syshin0116",
  VERCEL_GIT_REPO_SLUG: "syshin0116.dev",
  VERCEL_GIT_COMMIT_REF: "main",
  VERCEL_DEPLOYMENT_ID: "dpl_FciFB9jCy6zHMkACTrySxDGtHUu8",
  VERCEL_URL: "syshin0116-5wwb8dy37-syshin0116.vercel.app",
  VERCEL_GIT_COMMIT_SHA: SHA,
}

describe("readVercelProductionRevision", () => {
  test("returns the exact public revision contract", () => {
    expect(readVercelProductionRevision(VALID_ENVIRONMENT)).toEqual({
      schemaVersion: 1,
      deploymentId: "dpl_FciFB9jCy6zHMkACTrySxDGtHUu8",
      deploymentUrl: "syshin0116-5wwb8dy37-syshin0116.vercel.app",
      gitSha: SHA,
    })
  })

  test("allows a custom production domain to coexist with the canonical alias", () => {
    expect(
      readVercelProductionRevision({
        ...VALID_ENVIRONMENT,
        VERCEL_PROJECT_PRODUCTION_URL: "syshin0116.dev",
      })
    ).not.toBeNull()
  })

  test.each([
    ["VERCEL", undefined],
    ["VERCEL_ENV", "preview"],
    ["VERCEL_TARGET_ENV", "preview"],
    ["VERCEL_PROJECT_ID", "prj_wrong"],
    ["VERCEL_GIT_PROVIDER", "gitlab"],
    ["VERCEL_GIT_REPO_OWNER", "other"],
    ["VERCEL_GIT_REPO_SLUG", "other"],
    ["VERCEL_GIT_COMMIT_REF", "feature"],
    ["VERCEL_DEPLOYMENT_ID", "not-a-deployment"],
    ["VERCEL_URL", "https://syshin0116.vercel.app"],
    ["VERCEL_GIT_COMMIT_SHA", "short"],
  ])("fails closed when %s is %s", (key, value) => {
    expect(
      readVercelProductionRevision({
        ...VALID_ENVIRONMENT,
        [key]: value,
      })
    ).toBeNull()
  })
})

describe("createVercelProductionRevisionResponse", () => {
  test("serves only the canonical host with no-store caching", async () => {
    const response = createVercelProductionRevisionResponse(
      "https://syshin0116.vercel.app/api/deployment-revision",
      VALID_ENVIRONMENT
    )

    expect(response.status).toBe(200)
    expect(response.headers.get("cache-control")).toBe("no-store, max-age=0")
    expect(await response.json()).toEqual({
      schemaVersion: 1,
      deploymentId: "dpl_FciFB9jCy6zHMkACTrySxDGtHUu8",
      deploymentUrl: "syshin0116-5wwb8dy37-syshin0116.vercel.app",
      gitSha: SHA,
    })
  })

  test("does not expose the contract on a generated deployment host", async () => {
    const response = createVercelProductionRevisionResponse(
      "https://syshin0116-5wwb8dy37-syshin0116.vercel.app/api/deployment-revision",
      VALID_ENVIRONMENT
    )

    expect(response.status).toBe(404)
    expect(await response.json()).toEqual({ error: "not found" })
  })

  test("returns a safe 503 for an invalid production runtime", async () => {
    const response = createVercelProductionRevisionResponse(
      "https://syshin0116.vercel.app/api/deployment-revision",
      { ...VALID_ENVIRONMENT, VERCEL_GIT_COMMIT_SHA: undefined }
    )

    expect(response.status).toBe(503)
    expect(await response.json()).toEqual({
      error: "deployment revision unavailable",
    })
  })
})
