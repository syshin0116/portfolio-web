"use client"

import { ExternalLink } from "lucide-react"

interface BlogPost {
  number: number
  title: string
  url: string
  date: string
  tags: string[]
  summary: string
}

function parseBlogMetadata(content: string): BlogPost[] {
  const posts: BlogPost[] = []
  const sections = content.split(/\n\n+/)

  for (const section of sections) {
    const lines = section.trim().split("\n")
    if (lines.length < 4) continue

    const titleMatch = lines[0].match(/^(\d+)\.\s+Title:\s+(.+)$/)
    if (!titleMatch) continue

    const number = parseInt(titleMatch[1])
    const title = titleMatch[2]

    let url = ""
    let date = ""
    let tags: string[] = []
    let summary = ""

    for (let i = 1; i < lines.length; i++) {
      const line = lines[i].trim()
      if (line.startsWith("URL:")) {
        url = line.replace("URL:", "").trim()
      } else if (line.startsWith("Date:")) {
        date = line.replace("Date:", "").trim()
      } else if (line.startsWith("Tags:")) {
        const tagString = line.replace("Tags:", "").trim()
        tags = tagString.split(",").map((t) => t.trim())
      } else if (line.startsWith("Summary:")) {
        summary = line.replace("Summary:", "").trim()
      }
    }

    if (title && url) {
      posts.push({ number, title, url, date, tags, summary })
    }
  }

  return posts
}

export function BlogSearchResult({ content }: { content: string }) {
  const posts = parseBlogMetadata(content)

  if (posts.length === 0) {
    return (
      <div className="rounded-lg border p-4">
        <pre className="whitespace-pre-wrap text-sm">{content}</pre>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {posts.map((post) => (
        <div
          key={post.number}
          className="group rounded-lg border bg-card p-4 transition-colors hover:bg-accent"
        >
          <div className="flex items-start justify-between gap-2">
            <div className="flex-1 space-y-2">
              <div className="flex items-start gap-2">
                <span className="text-muted-foreground flex-shrink-0 font-mono text-sm">
                  {post.number}.
                </span>
                <div className="flex-1">
                  <a
                    href={post.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="font-medium text-primary hover:underline"
                  >
                    {post.title}
                  </a>
                </div>
              </div>

              {post.summary && (
                <p className="text-muted-foreground text-sm leading-relaxed">
                  {post.summary}
                </p>
              )}

              <div className="flex flex-wrap items-center gap-2 text-xs">
                {post.date && (
                  <span className="text-muted-foreground">{post.date}</span>
                )}
                {post.tags.length > 0 && (
                  <>
                    {post.date && (
                      <span className="text-muted-foreground">•</span>
                    )}
                    <div className="flex flex-wrap gap-1">
                      {post.tags.map((tag, idx) => (
                        <span
                          key={idx}
                          className="bg-primary/10 text-primary rounded-full px-2 py-0.5"
                        >
                          {tag}
                        </span>
                      ))}
                    </div>
                  </>
                )}
              </div>
            </div>

            <a
              href={post.url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-muted-foreground hover:text-primary flex-shrink-0 transition-colors"
            >
              <ExternalLink className="h-4 w-4" />
            </a>
          </div>
        </div>
      ))}
    </div>
  )
}
