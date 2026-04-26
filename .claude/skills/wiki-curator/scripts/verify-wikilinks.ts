#!/usr/bin/env bun
/**
 * Verify every [[wikilink]] in content/wiki/ resolves to an actual page.
 *
 * Wiki pages are matched by basename (slug), regardless of folder. This
 * mirrors how Nuartz/Obsidian resolve links — `[[zettelkasten]]` finds
 * `concepts/zettelkasten.md` or `zettelkasten.md` equally.
 *
 * Usage:
 *   bun .claude/skills/wiki-curator/scripts/verify-wikilinks.ts
 *
 * Exit code: 0 = all valid, 1 = broken links found.
 *
 * Output: report to stdout. Each broken link is one line:
 *   <source-file>:<line> [[<broken-target>]]
 */
import fs from "node:fs/promises"
import path from "node:path"

const WIKI_ROOT = path.join(process.cwd(), "content", "wiki")

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
      // Skip .orphaned/ and other dotted dirs
      if (entry.name.startsWith(".")) continue
      yield* walk(full)
    } else if (entry.name.endsWith(".md")) {
      yield full
    }
  }
}

async function collectSlugs(): Promise<Set<string>> {
  const slugs = new Set<string>()
  for await (const file of walk(WIKI_ROOT)) {
    const slug = path.basename(file, ".md")
    slugs.add(slug)
  }
  return slugs
}

interface BrokenLink {
  file: string
  line: number
  target: string
}

async function findBrokenLinks(slugs: Set<string>): Promise<BrokenLink[]> {
  const broken: BrokenLink[] = []
  // [[Target]] or [[Target|alias]] or [[Target#heading]]
  // Capture group: text up to first | or # or ]
  const pattern = /\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]/g

  for await (const file of walk(WIKI_ROOT)) {
    const content = await fs.readFile(file, "utf8")
    const lines = content.split("\n")
    for (let i = 0; i < lines.length; i++) {
      let m: RegExpExecArray | null
      while ((m = pattern.exec(lines[i])) !== null) {
        const target = m[1].trim()
        if (!slugs.has(target)) {
          broken.push({
            file: path.relative(process.cwd(), file),
            line: i + 1,
            target,
          })
        }
      }
    }
  }
  return broken
}

async function main() {
  const slugs = await collectSlugs()
  const broken = await findBrokenLinks(slugs)

  if (broken.length === 0) {
    console.log(`OK — ${slugs.size} pages, all wikilinks resolve.`)
    process.exit(0)
  }

  console.log(`FAIL — ${broken.length} broken wikilink(s) across ${slugs.size} pages:`)
  console.log("")
  for (const b of broken) {
    console.log(`  ${b.file}:${b.line}  [[${b.target}]]`)
  }
  console.log("")
  console.log(`Available slugs (${slugs.size}):`)
  console.log(
    [...slugs]
      .sort()
      .map((s) => `  ${s}`)
      .join("\n"),
  )
  process.exit(1)
}

main().catch((e) => {
  console.error(e)
  process.exit(2)
})
