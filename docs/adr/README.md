# Architecture Decision Records

MADR format. One decision per file, 4-digit sequential number.
**Accepted ADRs are never deleted - only superseded** (write a new ADR that links back).

Write an ADR for significant / hard-to-reverse / non-obvious decisions
(framework, content model, deploy, auth, RAG design). Use a code comment for
local "why this line" notes and an issue for transient task tracking.

New ADR: copy [`template.md`](template.md).

## Index

| # | Title | Status |
|---|---|---|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | accepted |
| [0002](0002-content-immutable-source-curated-wiki.md) | Content model: immutable source posts + curated wiki (LLM-wiki) | accepted |

<!-- Candidates to add: Next.js 15 + Nuartz blog stack, LangGraph RAG chatbot, Vercel deploy, Supabase auth -->
