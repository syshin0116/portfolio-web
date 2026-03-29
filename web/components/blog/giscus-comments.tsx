"use client"

import Giscus from "@giscus/react"
import { useTheme } from "next-themes"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"

export function GiscusComments() {
  const { resolvedTheme } = useTheme()

  return (
    <div className="mt-12">
      <Separator className="mb-8" />
      <Card className="border-0 shadow-none">
        <CardHeader className="px-0 pt-0">
          <CardTitle className="text-lg font-semibold">Comments</CardTitle>
        </CardHeader>
        <CardContent className="px-0 pb-0">
          <Giscus
            repo="syshin0116/syshin0116.dev"
            repoId="R_kgDOQbT8GQ"
            category="Announcements"
            categoryId="DIC_kwDOQbT8Gc4C3_kp"
            mapping="pathname"
            strict="0"
            reactionsEnabled="1"
            emitMetadata="0"
            inputPosition="bottom"
            theme={resolvedTheme === "dark" ? "dark" : "light"}
            lang="en"
            loading="lazy"
          />
        </CardContent>
      </Card>
    </div>
  )
}
