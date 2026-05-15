#!/usr/bin/env bun
/**
 * Rebuild content/wiki/index.md from current wiki pages.
 *
 * Walks every .md under content/wiki/ (except index.md, log.md, .hashes,
 * .orphaned/), reads the frontmatter, and emits the standard index format
 * defined in conventions.md.
 *
 * Run via:
 *   bun .claude/skills/wiki-curator/scripts/rebuild-index.ts
 *
 * Always overwrites content/wiki/index.md. Idempotent.
 *
 * This exists so wiki-curator operations don't have to generate the
 * full index table token-by-token (a frequent timeout culprit).
 */
import fs from "node:fs/promises"
import path from "node:path"

const ROOT = process.cwd()
const WIKI_ROOT = path.join(ROOT, "content", "wiki")
const INDEX_PATH = path.join(WIKI_ROOT, "index.md")
const SKIP_FILES = new Set(["index.md", "log.md"])

interface Page {
  slug: string
  folder: string
  title: string
  type: string
  tags: string[]
  sources: string[]
  summary: string
  updated: string
}

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
    } else if (entry.name.endsWith(".md") && !SKIP_FILES.has(entry.name)) {
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

function getScalar(fm: string, key: string): string | null {
  const lines = fm.split("\n")
  for (let i = 0; i < lines.length; i++) {
    const m = lines[i].match(new RegExp(`^${key}:\\s*(.*)$`))
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

function getList(fm: string, key: string): string[] {
  const lines = fm.split("\n")
  const out: string[] = []
  let inside = false
  for (const line of lines) {
    if (new RegExp(`^${key}:`).test(line)) {
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

function escapePipe(s: string): string {
  return s.replace(/\|/g, "\\|").replace(/\n+/g, " ").trim()
}

async function readPage(file: string): Promise<Page | null> {
  const raw = await fs.readFile(file, "utf8")
  const split = splitFrontmatter(raw)
  if (!split) return null

  const slug = path.basename(file, ".md")
  const rel = path.relative(WIKI_ROOT, path.dirname(file))
  const folder = rel === "" ? "" : rel

  return {
    slug,
    folder,
    title: getScalar(split.fm, "title") ?? slug,
    type: getScalar(split.fm, "type") ?? "—",
    tags: getList(split.fm, "tags"),
    sources: getList(split.fm, "sources"),
    summary: getScalar(split.fm, "summary") ?? "",
    updated: getScalar(split.fm, "updated") ?? "—",
  }
}

function renderIndex(pages: Page[]): string {
  pages.sort((a, b) => a.slug.localeCompare(b.slug))

  const lines: string[] = []
  lines.push("# Wiki Index")
  lines.push("")
  lines.push("## All pages")
  lines.push("")
  lines.push("| Page | Summary | Type | Tags | Sources | Updated |")
  lines.push("|------|---------|------|------|---------|---------|")
  for (const p of pages) {
    const tagStr = p.tags.join(", ")
    lines.push(
      `| [[${p.slug}]] | ${escapePipe(p.summary)} | ${p.type} | ${escapePipe(tagStr)} | ${p.sources.length} | ${p.updated} |`,
    )
  }

  // Sources catalog
  const bySource = new Map<string, string[]>()
  for (const p of pages) {
    for (const src of p.sources) {
      if (!bySource.has(src)) bySource.set(src, [])
      bySource.get(src)!.push(p.slug)
    }
  }
  const sortedSources = [...bySource.keys()].sort()

  lines.push("")
  lines.push("## Sources catalog")
  lines.push("")
  lines.push("| Source | Wiki pages |")
  lines.push("|--------|------------|")
  for (const src of sortedSources) {
    const slugs = bySource.get(src)!.sort()
    lines.push(`| ${escapePipe(src)} | ${slugs.map((s) => `[[${s}]]`).join(", ")} |`)
  }

  lines.push("")
  return lines.join("\n")
}

async function main() {
  const pages: Page[] = []
  for await (const file of walk(WIKI_ROOT)) {
    const page = await readPage(file)
    if (page) pages.push(page)
  }

  const content = renderIndex(pages)
  await fs.writeFile(INDEX_PATH, content)
  console.log(`OK — rebuilt content/wiki/index.md (${pages.length} pages)`)
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
