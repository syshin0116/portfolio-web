import "katex/dist/katex.min.css"
import { NavSidebar } from "@/components/blog/nav-sidebar"
import { BlogTreeProvider } from "@/components/blog/blog-tree-provider"
import { CommandPaletteDynamic } from "@/components/blog/command-palette-dynamic"
import { Navbar } from "@/components/navbar"
import fileTree from "@/.generated/file-tree.json"

export default function BlogLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const tree = fileTree as any

  return (
    <BlogTreeProvider tree={tree}>
      <a href="#main-content" className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-[100] focus:rounded-md focus:bg-background focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:shadow-lg focus:border">
        Skip to content
      </a>
      <Navbar />

      <div
        className="flex flex-1 mx-auto w-full max-w-[1440px]"
        style={{ "--sidebar-width": "16rem", "--toc-width": "14rem" } as React.CSSProperties}
      >
        <aside className="hidden lg:block w-[var(--sidebar-width)] shrink-0 border-r sticky top-[57px] self-start h-[calc(100vh-57px)] overflow-y-auto scroll-mask">
          <div className="pl-6 pr-4 pt-4 pb-6">
            <NavSidebar tree={tree} />
          </div>
        </aside>

        <main id="main-content" className="min-w-0 flex-1">
          {children}
        </main>
      </div>

      <CommandPaletteDynamic />
    </BlogTreeProvider>
  )
}
