import Link from "next/link"
import { ChevronRight, Home } from "lucide-react"

interface BreadcrumbProps {
  slug: string[]
}

export function Breadcrumb({ slug }: BreadcrumbProps) {
  const crumbs = slug.map((part, i) => ({
    label: part.replace(/-/g, " "),
    href: "/blog/" + slug.slice(0, i + 1).join("/"),
    isLast: i === slug.length - 1,
  }))

  return (
    <nav aria-label="현재 위치" className="flex items-center gap-1 text-sm text-muted-foreground">
      <Link
        href="/blog"
        aria-label="블로그 홈"
        className="hover:text-foreground transition-colors"
      >
        <Home className="h-3.5 w-3.5" aria-hidden="true" />
      </Link>
      {crumbs.map((crumb) => (
        <span key={crumb.href} className="flex items-center gap-1">
          <ChevronRight className="h-3.5 w-3.5 opacity-50" aria-hidden="true" />
          {crumb.isLast ? (
            <span className="text-foreground">{crumb.label}</span>
          ) : (
            <Link href={crumb.href} className="hover:text-foreground transition-colors capitalize">
              {crumb.label}
            </Link>
          )}
        </span>
      ))}
    </nav>
  )
}
