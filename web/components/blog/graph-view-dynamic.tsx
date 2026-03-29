"use client"

import dynamic from "next/dynamic"

const GraphView = dynamic(
  () => import("./graph-view").then((m) => m.GraphView),
  {
    ssr: false,
    loading: () => <div className="h-[200px] animate-pulse rounded bg-muted" />,
  }
)

export function GraphViewDynamic({ currentSlug }: { currentSlug?: string }) {
  return <GraphView currentSlug={currentSlug} />
}
