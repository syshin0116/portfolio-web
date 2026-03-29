"use client";

import Link from "next/link";
import { cn } from "@/lib/utils";

interface BlogCategoryFilterProps {
  categories: string[];
  selected: string;
}

export function BlogCategoryFilter({ categories, selected }: BlogCategoryFilterProps) {
  return (
    <div className="flex flex-wrap gap-2">
      {categories.map((cat) => (
        <Link
          key={cat}
          href={cat === "All" ? "/blog" : `/blog?category=${cat}`}
          className={cn(
            "px-4 py-1.5 rounded-full text-sm font-medium border transition-colors",
            selected === cat
              ? "bg-primary text-primary-foreground border-primary"
              : "bg-background text-muted-foreground border-border hover:border-primary/50 hover:text-foreground"
          )}
        >
          {cat}
        </Link>
      ))}
    </div>
  );
}
