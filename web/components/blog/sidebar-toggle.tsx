"use client"

import { useState } from "react"
import { PanelLeftClose, PanelLeft } from "lucide-react"
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Button } from "@/components/ui/button"
import { NavSidebar } from "@/components/blog/nav-sidebar"
import { useSidebar } from "./collapsible-sidebar"
import type { FileTreeNode } from "nuartz"

export function SidebarToggle({ tree }: { tree: FileTreeNode[] }) {
  const { open, toggle } = useSidebar()
  const [sheetOpen, setSheetOpen] = useState(false)

  const handleClick = () => {
    if (window.matchMedia("(min-width: 1024px)").matches) {
      toggle()
    } else {
      setSheetOpen(true)
    }
  }

  return (
    <>
      <Button
        variant="outline"
        size="icon"
        className="shadow-md rounded-full h-10 w-10"
        onClick={handleClick}
        aria-label={open ? "Hide sidebar" : "Show sidebar"}
      >
        {open
          ? <PanelLeftClose className="h-4 w-4" />
          : <PanelLeft className="h-4 w-4" />
        }
      </Button>

      <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
        <SheetContent side="left" className="w-72 p-4">
          <SheetHeader className="mb-4">
            <SheetTitle>Navigation</SheetTitle>
          </SheetHeader>
          <NavSidebar tree={tree} />
        </SheetContent>
      </Sheet>
    </>
  )
}
