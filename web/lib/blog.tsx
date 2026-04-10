import Link from "next/link"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import {
  Pagination,
  PaginationContent,
  PaginationItem,
  PaginationLink,
  PaginationPrevious,
  PaginationNext,
  PaginationEllipsis,
} from "@/components/ui/pagination"
import notesList from "@/.generated/notes-list.json"

export const NOTES_PER_PAGE = 10

export interface NoteEntry {
  slug: string
  title: string
  description: string | null
  summary: string | null
  date: string | null
  dateRaw: string | null
  tags: string[]
  draft: boolean
  category: string | null
}

export function getPublishedNotes(): NoteEntry[] {
  return notesList as NoteEntry[]
}

function blogPageHref(page: number): string {
  return page <= 1 ? "/blog" : `/blog/page/${page}`
}

export function BlogList({
  notes,
  currentPage,
  totalPages,
  totalCount,
}: {
  notes: NoteEntry[]
  currentPage: number
  totalPages: number
  totalCount: number
}): React.ReactElement {
  return (
    <div className="mx-auto max-w-3xl px-6 py-10">
      <div className="mb-8">
        <h1 className="text-2xl font-semibold tracking-tight">Recent Notes</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {totalCount} notes
        </p>
      </div>

      <Separator className="mb-8" />

      <div className="space-y-2">
        {notes.map((note) => {
          const title = note.title
          const date = note.date
          const tags = note.tags
          const category = note.category

          return (
            <Link key={note.slug} href={`/blog/${note.slug}`} className="group block">
              <div className="rounded-lg border px-4 py-3 transition-colors hover:bg-muted/50">
                <div className="flex items-start justify-between gap-4">
                  <span className="font-medium group-hover:underline underline-offset-4">
                    {title}
                  </span>
                  {date && (
                    <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
                      {date}
                    </span>
                  )}
                </div>
                {note.description && (
                  <p className="mt-1 text-sm text-muted-foreground line-clamp-2">
                    {note.description}
                  </p>
                )}
                <div className="mt-2 flex flex-wrap gap-1">
                  {category && (
                    <Badge variant="outline" className="text-xs font-normal border-primary/40 text-primary">
                      {category}
                    </Badge>
                  )}
                  {[...new Set(tags)].map((tag) => (
                    <Badge key={tag} variant="secondary" className="text-xs font-normal">
                      #{tag}
                    </Badge>
                  ))}
                </div>
              </div>
            </Link>
          )
        })}
      </div>

      {totalCount === 0 && (
        <div className="text-center py-20 text-muted-foreground">
          No notes found.
        </div>
      )}

      {totalPages > 1 && (
        <div className="mt-10">
          <BlogPagination currentPage={currentPage} totalPages={totalPages} />
        </div>
      )}
    </div>
  )
}

function BlogPagination({
  currentPage,
  totalPages,
}: {
  currentPage: number
  totalPages: number
}): React.ReactElement {
  const pageNumbers = getPageNumbers(currentPage, totalPages)

  return (
    <Pagination>
      <PaginationContent>
        <PaginationItem>
          <PaginationPrevious
            href={currentPage > 1 ? blogPageHref(currentPage - 1) : "#"}
            aria-disabled={currentPage <= 1}
            className={currentPage <= 1 ? "pointer-events-none opacity-50" : ""}
          />
        </PaginationItem>

        {pageNumbers.map((page, i) =>
          page === "ellipsis" ? (
            <PaginationItem key={`ellipsis-${i}`}>
              <PaginationEllipsis />
            </PaginationItem>
          ) : (
            <PaginationItem key={page}>
              <PaginationLink
                href={blogPageHref(page)}
                isActive={page === currentPage}
              >
                {page}
              </PaginationLink>
            </PaginationItem>
          )
        )}

        <PaginationItem>
          <PaginationNext
            href={currentPage < totalPages ? blogPageHref(currentPage + 1) : "#"}
            aria-disabled={currentPage >= totalPages}
            className={currentPage >= totalPages ? "pointer-events-none opacity-50" : ""}
          />
        </PaginationItem>
      </PaginationContent>
    </Pagination>
  )
}

function getPageNumbers(
  current: number,
  total: number
): (number | "ellipsis")[] {
  if (total <= 7) {
    return Array.from({ length: total }, (_, i) => i + 1)
  }

  const pages: (number | "ellipsis")[] = [1]

  if (current > 3) {
    pages.push("ellipsis")
  }

  const start = Math.max(2, current - 1)
  const end = Math.min(total - 1, current + 1)

  for (let i = start; i <= end; i++) {
    pages.push(i)
  }

  if (current < total - 2) {
    pages.push("ellipsis")
  }

  pages.push(total)

  return pages
}
