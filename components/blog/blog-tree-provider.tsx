"use client"

import { createContext, useContext } from "react"
import type { FileTreeNode } from "nuartz"

const BlogTreeContext = createContext<FileTreeNode[]>([])

export function BlogTreeProvider({ tree, children }: { tree: FileTreeNode[]; children: React.ReactNode }) {
  return (
    <BlogTreeContext.Provider value={tree}>
      {children}
    </BlogTreeContext.Provider>
  )
}

export function useBlogTree() {
  return useContext(BlogTreeContext)
}
