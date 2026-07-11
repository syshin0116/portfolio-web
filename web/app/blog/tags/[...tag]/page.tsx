import type { Metadata } from "next"
import Link from "next/link"
import { notFound } from "next/navigation"
import { Separator } from "@/components/ui/separator"
import tagsData from "@/.generated/tags.json"

interface TagEntry {
  slug: string
  title: string
  description: string | null
  date: string | null
}

const tagIndex = tagsData as Record<string, TagEntry[]>

export const revalidate = false
export const dynamicParams = false

export function generateStaticParams() {
  return Object.keys(tagIndex).map((tag) => ({ tag: tag.split("/") }))
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ tag: string[] }>
}): Promise<Metadata> {
  const { tag } = await params
  const tagName = tag.join("/")
  if (!tagIndex[tagName]) return {}

  return {
    title: `#${tagName} | Syshin's Blog`,
    description: `Posts tagged ${tagName}`,
    robots: { index: false, follow: true },
  }
}

export default async function TagPage({
  params,
}: {
  params: Promise<{ tag: string[] }>
}) {
  const { tag } = await params
  const tagName = tag.join("/")
  const entries = tagIndex[tagName]
  if (!entries) notFound()

  return (
    <div className="mx-auto w-full max-w-3xl px-6 py-10">
      <div className="mb-8">
        <h1 className="text-2xl font-semibold tracking-tight">#{tagName}</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {entries.length} {entries.length === 1 ? "note" : "notes"}
        </p>
      </div>

      <Separator className="mb-8" />

      <div className="space-y-2">
        {entries.map((entry) => (
          <Link
            key={entry.slug}
            href={`/blog/${entry.slug}`}
            className="group block rounded-lg border px-4 py-3 transition-colors hover:bg-muted/50"
          >
            <div className="flex items-start justify-between gap-4">
              <span className="font-medium group-hover:underline group-hover:underline-offset-4">
                {entry.title}
              </span>
              {entry.date && (
                <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                  {entry.date}
                </span>
              )}
            </div>
            {entry.description && (
              <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">
                {entry.description}
              </p>
            )}
          </Link>
        ))}
      </div>
    </div>
  )
}
