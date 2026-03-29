import { notFound, redirect } from "next/navigation"
import type { Metadata } from "next"
import { getPublishedNotes, BlogList, NOTES_PER_PAGE } from "@/lib/blog"

export const revalidate = false

export async function generateStaticParams() {
  const published = await getPublishedNotes()
  const totalPages = Math.max(1, Math.ceil(published.length / NOTES_PER_PAGE))

  // Generate params for page 2 onwards (page 1 is handled by /blog)
  return Array.from({ length: totalPages - 1 }, (_, i) => ({
    page: String(i + 2),
  }))
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ page: string }>
}): Promise<Metadata> {
  const { page } = await params
  return {
    title: `Blog – Page ${page} | Syshin's Portfolio`,
    description: "AI, 개발, 프로젝트에 관한 기술 블로그",
  }
}

export default async function BlogPaginatedPage({
  params,
}: {
  params: Promise<{ page: string }>
}) {
  const { page: pageParam } = await params
  const currentPage = parseInt(pageParam, 10)

  // Redirect page 1 to /blog
  if (currentPage === 1) {
    redirect("/blog")
  }

  if (isNaN(currentPage) || currentPage < 1) {
    notFound()
  }

  const published = await getPublishedNotes()
  const totalPages = Math.max(1, Math.ceil(published.length / NOTES_PER_PAGE))

  if (currentPage > totalPages) {
    notFound()
  }

  const startIndex = (currentPage - 1) * NOTES_PER_PAGE
  const paginatedNotes = published.slice(startIndex, startIndex + NOTES_PER_PAGE)

  return (
    <BlogList
      notes={paginatedNotes}
      currentPage={currentPage}
      totalPages={totalPages}
      totalCount={published.length}
    />
  )
}
