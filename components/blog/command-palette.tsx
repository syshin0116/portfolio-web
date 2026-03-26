"use client"

import { useEffect, useState, useCallback, useRef, useDeferredValue } from "react"
import { useRouter } from "next/navigation"
import { FileText, Hash, Loader2 } from "lucide-react"
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command"
import type { SearchEntry } from "nuartz"

interface Result {
  slug: string
  title: string
  excerpt: string
  type: "note" | "tag"
}

interface PagefindResult {
  url: string
  meta?: { title?: string }
  excerpt?: string
}

interface PagefindResponse {
  results: Array<{ data: () => Promise<PagefindResult> }>
}

type Pagefind = {
  init: () => Promise<void>
  search: (query: string) => Promise<PagefindResponse>
}

export function CommandPalette() {
  const router = useRouter()
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState("")
  const [results, setResults] = useState<{ notes: Result[]; tags: Result[] }>({ notes: [], tags: [] })
  const [ready, setReady] = useState(false)
  const pfRef = useRef<Pagefind | null>(null)
  const entriesRef = useRef<SearchEntry[]>([])
  const useFallbackRef = useRef(false)
  const initRef = useRef(false)
  const deferredQuery = useDeferredValue(query)

  // On mount, try Pagefind first; fall back to API search index for dev mode
  useEffect(() => {
    if (initRef.current) return
    initRef.current = true
    ;(async () => {
      try {
        const pf: Pagefind = await Function('return import("/pagefind/pagefind.js")')()
        await pf.init()
        pfRef.current = pf
      } catch {
        // Pagefind not available (dev mode) — fall back to API
        useFallbackRef.current = true
        const res = await fetch("/blog/api/search")
        entriesRef.current = await res.json()
      }
      setReady(true)
    })()
  }, [])

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault()
        setOpen((o) => !o)
      }
    }
    document.addEventListener("keydown", handler)
    return () => document.removeEventListener("keydown", handler)
  }, [])

  const search = useCallback(
    async (q: string) => {
      if (!q.trim()) { setResults({ notes: [], tags: [] }); return }

      // Tag search (works in both modes)
      if (q.startsWith("#")) {
        if (useFallbackRef.current) {
          const lower = q.slice(1).toLowerCase()
          const tags = [...new Set(entriesRef.current.flatMap((e) => e.tags))]
            .filter((t) => t.toLowerCase().includes(lower))
            .slice(0, 5)
            .map((t) => ({ slug: `tags/${t}`, title: `#${t}`, excerpt: "Browse tag", type: "tag" as const }))
          setResults({ notes: [], tags })
        }
        return
      }

      // Pagefind search
      const pf = pfRef.current
      if (pf) {
        const response = await pf.search(q)
        const items = await Promise.all(
          response.results.slice(0, 7).map((r) => r.data())
        )
        const notes: Result[] = items.map((item) => {
          let slug = item.url
          slug = slug.replace(/^\//, "").replace(/\/index\.html$/, "").replace(/\.html$/, "")
          return {
            slug,
            title: item.meta?.title ?? slug,
            excerpt: item.excerpt ?? "",
            type: "note" as const,
          }
        })
        setResults({ notes, tags: [] })
        return
      }

      // Fallback: substring matching on API data
      if (useFallbackRef.current) {
        const lower = q.toLowerCase()
        const notes: Result[] = entriesRef.current
          .filter((e) => e.title.toLowerCase().includes(lower) || e.content.toLowerCase().includes(lower))
          .slice(0, 7)
          .map((e) => {
            const pos = e.content.toLowerCase().indexOf(lower)
            const start = Math.max(0, pos - 50)
            const excerpt = pos >= 0
              ? "\u2026" + e.content.slice(start, start + 120) + "\u2026"
              : (e.description ?? e.content.slice(0, 120) + "\u2026")
            return { slug: e.slug, title: e.title, excerpt, type: "note" as const }
          })
        setResults({ notes, tags: [] })
      }
    },
    []
  )

  useEffect(() => { search(deferredQuery) }, [deferredQuery, search])

  const handleSelect = (slug: string) => {
    router.push(`/blog/${slug}`)
    setOpen(false)
    setQuery("")
  }

  const isSearching = query !== deferredQuery
  const hasResults = results.tags.length > 0 || results.notes.length > 0

  return (
    <CommandDialog open={open} onOpenChange={setOpen} shouldFilter={false}>
      <CommandInput
        placeholder="Search notes or type # for tags\u2026"
        value={query}
        onValueChange={setQuery}
      />
      <CommandList>
        {/* Loading state: index not ready yet */}
        {!ready && query.trim() && !query.startsWith("#") && (
          <div className="flex items-center justify-center gap-2 py-6 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading search index\u2026
          </div>
        )}

        {/* Searching indicator */}
        {isSearching && ready && (
          <div className="flex items-center justify-center gap-2 py-6 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Searching\u2026
          </div>
        )}

        {/* No results */}
        {!isSearching && ready && query.trim() && !hasResults && (
          <CommandEmpty>No results for &ldquo;{query}&rdquo;</CommandEmpty>
        )}

        {/* Results with fade-in animation */}
        <div className={hasResults ? "animate-in fade-in-0 duration-200" : ""}>
          {results.tags.length > 0 && (
            <CommandGroup heading="Tags">
              {results.tags.map((r) => (
                <CommandItem key={r.slug} value={r.slug} onSelect={() => handleSelect(r.slug)}>
                  <Hash className="mr-2 h-4 w-4 text-muted-foreground" />
                  <span>{r.title}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          )}
          {results.tags.length > 0 && results.notes.length > 0 && <CommandSeparator />}
          {results.notes.length > 0 && (
            <CommandGroup heading="Notes">
              {results.notes.map((r) => (
                <CommandItem key={r.slug} value={r.slug} onSelect={() => handleSelect(r.slug)}>
                  <FileText className="mr-2 h-4 w-4 text-muted-foreground" />
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium">{r.title}</div>
                    <div className="truncate text-xs text-muted-foreground">{r.excerpt}</div>
                  </div>
                </CommandItem>
              ))}
            </CommandGroup>
          )}
        </div>
      </CommandList>
    </CommandDialog>
  )
}
