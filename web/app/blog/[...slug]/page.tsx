import { notFound, redirect } from "next/navigation"
import fs from "node:fs/promises"
import path from "node:path"
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
import allSlugsData from "@/.generated/all-slugs.json"

export const revalidate = false

const GENERATED_DIR = path.join(process.cwd(), ".generated")

async function loadPageData(slugStr: string) {
  try {
    const raw = await fs.readFile(
      path.join(GENERATED_DIR, "pages", `${slugStr}.json`),
      "utf-8"
    )
    return JSON.parse(raw)
  } catch {
    return null
  }
}

async function loadFolderData(slugStr: string) {
  try {
    const raw = await fs.readFile(
      path.join(GENERATED_DIR, "folders", `${slugStr}.json`),
      "utf-8"
    )
    return JSON.parse(raw)
  } catch {
    return null
  }
}

function findAlias(slugStr: string): string | null {
  // Check all page data for aliases — we stored aliases in all-slugs.json
  // But to resolve alias → canonical slug, we need to check pages
  // For now, we can check if this slug matches any alias in allSlugsData
  // The prebuild script generates alias entries in all-slugs.json
  // We need the mapping from alias → canonical slug
  // Since we don't store that mapping directly, check page files
  // This is a simplified approach — alias redirects happen rarely
  return null
}

export function generateStaticParams() {
  const data = allSlugsData as {
    pages: string[][]
    folders: string[][]
    aliases: string[][]
  }
  return [
    ...data.pages.map((slug) => ({ slug })),
    ...data.folders.map((slug) => ({ slug })),
    ...data.aliases.map((slug) => ({ slug })),
  ]
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string[] }>
}): Promise<Metadata> {
  const { slug } = await params
  const slugStr = slug.map(s => decodeURIComponent(s)).join("/")
  const pageData = await loadPageData(slugStr)

  if (!pageData) {
    // Folder listing pages
    const folderData = await loadFolderData(slugStr)
    if (folderData) {
      return {
        title: `${slug[slug.length - 1]} | Syshin's Blog`,
        robots: { index: false, follow: true },
      }
    }
    return {}
  }

  const title = pageData.frontmatter.title ?? slug[slug.length - 1]
  const description = pageData.frontmatter.description ?? ""
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
  const slug = encodedSlug.map((s) => decodeURIComponent(s))
  const slugStr = slug.join("/")

  const pageData = await loadPageData(slugStr)

  // Check if it's a folder
  if (!pageData) {
    const folderData = await loadFolderData(slugStr)
    if (folderData) {
      return (
        <div className="mx-auto max-w-6xl w-full px-6 py-10">
          <div className="mb-6">
            <Breadcrumb slug={slug} />
          </div>
          <div className="mb-6">
            <h1 className="text-2xl font-semibold tracking-tight">
              {slug[slug.length - 1]}
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              {folderData.files.length} notes
            </p>
          </div>
          <Separator className="mb-6" />
          <div className="space-y-2">
            {folderData.files.map(
              (file: {
                slug: string
                title: string
                description: string | null
                date: string | null
                tags: string[]
              }) => {
                return (
                  <Link
                    key={file.slug}
                    href={`/blog/${file.slug}`}
                    className="group block"
                  >
                    <div className="rounded-lg border px-4 py-3 transition-colors hover:bg-muted/50">
                      <div className="flex items-start justify-between gap-4">
                        <span className="font-medium group-hover:underline underline-offset-4">
                          {file.title}
                        </span>
                        {file.date && (
                          <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
                            {file.date}
                          </span>
                        )}
                      </div>
                      {file.description && (
                        <p className="mt-1 text-sm text-muted-foreground line-clamp-2">
                          {file.description}
                        </p>
                      )}
                      {file.tags.length > 0 && (
                        <div className="mt-2 flex flex-wrap gap-1">
                          {Array.from(new Set(file.tags)).map((tag) => (
                            <Badge
                              key={tag}
                              variant="secondary"
                              className="text-xs font-normal"
                            >
                              #{tag}
                            </Badge>
                          ))}
                        </div>
                      )}
                    </div>
                  </Link>
                )
              }
            )}
          </div>
        </div>
      )
    }

    // Alias redirects are handled via generateStaticParams — if the page wasn't found,
    // it's a true 404
    notFound()
  }

  // Filter out draft pages
  if (
    pageData.frontmatter.draft === true ||
    pageData.frontmatter.published === false
  ) {
    notFound()
  }

  const { html, frontmatter, toc, tags, backlinks, prevNext, readingTime: rt, date, modifiedDate } = pageData

  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "BlogPosting",
    headline: frontmatter.title ?? slugStr,
    datePublished: date,
    dateModified: modifiedDate,
    author: {
      "@type": "Person",
      name: "Syshin",
      url: "https://syshin0116.vercel.app",
    },
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
          {frontmatter.title && (
            <h1 className="text-3xl font-bold tracking-tight">
              {frontmatter.title}
            </h1>
          )}
          <div className="mt-3 flex flex-wrap items-center gap-3">
            {date && (
              <span className="text-sm text-muted-foreground tabular-nums">
                {date}
              </span>
            )}
            {modifiedDate && modifiedDate !== date && (
              <span className="text-sm text-muted-foreground">
                Updated {modifiedDate}
              </span>
            )}
            {rt >= 1 && (
              <span className="text-sm text-muted-foreground">
                {rt} min read
              </span>
            )}
            {date && tags.length > 0 && (
              <span className="text-muted-foreground">·</span>
            )}
            {tags.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {Array.from(new Set(tags as string[])).map((tag) => (
                  <Badge
                    key={tag}
                    variant="secondary"
                    className="text-xs font-normal hover:bg-muted"
                  >
                    #{tag}
                  </Badge>
                ))}
              </div>
            )}
          </div>
        </header>

        <Separator className="mb-8" />

        {frontmatter.summary && (
          <div className="callout callout-summary not-prose mb-8" data-callout="summary">
            <div className="callout-title">Summary</div>
            <p>{frontmatter.summary as string}</p>
          </div>
        )}

        <HeadingAnchors />
        <PopoverPreview />
        <article
          data-pagefind-body
          className="prose max-w-none"
          dangerouslySetInnerHTML={{ __html: html }}
        />
        <MermaidRendererDynamic />
        <CopyCode />
        <ImageZoom />

        <Backlinks backlinks={backlinks} />

        <PrevNextNav prevNext={prevNext} />

        <GiscusComments />
      </div>

      {/* Right sidebar */}
      <TableOfContents toc={toc}>
        <GraphViewDynamic currentSlug={slugStr} />
      </TableOfContents>
    </div>
  )
}

function PrevNextNav({
  prevNext,
}: {
  prevNext: {
    prev: { slug: string; title: string } | null
    next: { slug: string; title: string } | null
  }
}) {
  const { prev, next } = prevNext

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
              {prev.title}
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
              {next.title}
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
