import type { Metadata } from "next"
import { getPublishedNotes, BlogList, NOTES_PER_PAGE } from "@/lib/blog"

export const revalidate = false

export const metadata: Metadata = {
  title: "Blog | Syshin's Portfolio",
  description: "AI, 개발, 프로젝트에 관한 기술 블로그",
}

export default async function BlogPage() {
  const published = await getPublishedNotes()

  const totalPages = Math.max(1, Math.ceil(published.length / NOTES_PER_PAGE))
  const paginatedNotes = published.slice(0, NOTES_PER_PAGE)

  return (
    <BlogList
      notes={paginatedNotes}
      currentPage={1}
      totalPages={totalPages}
      totalCount={published.length}
    />
  )
}
