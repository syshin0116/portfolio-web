import notesList from "@/.generated/notes-list.json"

export const dynamic = "force-static"

const BASE_URL = "https://syshin0116.vercel.app"

function escapeXml(str: string): string {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;")
}

export async function GET() {
  const posts = (notesList as any[])
    .filter((f) => !f.draft)
    .slice(0, 50)

  const lastBuildDate = posts[0]?.dateRaw
    ? new Date(posts[0].dateRaw).toUTCString()
    : new Date().toUTCString()

  const items = posts
    .map((post) => {
      const title = escapeXml(String(post.title))
      const description = escapeXml(String(post.description ?? ""))
      const url = `${BASE_URL}/blog/${post.slug.split("/").map(encodeURIComponent).join("/")}`
      const pubDate = post.dateRaw
        ? new Date(post.dateRaw).toUTCString()
        : ""
      const categories = (post.tags as string[])
        .map((tag) => `<category>${escapeXml(tag)}</category>`)
        .join("")

      return `    <item>
      <title>${title}</title>
      <link>${url}</link>
      <guid isPermaLink="true">${url}</guid>
      <description>${description}</description>
      ${pubDate ? `<pubDate>${pubDate}</pubDate>` : ""}
      ${categories}
    </item>`
    })
    .join("\n")

  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>Syshin0116 Dev Blog</title>
    <link>${BASE_URL}/blog</link>
    <description>AI Research Engineer portfolio &amp; tech blog</description>
    <language>ko</language>
    <lastBuildDate>${lastBuildDate}</lastBuildDate>
    <atom:link href="${BASE_URL}/feed.xml" rel="self" type="application/rss+xml"/>
${items}
  </channel>
</rss>`

  return new Response(xml, {
    headers: {
      "Content-Type": "application/xml; charset=utf-8",
      "Cache-Control": "public, max-age=3600, s-maxage=3600",
    },
  })
}
