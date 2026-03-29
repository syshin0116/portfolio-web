import { getAllMarkdownFiles } from "nuartz";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Calendar, ArrowRight } from "lucide-react";
import { CONTENT_DIR } from "@/lib/content";

function formatDate(date: string | Date | undefined): string {
  if (!date) return "";
  const d = typeof date === "string" ? new Date(date) : date;
  return d.toLocaleDateString("ko-KR", { year: "numeric", month: "short", day: "numeric" });
}

export async function RecentPosts() {
  let posts: Awaited<ReturnType<typeof getAllMarkdownFiles>> = [];
  try {
    const all = await getAllMarkdownFiles(CONTENT_DIR);
    posts = all
      .filter((f) => !f.frontmatter.draft)
      .sort((a, b) => {
        const da = a.frontmatter.date ? new Date(a.frontmatter.date).getTime() : 0;
        const db = b.frontmatter.date ? new Date(b.frontmatter.date).getTime() : 0;
        return db - da;
      })
      .slice(0, 3);
  } catch {
    posts = [];
  }

  return (
    <section>
      <div className="flex items-center justify-between mb-5">
        <h2 className="text-xl font-semibold">최근 블로그 포스트</h2>
        <Link
          href="/blog"
          className="text-sm text-muted-foreground hover:text-foreground flex items-center gap-1 transition-colors"
        >
          전체 보기 <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      </div>
      <ul className="space-y-3">
        {posts.map((post) => (
          <li key={post.slug}>
            <Link href={`/blog/${post.slug}`} className="block group">
              <div className="rounded-lg border bg-card p-4 hover:border-primary/50 transition-colors">
                <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-1.5">
                  <Calendar className="h-3 w-3" />
                  {formatDate(post.frontmatter.date)}
                </div>
                <p className="font-medium text-sm leading-snug group-hover:text-primary transition-colors line-clamp-2">
                  {post.frontmatter.title ?? post.slug.split("/").pop()}
                </p>
                {post.frontmatter.tags && post.frontmatter.tags.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-2">
                    {post.frontmatter.tags.slice(0, 3).map((tag) => (
                      <Badge key={tag} variant="secondary" className="text-xs px-1.5 py-0">
                        {tag}
                      </Badge>
                    ))}
                  </div>
                )}
              </div>
            </Link>
          </li>
        ))}
        {posts.length === 0 && (
          <li className="text-sm text-muted-foreground">게시물이 없습니다.</li>
        )}
      </ul>
    </section>
  );
}
