import { describe, expect, test } from "bun:test"
import { readFileSync } from "node:fs"
import { resolve } from "node:path"

import {
  TEMPORARY_ADVISORY,
  type AuditCommandResult,
  validateAuditPolicy,
} from "./audit-dependencies"

const webRoot = resolve(import.meta.dir, "..")
const packageJson = readFileSync(resolve(webRoot, "package.json"), "utf8")
const bunLock = readFileSync(resolve(webRoot, "bun.lock"), "utf8")

const emptyAudit: AuditCommandResult = {
  exitCode: 0,
  stdout: "{}",
  stderr: "",
}

const ignoredAudit: AuditCommandResult = {
  exitCode: 0,
  stdout: "",
  stderr: "",
}

const reviewedAudit: AuditCommandResult = {
  exitCode: 1,
  stdout: JSON.stringify({
    "brace-expansion": [
      {
        id: TEMPORARY_ADVISORY.id,
        url: `https://github.com/advisories/${TEMPORARY_ADVISORY.ghsa}`,
        severity: TEMPORARY_ADVISORY.severity,
        vulnerable_versions: TEMPORARY_ADVISORY.vulnerableVersions,
      },
    ],
  }),
  stderr: "",
}

function evidence() {
  return {
    production: emptyAudit,
    complete: reviewedAudit,
    ignored: ignoredAudit,
    packageJson,
    bunLock,
    now: new Date("2026-07-27T00:00:00Z"),
  }
}

describe("dependency audit exception policy", () => {
  test("accepts only the reviewed dev-only advisory before expiry", () => {
    expect(() => validateAuditPolicy(evidence())).not.toThrow()
  })

  test("rejects any production high or critical advisory", () => {
    const candidate = evidence()
    candidate.production = reviewedAudit

    expect(() => validateAuditPolicy(candidate)).toThrow(
      "production audit exited 1",
    )
  })

  test("rejects a second complete-audit advisory", () => {
    const candidate = evidence()
    candidate.complete = {
      exitCode: 1,
      stdout: JSON.stringify({
        "brace-expansion": JSON.parse(reviewedAudit.stdout)["brace-expansion"],
        sharp: [
          {
            id: 1,
            url: "https://github.com/advisories/GHSA-test-test-test",
            severity: "high",
            vulnerable_versions: "<1.0.0",
          },
        ],
      }),
      stderr: "",
    }

    expect(() => validateAuditPolicy(candidate)).toThrow(
      "must contain only brace-expansion",
    )
  })

  test("rejects moving eslint-config-next into production dependencies", () => {
    const candidate = evidence()
    const manifest = JSON.parse(candidate.packageJson)
    manifest.dependencies["eslint-config-next"] =
      manifest.devDependencies["eslint-config-next"]
    delete manifest.devDependencies["eslint-config-next"]
    candidate.packageJson = JSON.stringify(manifest)

    expect(() => validateAuditPolicy(candidate)).toThrow(
      "must not enter production dependencies",
    )
  })

  test("rejects vulnerable lock-path drift", () => {
    const candidate = evidence()
    candidate.bunLock = candidate.bunLock.replace(
      '"eslint-plugin-react/minimatch/brace-expansion": ' +
        '["brace-expansion@1.1.16"',
      '"other-runtime/minimatch/brace-expansion": ' +
        '["brace-expansion@1.1.16"',
    )

    expect(() => validateAuditPolicy(candidate)).toThrow(
      "brace-expansion@ lock paths drifted",
    )
  })

  test("rejects production override resolution drift", () => {
    const candidate = evidence()
    candidate.bunLock = candidate.bunLock.replace(
      '"postcss": ["postcss@8.5.24"',
      '"postcss": ["postcss@8.5.23"',
    )

    expect(() => validateAuditPolicy(candidate)).toThrow(
      "postcss@ lock paths drifted",
    )
  })

  test.each([
    ["@types/react", "19.1.16"],
    ["@types/react-dom", "19.1.9"],
  ])("rejects a stale React type override for %s", (name, staleVersion) => {
    const candidate = evidence()
    const manifest = JSON.parse(candidate.packageJson)
    manifest.overrides[name] = staleVersion
    candidate.packageJson = JSON.stringify(manifest)

    expect(() => validateAuditPolicy(candidate)).toThrow(
      `reviewed React type override ${name} drifted`,
    )
  })

  test("rejects unrelated direct resolution drift outside the security allowlist", () => {
    const candidate = evidence()
    candidate.bunLock = candidate.bunLock.replace(
      '"framer-motion": ["framer-motion@12.42.2"',
      '"framer-motion": ["framer-motion@12.23.25"',
    )

    expect(() => validateAuditPolicy(candidate)).toThrow(
      "unrelated direct resolution framer-motion drifted",
    )
  })

  test("rejects reintroducing legacy LangGraph UI dependencies", () => {
    const candidate = evidence()
    const manifest = JSON.parse(candidate.packageJson)
    manifest.dependencies["@langchain/react"] = "^1.0.29"
    candidate.packageJson = JSON.stringify(manifest)

    expect(() => validateAuditPolicy(candidate)).toThrow(
      "direct dependency set drifted",
    )
  })

  test.each([
    "@assistant-ui/react",
    "@assistant-ui/react-langgraph",
    "@langchain/langgraph-sdk",
    "@langchain/protocol",
  ])("rejects a non-exact native agent manifest pin for %s", (name) => {
    const candidate = evidence()
    const manifest = JSON.parse(candidate.packageJson)
    manifest.dependencies[name] = `^${manifest.dependencies[name]}`
    candidate.packageJson = JSON.stringify(manifest)

    expect(() => validateAuditPolicy(candidate)).toThrow(
      `native agent dependency ${name} must be pinned exactly`,
    )
  })

  test.each([
    ["@assistant-ui/react", "0.15.0", "0.14.28"],
    ["@assistant-ui/react-langgraph", "0.14.15", "0.14.13"],
    ["@langchain/langgraph-sdk", "1.9.28", "1.9.27"],
    ["@langchain/protocol", "0.0.18", "0.0.17"],
  ])(
    "rejects native agent lock drift for %s",
    (name, currentVersion, oldVersion) => {
      const candidate = evidence()
      candidate.bunLock = candidate.bunLock.replace(
        `"${name}": ["${name}@${currentVersion}"`,
        `"${name}": ["${name}@${oldVersion}"`,
      )

      expect(() => validateAuditPolicy(candidate)).toThrow(
        `native agent lock resolution ${name} drifted`,
      )
    },
  )

  test("rejects the exception after its review deadline", () => {
    const candidate = evidence()
    candidate.now = new Date("2026-09-01T00:00:00Z")

    expect(() => validateAuditPolicy(candidate)).toThrow(
      "exception expired after 2026-08-31",
    )
  })

  test("rejects an ignored audit that hides another finding", () => {
    const candidate = evidence()
    candidate.ignored = reviewedAudit

    expect(() => validateAuditPolicy(candidate)).toThrow(
      "reviewed-exception audit exited 1",
    )
  })
})
