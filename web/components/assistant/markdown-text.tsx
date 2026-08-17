"use client"

// Streaming cursor shown at the tail of the in-flight text part.
import "@assistant-ui/react-markdown/styles/dot.css"

import {
  MarkdownTextPrimitive,
  unstable_memoizeMarkdownComponents as memoizeMarkdownComponents,
  useIsMarkdownCodeBlock,
  type CodeHeaderProps,
} from "@assistant-ui/react-markdown"
import { Check, Copy } from "lucide-react"
import { memo, useEffect, useRef, useState, type FC } from "react"
import remarkBreaks from "remark-breaks"
import remarkGfm from "remark-gfm"

import { cn } from "@/lib/utils"

const MARKDOWN_PLUGINS = [remarkGfm, remarkBreaks]
const COPIED_DURATION_MS = 2_000

const CodeHeader: FC<CodeHeaderProps> = ({ language, code }) => {
  const [copied, setCopied] = useState(false)
  const resetTimer = useRef<ReturnType<typeof setTimeout>>(undefined)
  useEffect(() => () => clearTimeout(resetTimer.current), [])

  const copy = () => {
    if (!code || copied || !navigator.clipboard) return
    void navigator.clipboard.writeText(code).then(
      () => {
        setCopied(true)
        resetTimer.current = setTimeout(
          () => setCopied(false),
          COPIED_DURATION_MS
        )
      },
      () => {}
    )
  }

  return (
    <div className="mt-3 flex items-center justify-between rounded-t-xl border border-b-0 border-border/60 bg-muted/60 px-3.5 py-1.5 text-xs">
      <span className="font-mono lowercase text-muted-foreground">
        {language ?? "code"}
      </span>
      <button
        type="button"
        onClick={copy}
        aria-label="코드 복사"
        className="flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors motion-reduce:transition-none hover:bg-background hover:text-foreground"
      >
        {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
      </button>
    </div>
  )
}

const markdownComponents = memoizeMarkdownComponents({
  h1: ({ className, ...props }) => (
    <h1
      className={cn(
        "mb-2 mt-5 text-xl font-semibold tracking-tight first:mt-0 last:mb-0",
        className
      )}
      {...props}
    />
  ),
  h2: ({ className, ...props }) => (
    <h2
      className={cn(
        "mb-2 mt-5 text-lg font-semibold tracking-tight first:mt-0 last:mb-0",
        className
      )}
      {...props}
    />
  ),
  h3: ({ className, ...props }) => (
    <h3
      className={cn(
        "mb-1.5 mt-4 text-base font-semibold first:mt-0 last:mb-0",
        className
      )}
      {...props}
    />
  ),
  h4: ({ className, ...props }) => (
    <h4
      className={cn(
        "mb-1 mt-3.5 text-base font-medium first:mt-0 last:mb-0",
        className
      )}
      {...props}
    />
  ),
  h5: ({ className, ...props }) => (
    <h5
      className={cn(
        "mb-1 mt-3 text-sm font-semibold first:mt-0 last:mb-0",
        className
      )}
      {...props}
    />
  ),
  h6: ({ className, ...props }) => (
    <h6
      className={cn(
        "mb-1 mt-3 text-sm font-medium first:mt-0 last:mb-0",
        className
      )}
      {...props}
    />
  ),
  p: ({ className, ...props }) => (
    <p className={cn("my-3 first:mt-0 last:mb-0", className)} {...props} />
  ),
  // Answers cite blog posts and external references, so links leave the chat.
  a: ({ className, ...props }) => (
    <a
      target="_blank"
      rel="noreferrer"
      className={cn(
        "font-medium underline underline-offset-4",
        className
      )}
      {...props}
    />
  ),
  blockquote: ({ className, ...props }) => (
    <blockquote
      className={cn(
        "my-3 border-s-2 border-muted-foreground/30 ps-4 text-muted-foreground",
        className
      )}
      {...props}
    />
  ),
  ul: ({ className, ...props }) => (
    <ul
      className={cn(
        "my-3 ms-5 list-disc marker:text-muted-foreground [&>li]:mt-1",
        className
      )}
      {...props}
    />
  ),
  ol: ({ className, ...props }) => (
    <ol
      className={cn(
        "my-3 ms-5 list-decimal marker:text-muted-foreground [&>li]:mt-1",
        className
      )}
      {...props}
    />
  ),
  li: ({ className, ...props }) => (
    <li className={cn("leading-7", className)} {...props} />
  ),
  hr: ({ className, ...props }) => (
    <hr className={cn("my-4 border-border/60", className)} {...props} />
  ),
  // border-separate + border-spacing-0 lets the rounded corners survive on
  // th/td, which collapsed borders would clip.
  table: ({ className, ...props }) => (
    <table
      className={cn(
        "my-3 w-full border-separate border-spacing-0 text-sm",
        className
      )}
      {...props}
    />
  ),
  th: ({ className, ...props }) => (
    <th
      className={cn(
        "bg-muted px-3 py-1.5 text-start font-medium first:rounded-ss-lg last:rounded-se-lg",
        className
      )}
      {...props}
    />
  ),
  td: ({ className, ...props }) => (
    <td
      className={cn(
        "border-b border-s border-border/60 px-3 py-1.5 text-start last:border-e",
        className
      )}
      {...props}
    />
  ),
  tr: ({ className, ...props }) => (
    <tr
      className={cn(
        "[&:last-child>td:first-child]:rounded-es-lg [&:last-child>td:last-child]:rounded-ee-lg",
        className
      )}
      {...props}
    />
  ),
  strong: ({ className, ...props }) => (
    <strong className={cn("font-semibold", className)} {...props} />
  ),
  pre: ({ className, ...props }) => (
    <pre
      className={cn(
        "overflow-x-auto rounded-b-xl rounded-t-none border border-t-0 border-border/60 bg-muted/40 p-3.5 text-[13px] leading-relaxed",
        className
      )}
      {...props}
    />
  ),
  code: function Code({ className, ...props }) {
    const isBlock = useIsMarkdownCodeBlock()
    return (
      <code
        className={cn(
          !isBlock &&
            "rounded bg-muted px-1.5 py-0.5 font-mono text-[0.9em]",
          className
        )}
        {...props}
      />
    )
  },
  CodeHeader,
})

export const MarkdownText = memo(function MarkdownText() {
  return (
    <MarkdownTextPrimitive
      remarkPlugins={MARKDOWN_PLUGINS}
      components={markdownComponents}
      defer
    />
  )
})
