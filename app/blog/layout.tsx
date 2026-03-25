import "katex/dist/katex.min.css"
import { unstable_cache } from "next/cache"
import { getAllMarkdownFiles, buildFileTree } from "nuartz"
import { NavSidebar } from "@/components/blog/nav-sidebar"
import { BlogTreeProvider } from "@/components/blog/blog-tree-provider"
import { CommandPaletteDynamic } from "@/components/blog/command-palette-dynamic"
import { Navbar } from "@/components/navbar"
import { CONTENT_DIR } from "@/lib/content"

const getCachedBlogData = unstable_cache(
  async () => {
    const files = await getAllMarkdownFiles(CONTENT_DIR)
    return {
      tree: buildFileTree(files, { sortBy: "date" }),
    }
  },
  ["blog-layout-data"],
  { revalidate: false }
)

export default async function BlogLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const { tree } = await getCachedBlogData()

  return (
    <BlogTreeProvider tree={tree}>
      <Navbar />

      <div
        className="flex flex-1 mx-auto w-full max-w-[1440px]"
        style={{ "--sidebar-width": "16rem", "--toc-width": "14rem" } as React.CSSProperties}
      >
        <aside className="hidden lg:block w-[var(--sidebar-width)] shrink-0 border-r sticky top-[57px] self-start h-[calc(100vh-57px)] overflow-y-auto">
          <div className="pl-6 pr-4 pt-4 pb-6">
            <NavSidebar tree={tree} />
          </div>
        </aside>

        <main className="min-w-0 flex-1">
          {children}
        </main>
      </div>

      <CommandPaletteDynamic />
    </BlogTreeProvider>
  )
}
