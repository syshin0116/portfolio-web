import { getAllMarkdownFiles, renderMarkdown } from "nuartz"
import { NextResponse } from "next/server"
import { CONTENT_DIR } from "@/lib/content"

export const dynamic = "force-static"

export interface GraphNode {
  id: string
  title: string
  tags: string[]
  type: "note" | "tag"
}

export interface GraphLink {
  source: string
  target: string
}

export async function GET() {
  const files = await getAllMarkdownFiles(CONTENT_DIR)

  const rendered = await Promise.all(
    files.map(async (f) => ({ file: f, result: await renderMarkdown(f.raw) }))
  )

  const noteNodes: GraphNode[] = rendered.map(({ file, result }) => ({
    id: file.slug,
    title: String(file.frontmatter.title ?? file.slug.split("/").pop() ?? file.slug),
    tags: result.tags,
    type: "note",
  }))

  const linkSet = new Set<string>()
  const links: GraphLink[] = []

  const addLink = (source: string, target: string) => {
    const key = `${source}→${target}`
    if (!linkSet.has(key)) {
      linkSet.add(key)
      links.push({ source, target })
    }
  }

  for (const { file, result } of rendered) {
    for (const linkTarget of result.links) {
      const normalized = linkTarget.toLowerCase().replace(/\s+/g, "-")
      const match = files.find(
        (other) => other.slug === normalized || other.slug.endsWith("/" + normalized)
      )
      if (match && match.slug !== file.slug) {
        addLink(file.slug, match.slug)
      }
    }
  }

  const tagSet = new Set<string>()
  for (const node of noteNodes) {
    for (const tag of node.tags) tagSet.add(tag)
  }

  const tagNodes: GraphNode[] = [...tagSet].map((tag) => ({
    id: `tag/${tag}`,
    title: `#${tag}`,
    tags: [],
    type: "tag",
  }))

  for (const note of noteNodes) {
    for (const tag of note.tags) {
      addLink(note.id, `tag/${tag}`)
    }
  }

  return NextResponse.json({ nodes: [...noteNodes, ...tagNodes], links })
}
