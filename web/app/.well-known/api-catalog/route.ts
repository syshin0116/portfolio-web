import { NextResponse } from "next/server";

export function GET() {
  const catalog = {
    linkset: [
      {
        anchor: "https://syshin0116.vercel.app/",
        "service-doc": [
          {
            href: "https://syshin0116.vercel.app/llms.txt",
            type: "text/plain",
          },
        ],
      },
      {
        anchor: "https://syshin0116.vercel.app/blog/api/content/",
        "service-desc": [
          {
            href: "https://syshin0116.vercel.app/blog/api/content/",
            type: "application/json",
          },
        ],
        "service-doc": [
          {
            href: "https://syshin0116.vercel.app/llms.txt",
            type: "text/plain",
          },
        ],
      },
    ],
  };

  return NextResponse.json(catalog, {
    headers: {
      "Content-Type": "application/linkset+json",
    },
  });
}
