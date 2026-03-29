"use client";

import { cn } from "@/lib/utils";
import type { TocEntry } from "nuartz";
import { useEffect, useState } from "react";

interface TableOfContentsProps {
  toc: TocEntry[];
}

function TocItem({ entry, activeId }: { entry: TocEntry; activeId: string }) {
  return (
    <li>
      <a
        href={`#${entry.id}`}
        className={cn(
          "block text-sm py-0.5 transition-colors hover:text-foreground",
          entry.depth === 2 && "pl-0",
          entry.depth === 3 && "pl-3",
          entry.depth >= 4 && "pl-6",
          activeId === entry.id
            ? "text-foreground font-medium"
            : "text-muted-foreground"
        )}
      >
        {entry.text}
      </a>
      {entry.children.length > 0 && (
        <ul className="space-y-1 mt-1">
          {entry.children.map((child) => (
            <TocItem key={child.id} entry={child} activeId={activeId} />
          ))}
        </ul>
      )}
    </li>
  );
}

export function TableOfContents({ toc }: TableOfContentsProps) {
  const [activeId, setActiveId] = useState("");

  useEffect(() => {
    const headingIds = toc.flatMap(function flatten(entry): string[] {
      return [entry.id, ...entry.children.flatMap(flatten)];
    });

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries.find((e) => e.isIntersecting);
        if (visible) setActiveId(visible.target.id);
      },
      { rootMargin: "0px 0px -60% 0px" }
    );

    headingIds.forEach((id) => {
      const el = document.getElementById(id);
      if (el) observer.observe(el);
    });

    return () => observer.disconnect();
  }, [toc]);

  return (
    <nav className="border rounded-lg p-4 bg-card">
      <p className="text-sm font-semibold mb-3">목차</p>
      <ul className="space-y-1">
        {toc.map((entry) => (
          <TocItem key={entry.id} entry={entry} activeId={activeId} />
        ))}
      </ul>
    </nav>
  );
}
