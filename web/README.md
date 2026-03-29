<div align="center">

# syshin0116.dev

A personal tech blog, portfolio, and AI chatbot — built with [Next.js 15](https://nextjs.org/), [Nuartz](https://github.com/syshin0116/nuartz), and [LangGraph](https://github.com/langchain-ai/langgraph).

[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/import/project?template=https://github.com/syshin0116/syshin0116.dev)
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

- [Bun](https://bun.sh/) 1.0+ (or Node.js 18+)
- API keys for LangGraph and Supabase (optional — site works without them)

### Installation

```bash
git clone https://github.com/syshin0116/syshin0116.dev.git
cd syshin0116.dev
bun install
```

### Environment Variables

Copy `.env.example` or create `.env`:

```env
# LangGraph (blog-rag backend) — optional
LANGGRAPH_API_URL=your_langgraph_api_url
LANGGRAPH_API_KEY=your_api_key

# Supabase (auth) — optional
NEXT_PUBLIC_SUPABASE_URL=your_supabase_url
NEXT_PUBLIC_SUPABASE_ANON_KEY=your_supabase_anon_key
```

### Development

```bash
bun dev       # Start dev server (Turbopack)
bun build     # Production build
bun start     # Start production server
```

Open [http://localhost:3000](http://localhost:3000).

## Project Structure

```
syshin0116.dev/
├── app/
│   ├── page.tsx              # Home (hero + chat + recent posts/projects)
│   ├── blog/                 # Blog pages + API routes
│   ├── projects/             # Project timeline + detail pages
│   ├── about/                # About page
│   └── auth/                 # OAuth callback
├── components/
│   ├── ui/                   # shadcn/ui components
│   ├── blog/                 # Blog components (sidebar, TOC, graph, search)
│   ├── navbar/               # Navigation
│   └── chat-section.tsx      # AI chat interface
├── content/                  # Blog content (Obsidian vault)
├── data/                     # Project & event data
├── lib/                      # API client, utilities, Supabase
└── public/                   # Static assets
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
