import { MetadataRoute } from "next";
import { projectsTimeline } from "@/data/projects";
import sitemapData from "@/.generated/sitemap-data.json"

export default function sitemap(): MetadataRoute.Sitemap {
  const baseUrl = "https://syshin0116.vercel.app";

  const routes: MetadataRoute.Sitemap = [
    {
      url: baseUrl,
      lastModified: new Date(),
      changeFrequency: "daily",
      priority: 1,
    },
    {
      url: `${baseUrl}/blog`,
      lastModified: new Date(),
      changeFrequency: "daily",
      priority: 0.9,
    },
    {
      url: `${baseUrl}/projects`,
      lastModified: new Date(),
      changeFrequency: "weekly",
      priority: 0.9,
    },
    {
      url: `${baseUrl}/about`,
      lastModified: new Date(),
      changeFrequency: "monthly",
      priority: 0.7,
    },
  ];

  const projectRoutes: MetadataRoute.Sitemap = projectsTimeline.map((project) => ({
    url: `${baseUrl}/projects/${project.id}`,
    lastModified: new Date(),
    changeFrequency: "monthly",
    priority: 0.8,
  }));

  const blogRoutes: MetadataRoute.Sitemap = (sitemapData as { slug: string; mtime: string | null; date: string | null }[]).map(
    (entry) => ({
      url: `${baseUrl}/blog/${entry.slug.split("/").map(encodeURIComponent).join("/")}`,
      lastModified: entry.date
        ? new Date(entry.date)
        : entry.mtime
          ? new Date(entry.mtime)
          : new Date(),
      changeFrequency: "monthly" as const,
      priority: 0.7,
    })
  );

  return [...routes, ...projectRoutes, ...blogRoutes];
}
