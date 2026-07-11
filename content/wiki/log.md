## [2026-04-25 00:00] ingest | 5 sources → 5 new pages, 0 updated, 0 skipped
## [2026-04-26 07:15 UTC] migrate | metadata-only: summary→frontmatter, coverage dropped, tags 2-4→5-10 on 5 pages, index rebuilt to table format
## [2026-04-26 08:30 UTC] ingest | 50 sources → 21 new, 0 updated, 10 skipped (thin/duplicate/no-text content)
## [2026-04-26 09:00 UTC] migrate | 26 pages, no folders introduced; consolidated 3 tags: ai-agent→agent (4 pages), removed knowledge-management→pkm (2 pages), removed tools singleton (1 page)
## [2026-04-27 04:50 UTC] lint | red:0 yellow:2 blue:1 - verify gate OK (26/26 pages pass); yellow are infrastructure files (index.md, log.md); blue: 44 single-use tags, ~12 cluster into clear consolidation groups (ssg, docker, search, deep-learning archs)
## [2026-05-17 00:00 KST] ingest | LLM Wiki research → 1 new page, 2 updated pages, index rebuilt
- Created: content/wiki/llm-wiki.md
- Updated: content/wiki/second-brain-rag.md, content/wiki/블로그-검색-실험.md, content/wiki/index.md
- Research sources: Karpathy gist, Starmorph, MindStudio, Atlan
## [2026-05-17 23:30 KST] ingest | Agentic decision workflow research → 1 new page, 1 source post updated, index rebuilt manually
- Created: content/wiki/agentic-decision-workflow.md
- Updated: content/Tools/2026-05-17-Hermes-Agent-사용-사례와-Claude-Codex-조합.md, content/wiki/index.md
- Research sources: Atlassian HULA, GitHub Agentic Workflows, AI coding agent PR communication study, AWS/Microsoft/ADR guidance, Claude Code GitHub Actions, OpenAI Codex SDK review workflow
## [2026-05-17 23:55 KST] verify | wiki validation trigger added
- Added: scripts/verify-wiki.py, .github/workflows/wiki-verify.yml
- Checks: required wiki frontmatter, wikilink resolution, index coverage, forbidden private/internal terms
- Updated: removed private/internal example references from public blog/wiki content
## [2026-05-18 08:55 KST] update | Search, permissions, Second Brain, and CMDS references added
- Updated: content/Tools/2026-05-17-Hermes-Agent-사용-사례와-Claude-Codex-조합.md
- Updated: content/wiki/agentic-decision-workflow.md, content/wiki/llm-wiki.md, content/wiki/index.md
- Research sources: prodbartist/cmds-vault, cmds-llm-wiki skill, Forte Labs PARA, Azure AI Search document-level ACL, Dataquest metadata/hybrid search
## [2026-05-18 11:24 KST] ingest | Repo intelligence radar → 1 new page, index rebuilt manually
- Created: content/wiki/repo-intelligence-radar.md
- Updated: content/wiki/index.md
- Focus: watchlist에 repo뿐 아니라 changelog/release/docs 변화를 포함하고, GeekNews/GitHub Trending/HN/arXiv/Hugging Face Papers/social signals를 action queue로 압축하는 workflow 시각화
- Added SVG assets: repo-intelligence-radar-architecture.svg, repo-intelligence-radar-scoring.svg, repo-intelligence-radar-digest.svg
- Research sources: GitHub REST API repos/releases/activity, GitHub Trending, GeekNews, Hacker News API/Algolia, arXiv API, Hugging Face Papers
## [2026-05-18 13:05 KST] update | Repo intelligence radar source/feed boundary clarified
- Updated: content/wiki/repo-intelligence-radar.md, content/wiki/repo-intelligence-radar-architecture.svg, content/wiki/index.md
- Clarified: repo radar is a separate user-facing intelligence feed/source, not the knowledge base itself; only selected insights are promoted to knowledge when useful.
## [2026-05-18 13:20 KST] update | Repo intelligence radar split into source post and wiki note
- Created: content/AI/2026-05-18-Tech-Intelligence-Radar.md
- Updated: content/wiki/repo-intelligence-radar.md, content/wiki/index.md
- Clarified: the blog post is the user-facing article; the wiki page remains a linked knowledge note for reusable pattern synthesis.
## [2026-05-18 14:05 KST] update | Technical intelligence framing, SQLite rationale, and image embeds fixed
- Created: content/AI/2026-05-18-Tech-Intelligence-Radar.md
- Removed: content/AI/2026-05-18-Repo-Intelligence-Radar.md
- Added local article assets: content/AI/tech-intelligence-radar-architecture.svg, content/AI/tech-intelligence-radar-scoring.svg, content/AI/tech-intelligence-radar-digest.svg
- Updated: content/wiki/repo-intelligence-radar.md, content/wiki/index.md
- Clarified: this is not repo-only; it tracks papers, news, blogs, social signals, changelogs, and stale knowledge updates. Replaced confusing YAML-first schema with SQLite rationale and schema explanation.
## [2026-05-24 14:30 KST] migrate | Renamed slug repo-intelligence-radar → tech-intelligence-radar
- Renamed: content/wiki/repo-intelligence-radar.md → tech-intelligence-radar.md (+ architecture/scoring/digest SVGs)
- Updated backlinks: content/wiki/index.md (rebuilt), content/AI/2026-05-18-Tech-Intelligence-Radar.md
- Updated frontmatter title/summary and in-body self-name labels (Repo radar → Tech radar) to align with the broadened scope and the source article's "Technical Intelligence Radar" terminology. Claims unchanged.
## [2026-07-12 16:37 UTC] migrate | normalized source provenance, repaired mandatory headings/footnotes, and rebuilt index
