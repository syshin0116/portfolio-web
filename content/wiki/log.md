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
