import { NextResponse } from "next/server";
import { createHash } from "crypto";

const skills = [
  {
    name: "portfolio-overview",
    type: "resource",
    description:
      "Overview of Syshin's AI portfolio, projects, technical expertise, and professional experience. Available as llms.txt for LLM consumption.",
    url: "https://syshin0116.vercel.app/llms.txt",
  },
  {
    name: "project-browser",
    type: "resource",
    description:
      "Browse detailed information about AI/ML projects including RAG systems, LangGraph agents, and computer vision applications.",
    url: "https://syshin0116.vercel.app/projects",
  },
  {
    name: "blog-content",
    type: "resource",
    description:
      "Technical blog posts on AI, machine learning, RAG, LangChain, and software development.",
    url: "https://syshin0116.vercel.app/blog",
  },
  {
    name: "api-catalog",
    type: "discovery",
    description: "RFC 9727 API catalog for automated API discovery.",
    url: "https://syshin0116.vercel.app/.well-known/api-catalog",
  },
];

export function GET() {
  const index = {
    $schema:
      "https://raw.githubusercontent.com/cloudflare/agent-skills-discovery-rfc/main/schemas/index.schema.json",
    skills: skills.map((skill) => ({
      ...skill,
      sha256: createHash("sha256")
        .update(JSON.stringify(skill))
        .digest("hex"),
    })),
  };

  return NextResponse.json(index, {
    headers: {
      "Content-Type": "application/json",
    },
  });
}
