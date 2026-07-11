#!/usr/bin/env bun
/**
 * Single verification gate for content/wiki/.
 *
 * Runs every deterministic check against every wiki page:
 *   1. wikilinks resolve (basename match)
 *   2. required frontmatter fields present
 *   3. no legacy frontmatter fields (coverage)
 *   4. body has no `## Summary` (lives in frontmatter)
 *   5. body has no `> [!summary]` callout (legacy)
 *   6. body has mandatory sections (`## Key Claims`, `## Footnotes`)
 *   7. every source is either a valid HTTPS URL or an existing repo-local file
 *   8. summary length sane (1–500 chars)
 *   9. tags non-empty
 *
 * Run via:
 *   bun .claude/skills/wiki-curator/scripts/verify.ts
 *
 * Exit 0 = all pass.
 * Exit 1 = at least one failure. Errors grouped by check, page paths included.
 *
 * This script is the gate every wiki-curator operation runs as its final step.
 * If it exits non-zero, the operation must NOT commit or push — fix first.
 */
import fs from "node:fs/promises"
import path from "node:path"

const ROOT = process.cwd()
const WIKI_ROOT = path.join(ROOT, "content", "wiki")

const REQUIRED_FRONTMATTER = ["title", "type", "tags", "sources", "summary", "created", "updated", "author", "draft"]
const FORBIDDEN_FRONTMATTER = ["coverage"]
const MANDATORY_SECTIONS = ["## Key Claims", "## Footnotes"]
const SUMMARY_MIN = 1
const SUMMARY_MAX = 500

interface Failure {
  check: string
  file: string
  detail: string
}

const failures: Failure[] = []

async function* walk(dir: string): AsyncGenerator<string> {
  let entries: { name: string; isDirectory(): boolean }[]
  try {
    entries = (await fs.readdir(dir, { withFileTypes: true })) as any
  } catch {
    return
  }
  for (const entry of entries) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) {
      if (entry.name.startsWith(".")) continue
      yield* walk(full)
    } else if (entry.name.endsWith(".md")) {
      yield full
    }
  }
}

function splitFrontmatter(raw: string): { fm: string; body: string } | null {
  if (!raw.startsWith("---\n")) return null
  const end = raw.indexOf("\n---\n", 4)
  if (end === -1) return null
  return { fm: raw.slice(4, end), body: raw.slice(end + 5) }
}

function fmHasField(fm: string, key: string): boolean {
  return new RegExp(`^${key}:`, "m").test(fm)
}

function fmGetSummary(fm: string): string | null {
  const lines = fm.split("\n")
  for (let i = 0; i < lines.length; i++) {
    const m = lines[i].match(/^summary:\s*(.*)$/)
    if (!m) continue
    const inline = m[1].trim()
    if (inline === "|" || inline === ">" || inline === "|-" || inline === ">-") {
      const collected: string[] = []
      let j = i + 1
      while (j < lines.length && (/^\s+/.test(lines[j]) || lines[j] === "")) {
        if (lines[j] !== "") collected.push(lines[j].trim())
        j++
      }
      return collected.join(inline.startsWith(">") ? " " : "\n").trim()
    }
    let v = inline
    if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) {
      v = v.slice(1, -1)
    }
    return v
  }
  return null
}

function fmGetSources(fm: string): string[] {
  const lines = fm.split("\n")
  const out: string[] = []
  let inside = false
  for (const line of lines) {
    if (/^sources:/.test(line)) {
      inside = true
      continue
    }
    if (inside) {
      const m = line.match(/^\s+-\s+(.*)$/)
      if (m) {
        out.push(m[1].trim().replace(/^["']|["']$/g, ""))
      } else if (/^\S/.test(line)) {
        break
      }
    }
  }
  return out
}

function fmHasNonEmptyTags(fm: string): boolean {
  const lines = fm.split("\n")
  let inside = false
  for (const line of lines) {
    if (/^tags:/.test(line)) {
      inside = true
      continue
    }
    if (inside) {
      if (/^\s+-\s+\S/.test(line)) return true
      if (/^\S/.test(line)) return false
    }
  }
  return false
}

function validateHttpsSource(source: string): string | null {
  try {
    if (!/^https:\/\/[^/?#]+(?:[/?#]|$)/i.test(source) || /[\s\\]/.test(source)) {
      return "is not a valid HTTPS URL"
    }

    const url = new URL(source)
    if (url.protocol !== "https:" || url.hostname === "") {
      return "must be an absolute HTTPS URL"
    }

    if (!url.hostname.includes(":")) {
      const hostname = url.hostname.replace(/\.$/, "")
      const validHostname = hostname.length > 0 && hostname.length <= 253 && hostname
        .split(".")
        .every((label) => /^[a-z\d](?:[a-z\d-]{0,61}[a-z\d])?$/i.test(label))
      if (!validHostname) return "is not a valid HTTPS URL"
    }
    return null
  } catch {
    return "is not a valid HTTPS URL"
  }
}

async function validateLocalSource(source: string): Promise<string | null> {
  if (path.isAbsolute(source)) return "must be a repository-relative path"

  const resolved = path.resolve(ROOT, source)
  const relative = path.relative(ROOT, resolved)
  if (relative === "" || relative.startsWith(`..${path.sep}`) || relative === ".." || path.isAbsolute(relative)) {
    return "must stay inside the repository"
  }

  try {
    const stat = await fs.stat(resolved)
    return stat.isFile() ? null : "does not point to a file"
  } catch {
    return "does not exist"
  }
}

async function collectSlugs(): Promise<Set<string>> {
  const slugs = new Set<string>()
  for await (const file of walk(WIKI_ROOT)) {
    slugs.add(path.basename(file, ".md"))
  }
  return slugs
}

const SKIP_FILES = new Set(["index.md", "log.md"])

async function main() {
  const slugs = await collectSlugs()
  const wikilinkRe = /\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]/g

  let pageCount = 0

  for await (const file of walk(WIKI_ROOT)) {
    const rel = path.relative(ROOT, file)
    const basename = path.basename(file)
    if (SKIP_FILES.has(basename)) continue

    const raw = await fs.readFile(file, "utf8")
    const split = splitFrontmatter(raw)
    if (!split) {
      failures.push({ check: "frontmatter", file: rel, detail: "no frontmatter block" })
      continue
    }
    const { fm, body } = split
    pageCount++

    // 2. required frontmatter fields
    for (const key of REQUIRED_FRONTMATTER) {
      if (!fmHasField(fm, key)) {
        failures.push({ check: "frontmatter-missing", file: rel, detail: `missing required field: ${key}` })
      }
    }

    // 3. forbidden frontmatter fields
    for (const key of FORBIDDEN_FRONTMATTER) {
      if (fmHasField(fm, key)) {
        failures.push({ check: "frontmatter-legacy", file: rel, detail: `legacy field present: ${key}` })
      }
    }

    // 4. body has no `## Summary`
    if (/^##\s+Summary\b/m.test(body)) {
      failures.push({ check: "body-summary-section", file: rel, detail: "body contains `## Summary` — summary belongs in frontmatter" })
    }

    // 5. body has no `> [!summary]` callout
    if (/^\s*>\s*\[!summary\]/im.test(body)) {
      failures.push({ check: "body-callout-summary", file: rel, detail: "body contains legacy `> [!summary]` callout — move to frontmatter" })
    }

    // 6. mandatory sections
    for (const section of MANDATORY_SECTIONS) {
      if (!new RegExp(`^${section.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`, "m").test(body)) {
        failures.push({ check: "missing-section", file: rel, detail: `missing mandatory section: ${section}` })
      }
    }

    // 7. sources are valid HTTPS URLs or existing repo-local files
    const sources = fmGetSources(fm)
    if (sources.length === 0) {
      failures.push({ check: "sources-empty", file: rel, detail: "sources frontmatter is empty" })
    }
    for (const src of sources) {
      if (/^https:\/\//i.test(src)) {
        const detail = validateHttpsSource(src)
        if (detail) failures.push({ check: "source-invalid", file: rel, detail: `${src} ${detail}` })
        continue
      }

      if (/^[a-z][a-z\d+.-]*:/i.test(src)) {
        failures.push({ check: "source-invalid", file: rel, detail: `${src} uses an unsupported URL scheme; only HTTPS is allowed` })
        continue
      }

      const detail = await validateLocalSource(src)
      if (detail) failures.push({ check: "source-invalid", file: rel, detail: `${src} ${detail}` })
    }

    // 8. summary length
    const summary = fmGetSummary(fm)
    if (summary !== null) {
      if (summary.length < SUMMARY_MIN) {
        failures.push({ check: "summary-empty", file: rel, detail: "summary is empty" })
      } else if (summary.length > SUMMARY_MAX) {
        failures.push({ check: "summary-too-long", file: rel, detail: `summary is ${summary.length} chars (max ${SUMMARY_MAX})` })
      }
    }

    // 9. tags non-empty
    if (!fmHasNonEmptyTags(fm)) {
      failures.push({ check: "tags-empty", file: rel, detail: "tags frontmatter is empty" })
    }

    // 1. wikilinks resolve
    const lines = body.split("\n")
    for (let i = 0; i < lines.length; i++) {
      let m: RegExpExecArray | null
      while ((m = wikilinkRe.exec(lines[i])) !== null) {
        const target = m[1].trim()
        if (!slugs.has(target)) {
          failures.push({ check: "wikilink-broken", file: rel, detail: `line ${i + 1}: [[${target}]] does not resolve` })
        }
      }
    }
  }

  if (failures.length === 0) {
    console.log(`OK — ${pageCount} pages, all checks pass.`)
    process.exit(0)
  }

  // Group by check
  const byCheck = new Map<string, Failure[]>()
  for (const f of failures) {
    if (!byCheck.has(f.check)) byCheck.set(f.check, [])
    byCheck.get(f.check)!.push(f)
  }

  console.log(`FAIL — ${failures.length} issue(s) across ${pageCount} pages:`)
  console.log("")
  for (const [check, items] of [...byCheck.entries()].sort()) {
    console.log(`### ${check} (${items.length})`)
    for (const f of items) {
      console.log(`  ${f.file}: ${f.detail}`)
    }
    console.log("")
  }

  process.exit(1)
}

main().catch((e) => {
  console.error(e)
  process.exit(2)
})
