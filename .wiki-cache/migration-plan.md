# Migration plan — 2026-04-26 UTC

## Scope

5 wiki pages, all at root, created during the first ingest run (2026-04-25).
All pages have three shared defects from the earlier convention:
- `coverage:` field (now derived in index.md, not stored)
- `## Summary` body section (now lives in frontmatter `summary:`)
- Thin tags (2–4 per page; target 5–10)

## 1. Folder restructuring

**Decision: no folders introduced.**

Current page counts by type:
| Type | Count | Threshold |
|------|-------|-----------|
| pattern | 2 | need 5 |
| tool | 2 | need 5 |
| reference | 1 | need 5 |

No type clears the 5-page minimum. All pages stay at root. This is expected at this scale;
folder introduction will become relevant after 2–3 more ingest batches.

## 2. Type vocabulary

Types in use: `pattern`, `tool`, `reference` — no synonyms, no consolidation needed.

## 3. Tag enrichment

Source-post frontmatter vocabulary pulled through and mapped to wiki tag conventions
(lowercase, hyphenated, domain/technique/concept dimensions):

| Slug | Old tags | New tags | Source terms added |
|------|----------|----------|--------------------|
| cli-ux-design | cli, backend | cli, rust, backend, ai-agent, ux, api-design, unix, pattern | Rust, AI-Agent, UX, API-Design → unix (UNIX convention claim in body) |
| clidex | cli, rust, ai | cli, rust, ai, ai-agent, bm25, search, fuzzy-search, edit-distance, testing | AI-Agent, Search, BM25, Testing → fuzzy-search, edit-distance from body |
| llm-text-to-sql | text-to-sql, llm, prompt-engineering, ai | text-to-sql, llm, ai, agent, postgresql, prompt-engineering, evaluation, security | agent, postgresql, evaluation from source tags; security from body content |
| misen | python, ai, llm | python, ai, llm, pipeline, workflow, open-source, library, agent, operator | Pipeline, Workflow, Open Source from source tags; library, operator from body |
| 블로그-검색-실험 | rag, ai, embeddings | rag, ai, embeddings, bm25, search, vector-search, hybrid-search, korean, experiment, evaluation | RAG, BM25, Vector-Database→vector-search, Hybrid-Search, Experiment from source; korean from body |

## 4. Summary field migration

Every page has a `## Summary` body section that pre-dates the frontmatter `summary:` convention.
Action: extract verbatim, place in frontmatter `summary:`, remove body section.
Minor normalization: strip inline `**bold**` from summaries (frontmatter is plain text).

| Slug | Summary (abbreviated) |
|------|-----------------------|
| cli-ux-design | "CLI 도구의 사용성은 기능 추가가 아니라 출력 계약과 동작 규칙의 설계 문제다…" |
| clidex | "Clidex는 AI 에이전트와 인간 모두를 위한 CLI 도구 발견(discovery) 도구로…" |
| llm-text-to-sql | "LLM 기반 Text-to-SQL 시스템을 프로덕션에서 안정적으로 운영하려면 프롬프트 튜닝보다 DB 스키마 품질이 결정적 요소다…" |
| misen | "misen(mise en place)은 AI 워크플로우의 반복 작업을 Block(dict→dict) 단일 인터페이스로 정의하고…" |
| 블로그-검색-실험 | "280개 한국어+영어 혼용 블로그 포스트를 테스트베드로 6가지 검색 방법의 성능을 비교하는 실험 시리즈다…" |

## 5. Coverage field removal

All 5 pages carry `coverage: low/medium` — deprecated per current conventions (derived in index.md).
Remove from all pages.

## 6. Backlinks

No slug renames, so no backlink fixes required. All `[[wikilinks]]` resolve by basename.

## 7. Index rebuild

Rebuild `content/wiki/index.md` to the standard table format from conventions.md.
The type-grouped format from the first ingest is replaced with the flat `| Page | Summary | Type | Tags | Sources | Updated |` table.
