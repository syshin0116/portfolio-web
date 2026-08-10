import { describe, expect, test } from "bun:test"
import { readFileSync } from "node:fs"
import { resolve } from "node:path"

import {
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

const reviewedAudit: AuditCommandResult = {
  exitCode: 1,
  stdout: JSON.stringify({
    "brace-expansion": [
      {
        id: 1130588,
        url: "https://github.com/advisories/GHSA-mh99-v99m-4gvg",
        severity: "high",
        vulnerable_versions: "<1.1.17",
      },
    ],
  }),
  stderr: "",
}

function evidence() {
  return {
    production: emptyAudit,
    complete: emptyAudit,
    packageJson,
    bunLock,
  }
}

describe("dependency audit policy", () => {
  test("accepts clean production and complete audits", () => {
    expect(() => validateAuditPolicy(evidence())).not.toThrow()
  })

  test("rejects any production high or critical advisory", () => {
    const candidate = evidence()
    candidate.production = reviewedAudit

    expect(() => validateAuditPolicy(candidate)).toThrow(
      "production audit exited 1",
    )
  })

  test("rejects any complete-audit advisory", () => {
    const candidate = evidence()
    candidate.complete = reviewedAudit

    expect(() => validateAuditPolicy(candidate)).toThrow(
      "complete audit exited 1",
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
        '["brace-expansion@1.1.18"',
      '"other-runtime/minimatch/brace-expansion": ' +
        '["brace-expansion@1.1.18"',
    )

    expect(() => validateAuditPolicy(candidate)).toThrow(
      "brace-expansion@ lock paths drifted",
    )
  })

  test("rejects production override resolution drift", () => {
    const candidate = evidence()
    candidate.bunLock = candidate.bunLock.replace(
      '"postcss": ["postcss@8.5.26"',
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
      '"framer-motion": ["framer-motion@12.43.0"',
      '"framer-motion": ["framer-motion@12.23.25"',
    )

    expect(() => validateAuditPolicy(candidate)).toThrow(
      "unrelated direct resolution framer-motion drifted",
    )
  })

  test("rejects rolling lucide-react back from the reviewed resolution", () => {
    const candidate = evidence()
    candidate.bunLock = candidate.bunLock.replace(
      '"lucide-react": ["lucide-react@1.31.0"',
      '"lucide-react": ["lucide-react@1.25.0"',
    )

    expect(() => validateAuditPolicy(candidate)).toThrow(
      "unrelated direct resolution lucide-react drifted",
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

  test("rejects reintroducing an assistant-ui package patch", () => {
    const candidate = evidence()
    const manifest = JSON.parse(candidate.packageJson)
    manifest.patchedDependencies = {
      "@assistant-ui/store@0.3.8": "patches/store.patch",
    }
    candidate.packageJson = JSON.stringify(manifest)

    expect(() => validateAuditPolicy(candidate)).toThrow(
      "must not reintroduce assistant-ui patches",
    )
  })

  test("requires the assistant-ui store release with the upstream StrictMode fix", () => {
    const candidate = evidence()
    candidate.bunLock = candidate.bunLock.replace(
      '"@assistant-ui/store": ["@assistant-ui/store@0.3.8"',
      '"@assistant-ui/store": ["@assistant-ui/store@0.3.7"',
    )

    expect(() => validateAuditPolicy(candidate)).toThrow(
      "must retain the upstream StrictMode fix",
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
    "@auth/neon-adapter",
    "@neondatabase/serverless",
  ])("rejects a non-exact auth database manifest pin for %s", (name) => {
    const candidate = evidence()
    const manifest = JSON.parse(candidate.packageJson)
    manifest.dependencies[name] = `^${manifest.dependencies[name]}`
    candidate.packageJson = JSON.stringify(manifest)

    expect(() => validateAuditPolicy(candidate)).toThrow(
      `auth database dependency ${name} must be pinned exactly`,
    )
  })

  test("rejects reintroducing the generic PostgreSQL Auth.js adapter", () => {
    const candidate = evidence()
    const manifest = JSON.parse(candidate.packageJson)
    delete manifest.dependencies["@auth/neon-adapter"]
    manifest.dependencies["@auth/pg-adapter"] = "1.11.3"
    candidate.packageJson = JSON.stringify(manifest)

    expect(() => validateAuditPolicy(candidate)).toThrow(
      "auth database dependency @auth/neon-adapter must be pinned exactly",
    )
  })

  test.each([
    ["@assistant-ui/react", "0.15.13", "0.15.12"],
    ["@assistant-ui/react-langgraph", "0.14.23", "0.14.22"],
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

})
