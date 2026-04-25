#!/usr/bin/env bun
/**
 * Migrate body `> [!summary]` callouts → frontmatter `summary:` field.
 *
 * Strategy:
 *   - Read every .md under content/ (excluding content/wiki/ and Untitled.md)
 *   - Parse frontmatter and body
 *   - Extract `> [!summary]` callout content from body (multi-line aware)
 *   - Decide:
 *       a) callout exists, frontmatter summary differs → REPLACE frontmatter summary with callout content, REMOVE body callout
 *       b) callout exists, frontmatter summary identical → REMOVE body callout (keep frontmatter)
 *       c) callout exists, no frontmatter summary → ADD frontmatter summary, REMOVE body callout
 *       d) no callout, frontmatter summary exists → leave alone
 *       e) neither → leave alone (logged)
 *
 * Run with --dry-run to preview, then again without to apply.
 *
 * Usage:
 *   bun scripts/migrate-summary.ts --dry-run [--limit 5] [--filter <substring>]
 *   bun scripts/migrate-summary.ts                                # apply to all
 */
import fs from "node:fs/promises"
import path from "node:path"

const CONTENT_DIR = path.join(import.meta.dir, "..", "content")
const args = process.argv.slice(2)
const dryRun = args.includes("--dry-run")
const limitFlag = args.indexOf("--limit")
const limit = limitFlag !== -1 ? parseInt(args[limitFlag + 1] ?? "0", 10) : 0
const filterFlag = args.indexOf("--filter")
const filterStr = filterFlag !== -1 ? args[filterFlag + 1] ?? "" : ""

interface Stats {
  total: number
  replaced: number  // case a: existing summary differed
  identical: number // case b: same; only removed callout
  added: number     // case c: no summary field; added it
  noCallout: number // case d
  neither: number   // case e
  errors: number
}

const stats: Stats = { total: 0, replaced: 0, identical: 0, added: 0, noCallout: 0, neither: 0, errors: 0 }

async function* walk(dir: string): AsyncGenerator<string> {
  const entries = await fs.readdir(dir, { withFileTypes: true })
  for (const entry of entries) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) {
      if (entry.name === "wiki") continue
      yield* walk(full)
    } else if (entry.name.endsWith(".md") && entry.name !== "Untitled.md") {
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

function getFrontmatterField(fm: string, key: string): { value: string | null; raw: string | null } {
  // Match `key: value` (single line) or `key: |`/`key: >` (block scalar)
  const lines = fm.split("\n")
  for (let i = 0; i < lines.length; i++) {
    const m = lines[i].match(new RegExp(`^${key}:\\s*(.*)$`))
    if (!m) continue
    const inline = m[1].trim()
    if (inline === "|" || inline === ">" || inline === "|-" || inline === ">-") {
      // Block scalar — gather indented lines
      const collected: string[] = []
      let j = i + 1
      while (j < lines.length) {
        const line = lines[j]
        if (/^\s+/.test(line)) {
          collected.push(line.replace(/^  /, ""))
          j++
        } else if (line === "") {
          collected.push("")
          j++
        } else break
      }
      const value = inline.startsWith(">") ? collected.join(" ").trim() : collected.join("\n").trim()
      return { value, raw: lines.slice(i, j).join("\n") }
    }
    // Inline: handle quoted/unquoted
    let value = inline
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1)
    }
    return { value: value.trim(), raw: lines[i] }
  }
  return { value: null, raw: null }
}

function extractCallout(body: string): { content: string; matchStart: number; matchEnd: number } | null {
  // Match `> [!summary]` followed by `> ` lines (allow ONE blank line between, which Obsidian collapses)
  const lines = body.split("\n")
  let i = 0
  while (i < lines.length) {
    if (/^\s*> \[!summary\]/i.test(lines[i])) {
      const start = i
      const collected: string[] = []
      // First line may have inline content after [!summary]
      const firstLine = lines[i].replace(/^\s*> \[!summary\][^\n]*/i, "").trim()
      if (firstLine) collected.push(firstLine)
      i++

      // Allow up to one blank line followed by another > continuation (common Obsidian quirk)
      // BUT stop if the next > line starts a new [!type] callout
      while (i < lines.length) {
        if (/^\s*>\s*\[!\w+\]/i.test(lines[i])) {
          // New callout starts — don't absorb
          break
        }
        if (/^\s*>/.test(lines[i])) {
          const stripped = lines[i].replace(/^\s*>\s?/, "")
          collected.push(stripped)
          i++
        } else if (
          lines[i] === "" &&
          i + 1 < lines.length &&
          /^\s*>/.test(lines[i + 1]) &&
          !/^\s*>\s*\[!\w+\]/i.test(lines[i + 1])
        ) {
          // Skip the blank, continue with next > line (only if it's NOT a new callout)
          collected.push("")
          i++
        } else {
          break
        }
      }

      const end = i
      // Skip trailing blank line if present (so we don't leave a gap after removal)
      const matchEnd = lines[end] === "" ? end + 1 : end
      const matchStart = start
      const beforeChars = lines.slice(0, matchStart).join("\n")
      const matchedChars = lines.slice(matchStart, matchEnd).join("\n")
      const offsetStart = beforeChars.length + (matchStart > 0 ? 1 : 0)
      const offsetEnd = offsetStart + matchedChars.length + (matchEnd < lines.length ? 1 : 0)
      return {
        content: collected.join("\n").replace(/\n{3,}/g, "\n\n").trim(),
        matchStart: offsetStart,
        matchEnd: offsetEnd,
      }
    }
    i++
  }
  return null
}

function setFrontmatterSummary(fm: string, value: string): string {
  // Encode value: if multi-line or contains special chars, use folded scalar `>`
  const isMultiline = value.includes("\n")
  const hasSpecial = /[:#>|&*!%@`]/.test(value)
  let encoded: string
  if (isMultiline) {
    encoded = `summary: |\n  ${value.replace(/\n/g, "\n  ")}`
  } else if (hasSpecial || value.length > 120) {
    // Use folded with line wrap or just quote
    encoded = `summary: ${JSON.stringify(value)}`
  } else {
    encoded = `summary: ${JSON.stringify(value)}`
  }

  const lines = fm.split("\n")
  // Find existing summary key (handle block scalar AND folded continuation lines)
  let i = 0
  while (i < lines.length) {
    const m = lines[i].match(/^summary:\s*(.*)$/)
    if (m) {
      const inline = m[1].trim()
      if (inline === "|" || inline === ">" || inline === "|-" || inline === ">-") {
        // Block scalar — gather indented + blank lines
        let j = i + 1
        while (j < lines.length && (/^\s+/.test(lines[j]) || lines[j] === "")) j++
        return [...lines.slice(0, i), encoded, ...lines.slice(j)].join("\n")
      }
      // Inline scalar — but YAML allows folded continuation on subsequent indented lines
      let j = i + 1
      while (j < lines.length && /^\s+\S/.test(lines[j])) j++
      return [...lines.slice(0, i), encoded, ...lines.slice(j)].join("\n")
    }
    i++
  }
  // Insert before the closing --- ... actually fm is already without the delimiters
  // Append at the end (or before published/modified if conventions matter — keep simple)
  return fm.trimEnd() + "\n" + encoded
}

function removeCalloutAt(body: string, start: number, end: number): string {
  return (body.slice(0, start) + body.slice(end)).replace(/^\n+/, "")
}

async function processFile(filePath: string): Promise<{ action: string; before: string | null; after: string | null }> {
  const raw = await fs.readFile(filePath, "utf8")
  const split = splitFrontmatter(raw)
  if (!split) return { action: "no-frontmatter", before: null, after: null }
  const { fm, body } = split

  const callout = extractCallout(body)
  const existing = getFrontmatterField(fm, "summary")

  if (!callout) {
    if (existing.value) {
      stats.noCallout++
      return { action: "no-callout (kept existing summary)", before: null, after: null }
    } else {
      stats.neither++
      return { action: "no callout, no summary", before: null, after: null }
    }
  }

  // Callout exists. Decide based on existing summary.
  let action: string
  if (existing.value === null) {
    action = "added"
    stats.added++
  } else if (existing.value === callout.content) {
    action = "identical (removed callout only)"
    stats.identical++
  } else {
    action = `replaced (existing="${existing.value.slice(0, 60)}…" → callout)`
    stats.replaced++
  }

  const newFm = setFrontmatterSummary(fm, callout.content)
  const newBody = removeCalloutAt(body, callout.matchStart, callout.matchEnd)
  const newRaw = `---\n${newFm}\n---\n${newBody}`

  return { action, before: raw, after: newRaw }
}

async function main() {
  const targets: string[] = []
  for await (const f of walk(CONTENT_DIR)) {
    if (filterStr && !f.includes(filterStr)) continue
    targets.push(f)
  }
  targets.sort()
  const slice = limit > 0 ? targets.slice(0, limit) : targets

  console.log(`Mode: ${dryRun ? "DRY RUN" : "APPLY"}`)
  console.log(`Files to process: ${slice.length}/${targets.length}`)
  console.log("")

  for (const file of slice) {
    stats.total++
    try {
      const result = await processFile(file)
      const rel = path.relative(CONTENT_DIR, file)
      console.log(`[${result.action}] ${rel}`)

      if (result.before && result.after) {
        if (dryRun) {
          // Show diff hint: existing vs new summary
          const existingSummary = getFrontmatterField(splitFrontmatter(result.before)!.fm, "summary").value
          const newSummary = getFrontmatterField(splitFrontmatter(result.after)!.fm, "summary").value
          if (existingSummary !== newSummary) {
            console.log(`  - was: ${existingSummary?.slice(0, 80) ?? "(none)"}`)
            console.log(`  + now: ${newSummary?.slice(0, 80)}`)
          }
        } else {
          await fs.writeFile(file, result.after)
        }
      }
    } catch (e) {
      stats.errors++
      console.log(`[ERROR] ${path.relative(CONTENT_DIR, file)}: ${(e as Error).message}`)
    }
  }

  console.log("")
  console.log("=== Stats ===")
  console.log(`Total processed:     ${stats.total}`)
  console.log(`Added summary:       ${stats.added}    (had callout, no fm summary)`)
  console.log(`Replaced summary:    ${stats.replaced} (had callout, fm summary differed)`)
  console.log(`Identical:           ${stats.identical} (callout = fm summary, just removed callout)`)
  console.log(`No callout:          ${stats.noCallout} (left untouched)`)
  console.log(`Neither:             ${stats.neither}`)
  console.log(`Errors:              ${stats.errors}`)
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
