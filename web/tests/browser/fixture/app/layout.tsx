import "../../../../app/globals.css"
import type { Metadata } from "next"

export const metadata: Metadata = {
  title: "AI 검색 실험실 브라우저 검증",
}

export default function BrowserFixtureLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  )
}
