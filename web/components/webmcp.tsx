"use client";

import Script from "next/script";

const webmcpScript = `
(function() {
  if (!navigator.modelContext) return;

  navigator.modelContext.provideContext({
    tools: [
      {
        name: "browse_projects",
        description: "Browse Syshin's AI/ML projects. Returns a list of projects with descriptions, tech stacks, and links.",
        inputSchema: {
          type: "object",
          properties: {
            category: {
              type: "string",
              description: "Filter by category: 'all', 'ai', 'web', 'data'",
              default: "all"
            }
          }
        },
        execute: async () => {
          window.location.href = "/projects";
          return { navigated: "/projects" };
        }
      },
      {
        name: "read_blog",
        description: "Navigate to the blog to read technical posts about AI, RAG, LangChain, and software development.",
        inputSchema: {
          type: "object",
          properties: {}
        },
        execute: async () => {
          window.location.href = "/blog";
          return { navigated: "/blog" };
        }
      },
      {
        name: "get_portfolio_summary",
        description: "Get a machine-readable summary of this portfolio site, including owner info, projects, and technical expertise.",
        inputSchema: {
          type: "object",
          properties: {}
        },
        execute: async () => {
          const res = await fetch("/llms.txt");
          const text = await res.text();
          return { content: text, contentType: "text/markdown" };
        }
      },
      {
        name: "contact_owner",
        description: "Navigate to the about page to find contact and professional information about Syshin.",
        inputSchema: {
          type: "object",
          properties: {}
        },
        execute: async () => {
          window.location.href = "/about";
          return { navigated: "/about" };
        }
      }
    ]
  });
})();
`;

export function WebMCP() {
  return (
    <Script
      id="webmcp"
      strategy="lazyOnload"
      dangerouslySetInnerHTML={{ __html: webmcpScript }}
    />
  );
}
