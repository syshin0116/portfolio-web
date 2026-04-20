import { NextResponse } from "next/server";

export function GET() {
  const serverCard = {
    $schema: "https://raw.githubusercontent.com/modelcontextprotocol/modelcontextprotocol/main/schema/server-card.json",
    serverInfo: {
      name: "syshin0116-portfolio",
      version: "1.0.0",
      description:
        "AI Research Engineer portfolio & blog by Syshin. Browse projects, read blog posts, and learn about technical expertise in AI/ML, RAG, and LangGraph.",
    },
    capabilities: {
      resources: true,
      tools: false,
      prompts: false,
    },
    links: {
      homepage: "https://syshin0116.vercel.app",
      documentation: "https://syshin0116.vercel.app/llms.txt",
      source: "https://github.com/syshin0116/syshin0116.dev",
    },
  };

  return NextResponse.json(serverCard, {
    headers: {
      "Content-Type": "application/json",
    },
  });
}
