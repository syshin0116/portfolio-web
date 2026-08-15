<div align="center">

# syshin0116.dev

A personal tech blog, portfolio, and AI chatbot - built with [Next.js 16](https://nextjs.org/), [Nuartz](https://github.com/syshin0116/nuartz), and [LangGraph](https://github.com/langchain-ai/langgraph).

[![Deploy with Vercel](https://img.shields.io/badge/Deploy-Vercel-black?logo=vercel&logoColor=white)](https://vercel.com/import/project?template=https://github.com/syshin0116/syshin0116.dev)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Next.js](https://img.shields.io/badge/Next.js-16-black?logo=next.js)](https://nextjs.org/)
[![Nuartz](https://img.shields.io/badge/Nuartz-0.2.0-purple)](https://www.npmjs.com/package/nuartz)

[Live Demo](https://syshin0116.vercel.app) · [Blog](https://syshin0116.vercel.app/blog) · [Projects](https://syshin0116.vercel.app/projects)

</div>

---

## Features

### AI Chat Assistant
- Public Luna chat without login, plus signed-in Luna, Terra, and Sol selection
- RAG-powered dynamic specialists over the published blog corpus
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
- Google and GitHub OAuth via Auth.js
- Dark / light theme
- SEO: sitemap, robots.txt, Open Graph, JSON-LD
- Vercel Analytics & Speed Insights

## Tech Stack

| Layer | Tech |
|-------|------|
| Framework | Next.js 16 (App Router, Turbopack) |
| UI | React 19, shadcn/ui, Radix UI, Tailwind CSS v4 |
| Content | Nuartz (headless markdown processor) |
| Search | FlexSearch (CJK-aware) |
| AI / RAG | Aegra Agent Protocol v2, LangGraph, Deep Agents |
| Visualization | D3.js, Mermaid, Framer Motion |
| Auth | Auth.js v5 + Postgres (Google / GitHub OAuth) |
| Deployment | Vercel web + Cloud Run agent + Neon Postgres |
| Package Manager | Bun |

## Getting Started

### Prerequisites

- [Bun](https://bun.sh/) 1.3.14 - for `web/`
- [uv](https://github.com/astral-sh/uv) and Python 3.12+ - for `agent/` and `eval/`
- Postgres database (Neon or local) and OpenAI/OAuth provider keys - see
  [web/.env.example](web/.env.example) and [agent/.env.example](agent/.env.example)

### Installation

```bash
git clone https://github.com/syshin0116/syshin0116.dev.git
cd syshin0116.dev

# Frontend
cd web && bun install && cd ..

# Agent (optional, for local LangGraph backend)
uv sync --package syshin0116-dev-agent
```

### Environment Variables

Copy the example files and fill in your values:

```bash
cp web/.env.example web/.env.local
cp agent/.env.example .env
```

- `web/.env.local` - Auth.js/OAuth settings, `AUTH_ALLOWED_EMAILS`, optional `AUTH_ADMIN_EMAILS`, `DATABASE_URL`, agent URL, and `AGENT_AUTH_SECRET`
- root `.env` - the same `AGENT_AUTH_SECRET`, the agent's direct `DATABASE_URL`, Aegra runtime flags, model, and provider keys

Generate one Agent API secret and set the same value in both environments:

```bash
openssl rand -hex 32
```

Production sign-in fails closed when `AUTH_ALLOWED_EMAILS` is empty. Aegra's
`/info`, `/live`, and `/ready` health surfaces remain public. Agent Protocol routes always
require a signed, short-lived token. Production can issue one either from an allowed
Auth.js session or from the bodyless Vercel BotID Basic anonymous bootstrap. Anonymous
subjects are isolated, fixed to Luna, and covered by the public run and daily budgets.

Use a direct Postgres/Neon endpoint for migrations, not a Neon `-pooler` endpoint. For an
approved schema change, run the migration entrypoint separately from the service release:

```bash
uv run --frozen --project agent --package syshin0116-dev-agent \
  --env-file .env python -m agent.migrate
```

Production sets `RUN_MIGRATIONS_ON_STARTUP=false`; the normal image release does not run
the migration job. Aegra 0.9.25 cannot atomically delete thread metadata and LangGraph
checkpoints, so thread deletion is intentionally unsupported. The repository implements
bounded anonymous retention and checkpoint cleanup; deployed execution evidence remains
an operational check and this is not user-facing deletion.

### Development

```bash
# Frontend
cd web && bun dev       # http://localhost:3000

# Agent backend (separate terminal, optional)
uv run --frozen --project agent --package syshin0116-dev-agent \
  aegra serve --config aegra.json
```

## Project Structure

```
syshin0116.dev/          # Monorepo root
├── web/                 # Next.js frontend (Vercel Root Directory)
│   ├── app/             # App Router pages + API routes
│   ├── components/      # UI components (shadcn/ui, blog, chat)
│   ├── lib/             # Auth, Agent API, content, and utility modules
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
| [nuartz](https://github.com/syshin0116/nuartz) | Headless data layer - Obsidian vault → Next.js |
| [blog-rag](https://github.com/syshin0116/blog-rag) | RAG backend - FastAPI + LangGraph |

## Contributing

Contributions are welcome! Feel free to open an issue or submit a pull request.

## License

[MIT](LICENSE)

---

<div align="center">
Built by <a href="https://github.com/syshin0116">syshin0116</a>
</div>
