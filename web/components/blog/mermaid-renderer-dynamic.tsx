"use client"

import dynamic from "next/dynamic"

const MermaidRenderer = dynamic(
  () => import("./mermaid-renderer").then((m) => m.MermaidRenderer),
  {
    ssr: false,
    loading: () => <div className="h-[100px] animate-pulse rounded bg-muted" />,
  }
)

export function MermaidRendererDynamic() {
  return <MermaidRenderer />
}
