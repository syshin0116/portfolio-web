import { Navbar } from "@/components/navbar";
import Footer from "@/components/footer";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Button } from "@/components/ui/button";
import { GithubIcon, ExternalLink } from "lucide-react";
import Link from "next/link";
import { Metadata } from "next";

export const metadata: Metadata = {
  title: "About | Syshin's Portfolio",
  description: "Learn about Syshin and their work",
  openGraph: {
    title: "About Syshin",
    description: "Learn about Syshin and their work",
    url: "https://syshin0116.vercel.app/about",
    type: "profile",
  },
};

const techStack: { category: string; items: string[] }[] = [
  {
    category: "AI / ML",
    items: ["LangChain", "LangGraph", "OpenAI API", "RAG", "Vector DB", "Prompt Engineering"],
  },
  {
    category: "Backend",
    items: ["Python", "FastAPI", "Node.js", "PostgreSQL", "Redis", "Supabase"],
  },
  {
    category: "Frontend",
    items: ["Next.js", "React", "TypeScript", "Tailwind CSS", "shadcn/ui"],
  },
  {
    category: "Infrastructure",
    items: ["Docker", "AWS", "Azure", "GitHub Actions", "Vercel"],
  },
];

export default function AboutPage() {
  return (
    <>
      <Navbar />
      <main className="min-h-screen bg-background">
        <div className="container mx-auto px-4 md:px-6 py-14 max-w-3xl">
          <section className="mb-12">
            <h1 className="text-4xl font-bold tracking-tight mb-2">AI Engineer</h1>
            <p className="text-xl text-muted-foreground mb-6">
              BrainCrew
            </p>

            <div className="flex gap-3 mt-6">
              <Button asChild variant="outline" size="sm">
                <Link
                  href="https://github.com/syshin0116"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <GithubIcon className="h-4 w-4 mr-2" />
                  GitHub
                </Link>
              </Button>
              <Button asChild variant="outline" size="sm">
                <Link href="/blog">
                  <ExternalLink className="h-4 w-4 mr-2" />
                  Blog
                </Link>
              </Button>
            </div>
          </section>

          <Separator className="my-10" />

          <section className="mb-12">
            <h2 className="text-2xl font-semibold mb-6">기술 스택</h2>
            <div className="space-y-5">
              {techStack.map(({ category, items }) => (
                <div key={category}>
                  <h3 className="text-sm font-medium text-muted-foreground uppercase tracking-wide mb-2">
                    {category}
                  </h3>
                  <div className="flex flex-wrap gap-2">
                    {items.map((item) => (
                      <Badge key={item} variant="secondary">
                        {item}
                      </Badge>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </section>

          <Separator className="my-10" />

          <section>
            <h2 className="text-2xl font-semibold mb-6">경력</h2>
            <div className="space-y-4">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-1">
                <div>
                  <p className="font-medium">AI Engineer</p>
                  <p className="text-sm text-muted-foreground">BrainCrew</p>
                </div>
                <span className="text-sm text-muted-foreground">2026.02 ~</span>
              </div>
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-1">
                <div>
                  <p className="font-medium">AI Engineer</p>
                  <p className="text-sm text-muted-foreground">LabQ</p>
                </div>
                <span className="text-sm text-muted-foreground">2024.03 ~ 2026.02</span>
              </div>
            </div>
          </section>
        </div>
      </main>
      <Footer />
    </>
  );
}
