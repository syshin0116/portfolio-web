<div align="center">

# syshin0116.dev

A personal tech blog, portfolio, and AI chatbot — built with [Next.js 15](https://nextjs.org/), [Nuartz](https://github.com/syshin0116/nuartz), and [LangGraph](https://github.com/langchain-ai/langgraph).

[![Deploy with Vercel](https://img.shields.io/badge/Deploy-Vercel-black?logo=vercel&logoColor=white)](https://vercel.com/import/project?template=https://github.com/syshin0116/syshin0116.dev)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Next.js](https://img.shields.io/badge/Next.js-15-black?logo=next.js)](https://nextjs.org/)
[![Nuartz](https://img.shields.io/badge/Nuartz-0.1.7-purple)](https://www.npmjs.com/package/nuartz)

[Live Demo](https://syshin0116.vercel.app) · [Blog](https://syshin0116.vercel.app/blog) · [Projects](https://syshin0116.vercel.app/projects)

</div>

---

## Features

### AI Chat Assistant
- RAG-powered chatbot via LangGraph SDK
- Multiple search modes: Auto (single/multi agent) and Manual (metadata, filesystem, vector, graph)
- Real-time streaming with tool call visualization and source attribution

### Blog
- Obsidian-compatible markdown powered by [Nuartz](https://github.com/syshin0116/nuartz)
- Knowledge graph visualization (D3.js)
- Full-text search with command palette (`Cmd+K`)
- Backlinks, table of contents, link hover previews
- Mermaid diagrams, LaTeX math (KaTeX), syntax highlighting (Shiki)
- Reader mode, reading time, copy code buttons

### Projects
- Timeline view with Work / Personal split layout
- Detailed project pages with tech stack, achievements, and architecture

### Other
- Google OAuth via Supabase
- Dark / light theme
- SEO: sitemap, robots.txt, Open Graph, JSON-LD
- Vercel Analytics & Speed Insights

## Tech Stack

| Layer | Tech |
|-------|------|
| Framework | Next.js 15 (App Router, Turbopack) |
| UI | React 19, shadcn/ui, Radix UI, Tailwind CSS v4 |
| Content | Nuartz (headless markdown processor) |
| Search | FlexSearch (CJK-aware) |
| AI / RAG | LangGraph SDK, LangChain Core |
| Visualization | D3.js, Mermaid, Framer Motion |
| Auth | Supabase (Google OAuth) |
| Deployment | Vercel |
| Package Manager | Bun |

## Getting Started

### Prerequisites

- [Bun](https://bun.sh/) 1.0+ (or Node.js 18+) — for `web/`
- [uv](https://github.com/astral-sh/uv) — for `agent/` (Python)
- Postgres database (Neon, Supabase, or local) and API keys (Anthropic/OpenAI, OAuth providers) — see `.env.example`

### Installation

```bash
git clone https://github.com/syshin0116/syshin0116.dev.git
cd syshin0116.dev

# Frontend
cd web && bun install && cd ..

# Agent (optional, for local LangGraph backend)
cd agent && uv sync && cd ..
```

### Environment Variables

Copy the example files and fill in your values:

```bash
cp web/.env.example web/.env.local
cp agent/.env.example agent/.env
```

- `web/.env.local` — Auth.js secret, OAuth credentials, `DATABASE_URL`, agent backend URL
- `agent/.env` — `DATABASE_URL`, model selection, Anthropic/OpenAI keys, optional LangSmith

### Development

```bash
# Frontend
cd web && bun dev       # http://localhost:3000

# Agent backend (separate terminal, optional)
cd agent && uv run langgraph dev
```

## Project Structure

```
syshin0116.dev/          # Monorepo root
├── web/                 # Next.js frontend (Vercel Root Directory)
│   ├── app/             # App Router pages + API routes
│   ├── components/      # UI components (shadcn/ui, blog, chat)
│   ├── lib/             # API client, utilities, Supabase
│   ├── public/          # Static assets
│   └── data/            # Project & event data
├── content/             # Blog content (Obsidian vault, shared)
│   ├── AI/              # AI/ML posts
│   ├── Dev/             # Development posts
│   ├── Projects/        # Project write-ups
│   └── ...
└── agent/               # LangGraph agent backend
```

## Related Repositories

| Repo | Description |
|------|-------------|
| [nuartz](https://github.com/syshin0116/nuartz) | Headless data layer — Obsidian vault → Next.js |
| [blog-rag](https://github.com/syshin0116/blog-rag) | RAG backend — FastAPI + LangGraph |

## Contributing

Contributions are welcome! Feel free to open an issue or submit a pull request.

## License

[MIT](LICENSE)

---

<div align="center">
Built by <a href="https://github.com/syshin0116">syshin0116</a>
</div>
