import { readFile } from "node:fs/promises"
import { resolve } from "node:path"

const EXPECTED_ASSISTANT_UI_STORE_RESOLUTION =
  "@assistant-ui/store@0.3.8"

const EXPECTED_BRACE_RECORDS = new Map([
  ["brace-expansion", "brace-expansion@5.0.9"],
  [
    "eslint-plugin-import/minimatch/brace-expansion",
    "brace-expansion@1.1.18",
  ],
  [
    "eslint-plugin-jsx-a11y/minimatch/brace-expansion",
    "brace-expansion@1.1.18",
  ],
  [
    "eslint-plugin-react/minimatch/brace-expansion",
    "brace-expansion@1.1.18",
  ],
])

const EXPECTED_LEGACY_MINIMATCH_RECORDS = new Map([
  ["eslint-plugin-import/minimatch", "minimatch@3.1.5"],
  ["eslint-plugin-jsx-a11y/minimatch", "minimatch@3.1.5"],
  ["eslint-plugin-react/minimatch", "minimatch@3.1.5"],
])

const EXPECTED_ESLINT_PLUGIN_RECORDS = new Map([
  ["eslint-plugin-import", "eslint-plugin-import@2.32.0"],
  ["eslint-plugin-jsx-a11y", "eslint-plugin-jsx-a11y@6.10.2"],
  ["eslint-plugin-react", "eslint-plugin-react@7.37.5"],
])

const EXPECTED_SECURITY_DIRECT_RESOLUTIONS = new Map([
  ["@assistant-ui/react", "@assistant-ui/react@0.15.13"],
  [
    "@assistant-ui/react-langgraph",
    "@assistant-ui/react-langgraph@0.14.23",
  ],
  [
    "@assistant-ui/react-markdown",
    "@assistant-ui/react-markdown@0.14.10",
  ],
  ["@auth/neon-adapter", "@auth/neon-adapter@1.11.3"],
  ["@langchain/core", "@langchain/core@1.2.5"],
  ["@langchain/langgraph-sdk", "@langchain/langgraph-sdk@1.9.28"],
  ["@langchain/protocol", "@langchain/protocol@0.0.18"],
  ["@neondatabase/serverless", "@neondatabase/serverless@1.1.0"],
  ["botid", "botid@1.5.11"],
  ["eslint-config-next", "eslint-config-next@16.3.0"],
  ["mermaid", "mermaid@11.16.1"],
  ["next", "next@16.3.0"],
  ["next-auth", "next-auth@5.0.0-beta.32"],
  ["pg", "pg@8.23.0"],
  ["postcss", "postcss@8.5.26"],
])

const EXPECTED_NATIVE_AGENT_PINS = new Map([
  ["@assistant-ui/react", "0.15.13"],
  ["@assistant-ui/react-langgraph", "0.14.23"],
  ["@assistant-ui/react-markdown", "0.14.10"],
  ["@langchain/langgraph-sdk", "1.9.28"],
  ["@langchain/protocol", "0.0.18"],
])

const EXPECTED_AUTH_DATABASE_PINS = new Map([
  ["@auth/neon-adapter", "1.11.3"],
  ["@neondatabase/serverless", "1.1.0"],
])

const EXPECTED_REACT_TYPE_OVERRIDES = new Map([
  ["@types/react", "19.2.18"],
  ["@types/react-dom", "19.2.4"],
])

const EXPECTED_UNCHANGED_DIRECT_RESOLUTIONS = new Map([
  ["@axe-core/playwright", "@axe-core/playwright@4.12.1"],
  ["@eslint/compat", "@eslint/compat@2.1.0"],
  ["@giscus/react", "@giscus/react@3.1.0"],
  ["@playwright/test", "@playwright/test@1.62.1"],
  ["@radix-ui/react-accordion", "@radix-ui/react-accordion@1.2.20"],
  ["@radix-ui/react-avatar", "@radix-ui/react-avatar@1.2.6"],
  ["@radix-ui/react-checkbox", "@radix-ui/react-checkbox@1.3.11"],
  ["@radix-ui/react-collapsible", "@radix-ui/react-collapsible@1.1.20"],
  ["@radix-ui/react-dialog", "@radix-ui/react-dialog@1.1.23"],
  [
    "@radix-ui/react-dropdown-menu",
    "@radix-ui/react-dropdown-menu@2.1.24",
  ],
  ["@radix-ui/react-hover-card", "@radix-ui/react-hover-card@1.1.23"],
  [
    "@radix-ui/react-navigation-menu",
    "@radix-ui/react-navigation-menu@1.2.22",
  ],
  ["@radix-ui/react-popover", "@radix-ui/react-popover@1.1.23"],
  ["@radix-ui/react-slot", "@radix-ui/react-slot@1.3.3"],
  ["@radix-ui/react-toggle", "@radix-ui/react-toggle@1.1.18"],
  ["@radix-ui/react-toggle-group", "@radix-ui/react-toggle-group@1.1.19"],
  ["@radix-ui/react-tooltip", "@radix-ui/react-tooltip@1.2.16"],
  ["@tailwindcss/postcss", "@tailwindcss/postcss@4.3.3"],
  ["@types/bun", "@types/bun@1.3.14"],
  ["@types/d3", "@types/d3@7.4.3"],
  ["@types/node", "@types/node@26.2.0"],
  ["@types/pg", "@types/pg@8.21.0"],
  ["@types/react", "@types/react@19.2.18"],
  ["@types/react-dom", "@types/react-dom@19.2.4"],
  ["@vercel/analytics", "@vercel/analytics@2.0.1"],
  ["@vercel/speed-insights", "@vercel/speed-insights@2.0.0"],
  ["class-variance-authority", "class-variance-authority@0.7.1"],
  ["clsx", "clsx@2.1.1"],
  ["cmdk", "cmdk@1.1.1"],
  ["d3", "d3@7.9.0"],
  ["embla-carousel-react", "embla-carousel-react@8.6.0"],
  ["eslint", "eslint@10.8.1"],
  ["framer-motion", "framer-motion@12.43.0"],
  ["lucide-react", "lucide-react@1.31.0"],
  ["marked", "marked@18.0.9"],
  ["medium-zoom", "medium-zoom@1.1.0"],
  ["next-themes", "next-themes@0.4.6"],
  ["nuartz", "nuartz@0.2.0"],
  ["pagefind", "pagefind@1.5.2"],
  ["radix-ui", "radix-ui@1.6.7"],
  ["react", "react@19.2.8"],
  ["react-dom", "react-dom@19.2.8"],
  ["react-icons", "react-icons@5.7.0"],
  ["react-markdown", "react-markdown@10.1.0"],
  ["remark-breaks", "remark-breaks@4.0.0"],
  ["remark-gfm", "remark-gfm@4.0.1"],
  ["shiki", "shiki@4.4.3"],
  ["tailwind-merge", "tailwind-merge@3.6.0"],
  ["tailwindcss", "tailwindcss@4.3.3"],
  ["tailwindcss-animate", "tailwindcss-animate@1.0.7"],
  ["typescript", "typescript@5.9.3"],
  ["use-stick-to-bottom", "use-stick-to-bottom@1.1.6"],
])

const EXPECTED_PRODUCTION_OVERRIDE_RECORDS = [
  new Map([["postcss", "postcss@8.5.26"]]),
  new Map([["sharp", "sharp@0.35.3"]]),
]

export interface AuditCommandResult {
  exitCode: number
  stdout: string
  stderr: string
}

export interface AuditPolicyEvidence {
  production: AuditCommandResult
  complete: AuditCommandResult
  packageJson: string
  bunLock: string
}

function fail(message: string): never {
  throw new Error(`dependency audit policy failed: ${message}`)
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function parseAuditJson(result: AuditCommandResult, label: string) {
  try {
    const parsed: unknown = JSON.parse(result.stdout.trim())
    if (!isRecord(parsed)) {
      fail(`${label} audit JSON must be one object`)
    }
    return parsed
  } catch (error) {
    if (error instanceof SyntaxError) {
      fail(
        `${label} audit did not emit valid JSON; exit=${result.exitCode}, ` +
          `stderr=${result.stderr.trim()}`,
      )
    }
    throw error
  }
}

function requireEmptySuccessfulAudit(
  result: AuditCommandResult,
  label: string,
): void {
  if (result.exitCode !== 0) {
    fail(
      `${label} audit exited ${result.exitCode}; stderr=${result.stderr.trim()}`,
    )
  }
  const findings = parseAuditJson(result, label)
  if (Object.keys(findings).length !== 0) {
    fail(`${label} audit must contain zero findings`)
  }
}

function packageRecords(lock: string) {
  const records = new Map<string, { resolved: string; line: string }>()
  for (const line of lock.split(/\r?\n/u)) {
    const match = /^ {4}"([^"]+)": \["([^"]+)"/u.exec(line)
    if (!match) {
      continue
    }
    const [, key, resolved] = match
    if (records.has(key)) {
      fail(`bun.lock contains duplicate package record ${key}`)
    }
    records.set(key, { resolved, line })
  }
  return records
}

function requireExactRecords(
  records: Map<string, { resolved: string; line: string }>,
  expected: Map<string, string>,
  packagePrefix: string,
): void {
  const actual = new Map(
    [...records.entries()]
      .filter(([, record]) => record.resolved.startsWith(packagePrefix))
      .map(([key, record]) => [key, record.resolved]),
  )
  if (JSON.stringify([...actual]) !== JSON.stringify([...expected])) {
    fail(
      `${packagePrefix} lock paths drifted; ` +
        `actual=${JSON.stringify([...actual])}, ` +
        `expected=${JSON.stringify([...expected])}`,
    )
  }
}

function requireExpectedRecords(
  records: Map<string, { resolved: string; line: string }>,
  expected: Map<string, string>,
): void {
  for (const [key, resolved] of expected) {
    if (records.get(key)?.resolved !== resolved) {
      fail(
        `bun.lock package record ${key} drifted; ` +
          `actual=${JSON.stringify(records.get(key)?.resolved)}, ` +
          `expected=${JSON.stringify(resolved)}`,
      )
    }
  }
}

function requireLineFragments(
  records: Map<string, { resolved: string; line: string }>,
  key: string,
  fragments: string[],
): void {
  const record = records.get(key)
  if (!record) {
    fail(`bun.lock package record ${key} is missing`)
  }
  for (const fragment of fragments) {
    if (!record.line.includes(fragment)) {
      fail(`bun.lock package record ${key} lost ${fragment}`)
    }
  }
}

function requireDirectResolutionBaseline(
  records: Map<string, { resolved: string; line: string }>,
  dependencies: Record<string, unknown>,
  devDependencies: Record<string, unknown>,
): void {
  const actualDirectNames = [
    ...new Set([
      ...Object.keys(dependencies),
      ...Object.keys(devDependencies),
    ]),
  ].sort()
  const expectedDirectNames = [
    ...EXPECTED_SECURITY_DIRECT_RESOLUTIONS.keys(),
    ...EXPECTED_UNCHANGED_DIRECT_RESOLUTIONS.keys(),
  ].sort()
  if (
    JSON.stringify(actualDirectNames) !== JSON.stringify(expectedDirectNames)
  ) {
    fail(
      `direct dependency set drifted; ` +
        `actual=${JSON.stringify(actualDirectNames)}, ` +
        `expected=${JSON.stringify(expectedDirectNames)}`,
    )
  }

  requireExpectedRecords(records, EXPECTED_SECURITY_DIRECT_RESOLUTIONS)
  for (const [name, expected] of EXPECTED_UNCHANGED_DIRECT_RESOLUTIONS) {
    const actual = records.get(name)?.resolved
    if (actual !== expected) {
      fail(
        `unrelated direct resolution ${name} drifted; ` +
          `actual=${JSON.stringify(actual)}, ` +
          `expected=${JSON.stringify(expected)}`,
      )
    }
  }
}

function requireNativeAgentPins(
  records: Map<string, { resolved: string; line: string }>,
  dependencies: Record<string, unknown>,
): void {
  for (const [name, version] of EXPECTED_NATIVE_AGENT_PINS) {
    if (dependencies[name] !== version) {
      fail(
        `native agent dependency ${name} must be pinned exactly; ` +
          `actual=${JSON.stringify(dependencies[name])}, ` +
          `expected=${JSON.stringify(version)}`,
      )
    }
    if (records.get(name)?.resolved !== `${name}@${version}`) {
      fail(
        `native agent lock resolution ${name} drifted; ` +
          `actual=${JSON.stringify(records.get(name)?.resolved)}, ` +
          `expected=${JSON.stringify(`${name}@${version}`)}`,
      )
    }
  }
}

function requireAuthDatabasePins(
  records: Map<string, { resolved: string; line: string }>,
  dependencies: Record<string, unknown>,
): void {
  for (const [name, version] of EXPECTED_AUTH_DATABASE_PINS) {
    if (dependencies[name] !== version) {
      fail(
        `auth database dependency ${name} must be pinned exactly; ` +
          `actual=${JSON.stringify(dependencies[name])}, ` +
          `expected=${JSON.stringify(version)}`,
      )
    }
    if (records.get(name)?.resolved !== `${name}@${version}`) {
      fail(
        `auth database lock resolution ${name} drifted; ` +
          `actual=${JSON.stringify(records.get(name)?.resolved)}, ` +
          `expected=${JSON.stringify(`${name}@${version}`)}`,
      )
    }
  }
}

function requireDependencyBaseline(
  packageJson: string,
  bunLock: string,
): void {
  let manifest: unknown
  try {
    manifest = JSON.parse(packageJson)
  } catch {
    fail("package.json is not valid JSON")
  }
  if (!isRecord(manifest)) {
    fail("package.json must contain one object")
  }
  const dependencies = manifest.dependencies
  const devDependencies = manifest.devDependencies
  const overrides = manifest.overrides
  if (
    !isRecord(dependencies) ||
    !isRecord(devDependencies) ||
    !isRecord(overrides)
  ) {
    fail(
      "package.json must contain dependency, devDependency, and override objects",
    )
  }
  if ("eslint-config-next" in dependencies) {
    fail("eslint-config-next must not enter production dependencies")
  }
  if (devDependencies["eslint-config-next"] !== "^16.3.0") {
    fail("eslint-config-next devDependency drift requires exception review")
  }
  if (
    JSON.stringify(Object.keys(overrides).sort()) !==
    JSON.stringify(
      ["@types/react", "@types/react-dom", "postcss", "sharp"].sort(),
    )
  ) {
    fail("package.json override set drifted")
  }
  if (overrides.postcss !== "8.5.26" || overrides.sharp !== "0.35.3") {
    fail("reviewed production override versions drifted")
  }
  for (const [name, version] of EXPECTED_REACT_TYPE_OVERRIDES) {
    if (overrides[name] !== version) {
      fail(
        `reviewed React type override ${name} drifted; ` +
          `actual=${JSON.stringify(overrides[name])}, ` +
          `expected=${JSON.stringify(version)}`,
      )
    }
  }

  const records = packageRecords(bunLock)
  if ("patchedDependencies" in manifest) {
    fail("package.json must not reintroduce assistant-ui patches")
  }
  if (
    records.get("@assistant-ui/store")?.resolved !==
    EXPECTED_ASSISTANT_UI_STORE_RESOLUTION
  ) {
    fail("assistant-ui store must retain the upstream StrictMode fix")
  }
  requireNativeAgentPins(records, dependencies)
  requireAuthDatabasePins(records, dependencies)
  requireExactRecords(
    records,
    EXPECTED_BRACE_RECORDS,
    "brace-expansion@",
  )
  requireExactRecords(
    records,
    EXPECTED_LEGACY_MINIMATCH_RECORDS,
    "minimatch@3.",
  )
  requireExpectedRecords(records, EXPECTED_ESLINT_PLUGIN_RECORDS)
  for (const expected of EXPECTED_PRODUCTION_OVERRIDE_RECORDS) {
    const [[, resolved]] = expected
    requireExactRecords(records, expected, resolved.split("@")[0] + "@")
  }

  requireLineFragments(records, "eslint-config-next", [
    "eslint-config-next@16.3.0",
    '"eslint-plugin-import": "^2.32.0"',
    '"eslint-plugin-jsx-a11y": "^6.10.0"',
    '"eslint-plugin-react": "^7.37.0"',
  ])
  requireLineFragments(records, "next", [
    "next@16.3.0",
    '"postcss": "8.5.23"',
    '"sharp": "^0.35.3"',
  ])
  for (const plugin of EXPECTED_ESLINT_PLUGIN_RECORDS.keys()) {
    requireLineFragments(records, plugin, ['"minimatch": "^3.1.2"'])
    requireLineFragments(records, `${plugin}/minimatch`, [
      '"brace-expansion": "^1.1.7"',
    ])
  }
  requireDirectResolutionBaseline(records, dependencies, devDependencies)
}

export function validateAuditPolicy(evidence: AuditPolicyEvidence): void {
  requireEmptySuccessfulAudit(evidence.production, "production")
  requireEmptySuccessfulAudit(evidence.complete, "complete")
  requireDependencyBaseline(
    evidence.packageJson,
    evidence.bunLock,
  )
}

function runAudit(args: string[]): AuditCommandResult {
  const result = Bun.spawnSync({
    cmd: [process.execPath, "audit", ...args, "--json"],
    cwd: resolve(import.meta.dir, ".."),
    stdout: "pipe",
    stderr: "pipe",
  })
  const decoder = new TextDecoder()
  return {
    exitCode: result.exitCode,
    stdout: decoder.decode(result.stdout),
    stderr: decoder.decode(result.stderr),
  }
}

async function main(): Promise<void> {
  const webRoot = resolve(import.meta.dir, "..")
  const evidence: AuditPolicyEvidence = {
    production: runAudit(["--prod", "--audit-level=high"]),
    complete: runAudit(["--audit-level=high"]),
    packageJson: await readFile(resolve(webRoot, "package.json"), "utf8"),
    bunLock: await readFile(resolve(webRoot, "bun.lock"), "utf8"),
  }
  validateAuditPolicy(evidence)
  console.log(
    "dependency audit policy passed: production and complete " +
      "high/critical=0; " +
      `unrelated direct resolutions preserved=` +
      EXPECTED_UNCHANGED_DIRECT_RESOLUTIONS.size,
  )
}

if (import.meta.main) {
  await main()
}
