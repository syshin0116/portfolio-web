import { MetadataRoute } from "next";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      disallow: ['/login', '/api/'],
    },
    sitemap: "https://syshin0116.vercel.app/sitemap.xml",
  };
}
