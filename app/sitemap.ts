import { MetadataRoute } from "next";
import { projectsTimeline } from "@/data/projects";
import { getAllMarkdownFiles } from "nuartz";
import { CONTENT_DIR } from "@/lib/content";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
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

  let blogRoutes: MetadataRoute.Sitemap = [];
  try {
    const files = await getAllMarkdownFiles(CONTENT_DIR);
    blogRoutes = files
      .filter((f) => !f.frontmatter.draft && f.frontmatter.published !== false)
      .map((file) => ({
        url: `${baseUrl}/blog/${file.slug.split("/").map(encodeURIComponent).join("/")}`,
        lastModified: file.frontmatter.date
          ? new Date(file.frontmatter.date)
          : new Date(),
        changeFrequency: "monthly" as const,
        priority: 0.7,
      }));
  } catch {
    // ignore if content dir unavailable
  }

  return [...routes, ...projectRoutes, ...blogRoutes];
}
