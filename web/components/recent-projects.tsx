import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { ArrowRight } from "lucide-react";
import { projectsTimeline } from "@/data/projects";

export function RecentProjects() {
  const recent = projectsTimeline.slice(0, 3);

  return (
    <section>
      <div className="flex items-center justify-between mb-5">
        <h2 className="text-xl font-semibold">최근 프로젝트</h2>
        <Link
          href="/projects"
          className="text-sm text-muted-foreground hover:text-foreground flex items-center gap-1 transition-colors"
        >
          전체 보기 <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      </div>
      <ul className="space-y-3">
        {recent.map((project) => (
          <li key={project.id}>
            <Link href={`/projects/${project.id}`} className="block group">
              <div className="rounded-lg border bg-card p-4 hover:border-primary/50 transition-colors">
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-xs text-muted-foreground">{project.period}</span>
                  {!project.isCompleted && (
                    <span className="text-xs font-medium text-emerald-600 dark:text-emerald-400">
                      진행 중
                    </span>
                  )}
                </div>
                <p className="font-medium text-sm leading-snug group-hover:text-primary transition-colors line-clamp-1">
                  {project.title}
                </p>
                <p className="text-xs text-muted-foreground mt-1 line-clamp-2">
                  {project.description}
                </p>
                {project.tags.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-2">
                    {project.tags.slice(0, 3).map((tag) => (
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
      </ul>
    </section>
  );
}
