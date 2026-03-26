import { notFound, redirect } from "next/navigation"
import { renderMarkdown, getAllMarkdownFiles } from "nuartz"
import fs from "node:fs/promises"
import path from "node:path"
import matter from "gray-matter"
import type { Metadata } from "next"
import Link from "next/link"
import { ChevronLeft, ChevronRight } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { Breadcrumb } from "@/components/blog/breadcrumb"
import { TableOfContents } from "@/components/blog/toc"
import { Backlinks } from "@/components/blog/backlinks"
import { MermaidRendererDynamic } from "@/components/blog/mermaid-renderer-dynamic"
import { GraphViewDynamic } from "@/components/blog/graph-view-dynamic"
import { HeadingAnchors } from "@/components/blog/heading-anchors"
import { PopoverPreview } from "@/components/blog/popover-preview"
import { CopyCode } from "@/components/blog/copy-code"
import { ImageZoom } from "@/components/blog/image-zoom"
import { GiscusComments } from "@/components/blog/giscus-comments"
import { CONTENT_DIR } from "@/lib/content"

export const revalidate = false

function readingTime(raw: string): number {
  const body = raw.replace(/^---[\s\S]*?---\n?/, "")
  const words = body.trim().split(/\s+/).filter(Boolean).length
  return Math.max(1, Math.ceil(words / 200))
}

async function getMarkdownFile(slug: string[]): Promise<string | null> {
  const filePath = path.join(CONTENT_DIR, ...slug) + ".md"
  try {
    return await fs.readFile(filePath, "utf-8")
  } catch {
    return null
  }
}

async function getAllSlugs(): Promise<string[][]> {
  async function walk(dir: string, base: string[] = []): Promise<string[][]> {
    const entries = await fs.readdir(dir, { withFileTypes: true })
    const results: string[][] = []
    for (const entry of entries) {
      if (entry.isDirectory()) {
        results.push(...(await walk(path.join(dir, entry.name), [...base, entry.name])))
      } else if (entry.name.endsWith(".md")) {
        results.push([...base, entry.name.replace(/\.md$/, "")])
      }
    }
    return results
  }
  try {
    return await walk(CONTENT_DIR)
  } catch {
    return []
  }
}

async function getFolderFiles(slug: string[]) {
  const folderPath = path.join(CONTENT_DIR, ...slug)
  try {
    const stat = await fs.stat(folderPath)
    if (!stat.isDirectory()) return null
  } catch {
    return null
  }
  const allFiles = await getAllMarkdownFiles(CONTENT_DIR)
  const prefix = slug.join("/") + "/"
  return allFiles
    .filter((f) => f.slug.startsWith(prefix))
    .sort((a, b) => {
      const da = a.frontmatter.date ? new Date(a.frontmatter.date).getTime() : 0
      const db = b.frontmatter.date ? new Date(b.frontmatter.date).getTime() : 0
      return db - da
    })
}

async function findByAlias(slug: string[]): Promise<string | null> {
  const aliasSlug = slug.join("/")
  const allFiles = await getAllMarkdownFiles(CONTENT_DIR)
  for (const file of allFiles) {
    const aliases: string[] = file.frontmatter.aliases ?? []
    if (aliases.some((a) => a === aliasSlug || a === `/${aliasSlug}`)) {
      return file.slug
    }
  }
  return null
}

export async function generateStaticParams() {
  const slugs = await getAllSlugs()

  const folderPaths = new Set<string>()
  for (const slug of slugs) {
    for (let i = 1; i < slug.length; i++) {
      folderPaths.add(slug.slice(0, i).join("/"))
    }
  }
  const folderParams = [...folderPaths].map((p) => ({ slug: p.split("/") }))

  const aliasParams: { slug: string[] }[] = []
  try {
    const allFiles = await getAllMarkdownFiles(CONTENT_DIR)
    for (const file of allFiles) {
      const aliases: string[] = file.frontmatter.aliases ?? []
      for (const alias of aliases) {
        const cleaned = alias.startsWith("/") ? alias.slice(1) : alias
        if (cleaned) aliasParams.push({ slug: cleaned.split("/") })
      }
    }
  } catch {
    // ignore
  }

  return [...slugs.map((slug) => ({ slug })), ...folderParams, ...aliasParams]
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string[] }>
}): Promise<Metadata> {
  const { slug } = await params
  const raw = await getMarkdownFile(slug)
  if (!raw) {
    // Folder listing pages — noindex to focus crawl budget on actual posts
    const folderPath = path.join(CONTENT_DIR, ...slug)
    try {
      const stat = await fs.stat(folderPath)
      if (stat.isDirectory()) {
        return {
          title: `${slug[slug.length - 1]} | Syshin's Blog`,
          robots: { index: false, follow: true },
        }
      }
    } catch {}
    return {}
  }
  const { data } = matter(raw)
  const title = data.title ?? slug[slug.length - 1]
  const description = data.description ?? ""
  const slugStr = slug.join("/")
  return {
    title: `${title} | Syshin's Blog`,
    description,
    alternates: {
      canonical: `/blog/${slugStr}`,
    },
    openGraph: {
      title,
      description,
      type: "article",
      url: `/blog/${slugStr}`,
      images: [{ url: "/og-image.png", width: 1200, height: 630 }],
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
      images: ["/og-image.png"],
    },
  }
}

export default async function BlogPostPage({
  params,
}: {
  params: Promise<{ slug: string[] }>
}) {
  const { slug: encodedSlug } = await params
  // Decode URL-encoded slug parts (handles Korean characters, etc.)
  const slug = encodedSlug.map(s => decodeURIComponent(s))
  const raw = await getMarkdownFile(slug)

  // Check if it's a folder
  if (!raw) {
    const folderFiles = await getFolderFiles(slug)
    if (folderFiles) {
      return (
        <div className="mx-auto max-w-6xl w-full px-6 py-10">
          <div className="mb-6">
            <Breadcrumb slug={slug} />
          </div>
          <div className="mb-6">
            <h1 className="text-2xl font-semibold tracking-tight">{slug[slug.length - 1]}</h1>
            <p className="mt-1 text-sm text-muted-foreground">{folderFiles.length} notes</p>
          </div>
          <Separator className="mb-6" />
          <div className="space-y-2">
            {folderFiles.map((file) => {
              const title = file.frontmatter.title ?? file.slug.split("/").pop()
              const date = file.frontmatter.date
                ? new Date(file.frontmatter.date).toLocaleDateString("en-CA")
                : null
              const tags: string[] = file.frontmatter.tags ?? []
              return (
                <Link key={file.slug} href={`/blog/${file.slug}`} className="group block">
                  <div className="rounded-lg border px-4 py-3 transition-colors hover:bg-muted/50">
                    <div className="flex items-start justify-between gap-4">
                      <span className="font-medium group-hover:underline underline-offset-4">{title}</span>
                      {date && <span className="shrink-0 text-xs text-muted-foreground tabular-nums">{date}</span>}
                    </div>
                    {file.frontmatter.description && (
                      <p className="mt-1 text-sm text-muted-foreground line-clamp-2">{file.frontmatter.description}</p>
                    )}
                    {tags.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1">
                        {Array.from(new Set(tags)).map((tag) => (
                          <Badge key={tag} variant="secondary" className="text-xs font-normal">#{tag}</Badge>
                        ))}
                      </div>
                    )}
                  </div>
                </Link>
              )
            })}
          </div>
        </div>
      )
    }

    // Check aliases
    const canonicalSlug = await findByAlias(slug)
    if (canonicalSlug) {
      redirect(`/blog/${canonicalSlug}`)
    }
    notFound()
  }

  // Filter out draft pages
  const { data: rawFrontmatter } = matter(raw)
  if (rawFrontmatter.draft === true || rawFrontmatter.published === false) {
    notFound()
  }

  const files = await getAllMarkdownFiles(CONTENT_DIR)

  // Build filename → full slug lookup for Obsidian-style wikilink resolution
  const slugByName = new Map<string, string>()
  for (const f of files) {
    const name = f.slug.split("/").pop()!.toLowerCase().replace(/\s+/g, "-")
    if (!slugByName.has(name)) slugByName.set(name, f.slug)
  }
  const resolveLink = (target: string): string => {
    const normalized = target.toLowerCase().replace(/\s+/g, "-").replace(/[^\p{L}\p{N}_/-]/gu, "")
    const exact = files.find((f) => f.slug === normalized)
    if (exact) return `/blog/${exact.slug}`
    const byName = slugByName.get(normalized.split("/").pop()!)
    if (byName) return `/blog/${byName}`
    return `/blog/${normalized}`
  }

  const knownSlugs = new Set(files.map((f) => f.slug))
  const rawResult = await renderMarkdown(raw, { resolveLink, knownSlugs, filePath: slug.join("/") + ".md" })

  // Rewrite /api/content/ to /blog/api/content/ for the blog prefix
  const result = {
    ...rawResult,
    html: rawResult.html.replaceAll('/api/content/', '/blog/api/content/'),
  }

  // Build backlink index — use raw text wikilink detection instead of full renderMarkdown
  const slugStr = slug.join("/")
  const wikilinkPattern = /\[\[([^\]|]+)(?:\|[^\]]+)?\]\]/g
  const backlinkSlugs: { slug: string; title: string }[] = []
  for (const file of files) {
    if (file.slug === slugStr) continue
    const matches = file.raw.matchAll(wikilinkPattern)
    for (const match of matches) {
      const target = match[1].trim()
      const normalized = target.toLowerCase().replace(/\s+/g, "-").replace(/[^\p{L}\p{N}_/-]/gu, "")
      const targetName = normalized.split("/").pop()!
      const currentName = slugStr.split("/").pop()!.toLowerCase().replace(/\s+/g, "-")
      if (normalized === slugStr.toLowerCase() || targetName === currentName) {
        backlinkSlugs.push({
          slug: file.slug,
          title: file.frontmatter.title ?? file.slug.split("/").pop()!,
        })
        break
      }
    }
  }
  const backlinks = backlinkSlugs.map((b) => {
    const file = files.find((f) => f.slug === b.slug)
    const rawBody = (file?.raw ?? "").replace(/^---[\s\S]*?---\n?/, "").trim()
    const excerpt = rawBody.slice(0, 150).replace(/\n/g, " ").trim()
    return { slug: b.slug, title: b.title, excerpt }
  })

  const date = result.frontmatter.date
    ? new Date(result.frontmatter.date).toLocaleDateString("en-CA")
    : null

  const filePath = path.join(CONTENT_DIR, ...slug) + ".md"
  const fileStat = await fs.stat(filePath)
  const modifiedDate = fileStat.mtime.toLocaleDateString("en-CA")

  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "BlogPosting",
    headline: result.frontmatter.title ?? slugStr,
    datePublished: date,
    dateModified: modifiedDate,
    author: { "@type": "Person", name: "Syshin", url: "https://syshin0116.vercel.app" },
    url: `https://syshin0116.vercel.app/blog/${slugStr}`,
  }

  return (
    <div className="flex min-h-0 gap-8 px-6 py-8 max-w-6xl mx-auto w-full">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />
      {/* Main content */}
      <div className="min-w-0 flex-1">
        {slug.length > 1 && (
          <div className="mb-6">
            <Breadcrumb slug={slug} />
          </div>
        )}

        <header className="mb-6">
          {result.frontmatter.title && (
            <h1 className="text-3xl font-bold tracking-tight">{result.frontmatter.title}</h1>
          )}
          <div className="mt-3 flex flex-wrap items-center gap-3">
            {date && (
              <span className="text-sm text-muted-foreground tabular-nums">{date}</span>
            )}
            {modifiedDate && modifiedDate !== date && (
              <span className="text-sm text-muted-foreground">Updated {modifiedDate}</span>
            )}
            {readingTime(raw) >= 1 && (
              <span className="text-sm text-muted-foreground">{readingTime(raw)} min read</span>
            )}
            {date && result.tags.length > 0 && (
              <span className="text-muted-foreground">·</span>
            )}
            {result.tags.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {Array.from(new Set(result.tags)).map((tag) => (
                  <Badge key={tag} variant="secondary" className="text-xs font-normal hover:bg-muted">
                    #{tag}
                  </Badge>
                ))}
              </div>
            )}
          </div>
          {result.frontmatter.description && (
            <p className="mt-3 text-base text-muted-foreground">{result.frontmatter.description}</p>
          )}
        </header>

        <Separator className="mb-8" />

        <HeadingAnchors />
        <PopoverPreview />
        <article
          data-pagefind-body
          className="prose max-w-none"
          dangerouslySetInnerHTML={{ __html: result.html }}
        />
        <MermaidRendererDynamic />
        <CopyCode />
        <ImageZoom />

        <Backlinks backlinks={backlinks} />

        <PrevNextNav currentSlug={slugStr} files={files} />

        <GiscusComments />
      </div>

      {/* Right sidebar */}
      <TableOfContents toc={result.toc}>
        <GraphViewDynamic currentSlug={slugStr} />
      </TableOfContents>
    </div>
  )
}

function PrevNextNav({
  currentSlug,
  files,
}: {
  currentSlug: string
  files: { slug: string; frontmatter: Record<string, unknown> }[]
}) {
  const parts = currentSlug.split("/")
  const folder = parts.slice(0, -1).join("/")
  const siblings = files
    .filter((f) => {
      const fParts = f.slug.split("/")
      const fFolder = fParts.slice(0, -1).join("/")
      return fFolder === folder
    })
    .sort((a, b) => a.slug.localeCompare(b.slug))

  const idx = siblings.findIndex((f) => f.slug === currentSlug)
  if (idx === -1) return null

  const prev = idx > 0 ? siblings[idx - 1] : null
  const next = idx < siblings.length - 1 ? siblings[idx + 1] : null

  if (!prev && !next) return null

  return (
    <nav className="mt-12 flex items-stretch gap-4 border-t pt-6">
      {prev ? (
        <Link
          href={`/blog/${prev.slug}`}
          className="group flex flex-1 items-center gap-2 rounded-lg border px-4 py-3 transition-colors hover:bg-muted/50"
        >
          <ChevronLeft className="h-4 w-4 shrink-0 text-muted-foreground" />
          <div className="min-w-0">
            <div className="text-xs text-muted-foreground">Previous</div>
            <div className="truncate text-sm font-medium group-hover:underline">
              {(prev.frontmatter.title as string) ?? prev.slug.split("/").pop()}
            </div>
          </div>
        </Link>
      ) : (
        <div className="flex-1" />
      )}
      {next ? (
        <Link
          href={`/blog/${next.slug}`}
          className="group flex flex-1 items-center justify-end gap-2 rounded-lg border px-4 py-3 text-right transition-colors hover:bg-muted/50"
        >
          <div className="min-w-0">
            <div className="text-xs text-muted-foreground">Next</div>
            <div className="truncate text-sm font-medium group-hover:underline">
              {(next.frontmatter.title as string) ?? next.slug.split("/").pop()}
            </div>
          </div>
          <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
        </Link>
      ) : (
        <div className="flex-1" />
      )}
    </nav>
  )
}
