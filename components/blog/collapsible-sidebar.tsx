"use client"

import { createContext, useContext, useState, useCallback, useRef, useEffect } from "react"
import { NavSidebar } from "@/components/blog/nav-sidebar"
import type { FileTreeNode } from "nuartz"

interface SidebarContextValue {
  open: boolean
  toggle: () => void
}

const SidebarContext = createContext<SidebarContextValue>({ open: true, toggle: () => {} })

export function useSidebar() {
  return useContext(SidebarContext)
}

export function SidebarProvider({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(true)
  const toggle = useCallback(() => setOpen(o => !o), [])

  return (
    <SidebarContext.Provider value={{ open, toggle }}>
      {children}
    </SidebarContext.Provider>
  )
}

const OPEN_DURATION = 300
const CLOSE_DURATION = 200

export function SidebarLayout({ tree, children }: { tree: FileTreeNode[]; children: React.ReactNode }) {
  const { open } = useSidebar()
  const asideRef = useRef<HTMLElement>(null)
  const innerRef = useRef<HTMLDivElement>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout>>(undefined)
  const isInitial = useRef(true)

  useEffect(() => {
    const aside = asideRef.current
    const inner = innerRef.current
    if (!aside || !inner) return

    if (isInitial.current) {
      isInitial.current = false
      aside.style.width = open ? `${inner.offsetWidth}px` : "0"
      aside.style.opacity = open ? "1" : "0"
      if (open) requestAnimationFrame(() => aside.style.removeProperty("width"))
      return
    }

    clearTimeout(timerRef.current)

    if (open) {
      const targetWidth = inner.offsetWidth
      aside.style.width = `${targetWidth}px`
      aside.style.opacity = "1"
      aside.style.transitionDuration = `${OPEN_DURATION}ms`
      timerRef.current = setTimeout(() => {
        aside.style.removeProperty("width")
      }, OPEN_DURATION)
    } else {
      aside.style.width = `${aside.offsetWidth}px`
      aside.style.transitionDuration = `${CLOSE_DURATION}ms`
      requestAnimationFrame(() => {
        aside.style.width = "0"
        aside.style.opacity = "0"
      })
    }
  }, [open])

  return (
    <div
      className="flex flex-1 mx-auto w-full max-w-[1440px]"
      style={{ "--sidebar-width": "16rem", "--toc-width": "14rem" } as React.CSSProperties}
    >
      <aside
        ref={asideRef}
        className="hidden lg:block shrink-0 border-r overflow-hidden transition-[width,opacity] ease-in-out"
        style={{ width: "var(--sidebar-width)" }}
      >
        <div ref={innerRef} className="w-[var(--sidebar-width)]">
          <div className="sticky top-[73px] h-[calc(100vh-73px)] overflow-y-auto">
            <div className="pl-6 pr-4 pt-4 pb-6">
              <NavSidebar tree={tree} />
            </div>
          </div>
        </div>
      </aside>
      <main className="min-w-0 flex-1">
        {children}
      </main>
    </div>
  )
}
