---
title: "LLM Wiki 패턴"
type: pattern
tags:
  - llm
  - ai
  - knowledge-base
  - pkm
  - markdown
  - agent
  - rag
  - obsidian
  - automation
summary: "LLM Wiki는 원문을 매번 검색해 답하는 RAG 대신, LLM이 raw 소스를 읽어 지속적으로 갱신되는 Markdown 위키를 컴파일·유지하는 패턴이다. 이 블로그는 이미 원본 글(content/AI, Tools 등)과 정제 레이어(content/wiki)를 분리하고 있으므로, raw→wiki ingest, index/log, lint, wikilink 검증, 자동 PR 루틴을 붙이면 개인 블로그를 누적 지식베이스로 발전시킬 수 있다."
sources:
  - https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
  - https://blog.starmorph.com/blog/karpathy-llm-wiki-knowledge-base-guide
  - https://www.mindstudio.ai/blog/karpathy-llm-wiki-pattern-knowledge-base-without-rag
  - https://atlan.com/know/llm-wiki-vs-rag-knowledge-base/
  - private repository example A
  - private repository example B
  - private repository example
created: 2026-05-17
updated: 2026-05-17
author: wiki-curator
draft: false
---

## Key Claims

- LLM Wiki의 핵심은 원문 chunk를 매 질문마다 다시 검색·종합하는 대신, LLM이 원문을 읽고 **지속적으로 누적되는 Markdown 위키**를 유지한다는 점이다. Karpathy는 이를 "Obsidian은 IDE, LLM은 프로그래머, 위키는 코드베이스"에 비유한다.[^1]
- 표준 구조는 세 층으로 나뉜다. `raw/`는 사람이 넣는 불변 원천 자료, `wiki/`는 LLM이 작성·갱신하는 정제 지식, `AGENTS.md`/`CLAUDE.md`는 스키마와 운영 규칙이다.[^1][^2]
- LLM Wiki는 RAG의 대체재라기보다 **bounded corpus**에 대한 compile-time synthesis다. 문서가 수만~수십만 토큰 규모이고 curated 상태라면 Markdown을 직접 읽는 방식이 단순하고 투명하지만, 수백만 문서·권한 제어·고빈도 변경이 있는 엔터프라이즈 지식에는 RAG나 데이터 카탈로그 계층이 여전히 필요하다.[^3][^4]
- 운영의 핵심 작업은 `ingest`, `query`, `lint`다. 새 소스를 읽어 관련 페이지를 만들거나 갱신하고, 질의 결과 중 재사용 가치가 큰 답을 다시 위키에 파일링하며, 주기적으로 broken link·orphan·stale claim·contradiction을 점검한다.[^1][^2]
- 한 팀 위키 구현은 이 패턴을 팀 단위로 확장한다. 사람은 Obsidian 또는 `/bc-wiki-add`로 `content/raw/`에 메모하고, GitHub Action/Anthropic Routine이 raw 변경을 감지해 `content/wiki/` PR을 만든다. pre-commit hook과 path-guard CI로 사람이 `wiki/`를 직접 수정하지 못하게 막아 raw→wiki 단방향 흐름을 강제한다.[^5]
- 팀 위키 사례에서 배운 중요한 구현 디테일은 운영 상태를 공개 콘텐츠와 분리하는 것이다. `content/`는 웹 배포 경계이고, `.wiki-state/log.md`, `.wiki-state/review.md`, `.wiki-state/hashes`는 공개하지 않는다. 이 분리는 로그·검토 항목·hash ledger가 사이트에 노출되는 문제를 구조적으로 방지한다.[^5]
- `deep-agent-builder-claw-wiki`는 LLM Wiki를 제품/PM 운영 위키로 쓴 예시다. 5개 레포의 아키텍처·기능·사용자 시나리오·리서치·제안을 한곳에 모으고, cron 기반 Claw 에이전트가 daily PM sync와 research radar를 수행한다.[^6]
- `consulting-wiki`는 컨설팅 지식베이스형 적용 예시다. `PROJECT.md`를 항상 먼저 읽고, `wiki-search`로 근거를 찾은 뒤, 답변 후 새 인사이트를 `wiki-write`로 환원하는 PROJECT-first → Wiki-first 루프를 강제한다.[^7]

## LLM Wiki vs RAG

| 관점 | LLM Wiki | RAG |
|------|----------|-----|
| 지식 조립 시점 | 소스 ingest 때 미리 정제·연결 | 질문 시점에 chunk 검색 |
| 저장 형태 | Markdown 파일 + wikilink + index | 원문 chunk + embedding + vector DB |
| 강점 | 작고 curated한 코퍼스, 투명한 provenance, 쉬운 Git diff/review | 대규모·동적 문서, 권한 제어, 다중 시스템 검색 |
| 실패 모드 | 오래된 페이지, 잘못된 수동/LLM 편집, index/log 부실 | chunking 손실, 검색 누락, embedding mismatch, opaque retrieval |
| 이 블로그 적용 | `content/wiki/`를 정제 레이어로 유지 | 검색 챗봇이나 대규모 원문 검색에는 보조적으로 유지 |

이 블로그의 [[블로그-검색-실험]]은 BM25·벡터·하이브리드 검색을 비교하는 RAG 관점의 실험이고, LLM Wiki는 그 위에 올라가는 **정제된 지식 레이어**에 가깝다. 즉 `content/wiki/`는 사람이 읽고 LLM이 재사용할 canonical synthesis, RAG/검색은 원문 회수와 누락 보완용으로 함께 쓰는 구조가 자연스럽다.[^3][^4]

## How to Apply to This Blog

현재 `syshin0116.dev`는 이미 LLM Wiki 패턴의 골격을 갖고 있다.

- 원문 레이어: `content/AI/`, `content/Tools/`, `content/Study/`, `content/Projects/` 등 기존 글
- 정제 레이어: `content/wiki/`
- 스키마/가드레일: `AGENTS.md`, `CLAUDE.md`의 "source posts immutable, wiki curated" 규칙
- 렌더링: Nuartz/Next.js가 frontmatter `summary`, `tags`, wikilink, graph/backlink를 렌더링

다음 순서로 강화하면 된다.

1. **raw/source 경계 명확화**: 기존 source post는 계속 immutable로 두고, 새로 수집하는 외부 자료는 `content/raw/` 또는 `.wiki-cache/raw/`처럼 별도 원문 폴더에 저장한다. 공개하고 싶은 raw만 `content/` 아래에 둔다.
2. **전용 wiki-curator 스킬 추가**: 팀 위키 사례처럼 `ingest`, `lint`, `reflect`, `migrate`를 분리한다. 이 블로그에서는 우선 `ingest`와 `lint`만 자동화해도 효과가 크다.
3. **index/log 자동화**: `content/wiki/index.md`는 모든 페이지 요약 테이블과 source catalog를 deterministic script로 재생성하고, `content/wiki/log.md`는 append-only로 유지한다.
4. **검증 게이트 추가**: wikilink가 실제 파일 basename으로 resolve되는지, 필수 frontmatter(`title`, `type`, `tags`, `sources`, `summary`, `created`, `updated`, `author`, `draft`)가 있는지, footnote/source가 비어 있지 않은지 검사하는 `verify-wiki` 스크립트를 둔다.
5. **자동 PR 루틴 연결**: source post 또는 raw 자료가 추가되면 GitHub Actions가 루틴을 fire하고, 루틴은 `content/wiki/` 변경만 담은 PR을 만든다. main 직접 push보다 PR diff로 사람이 검토하는 편이 안전하다.
6. **검색 챗봇과 연결**: 현재 RAG/검색 챗봇은 먼저 `content/wiki/index.md`와 관련 wiki page를 읽고, 부족할 때만 원문 검색으로 내려가게 한다. 이렇게 하면 canonical synthesis를 우선 사용하면서도 누락 회수를 보완할 수 있다.

## Implementation Notes from the Example Repos

| 예시 레포 | 적용 방식 | 이 블로그에 가져올 점 |
|-----------|-----------|------------------------|
| `team-wiki` | raw는 사람/Obsidian이 작성, wiki는 Routine이 작성, path-guard CI와 pre-commit hook으로 경계 강제 | `content/wiki/` 직접 수정 방지, raw frontmatter 검증, 루틴 PR 자동 생성 |
| `deep-agent-builder-claw-wiki` | PM 위키. 여러 제품 레포의 architecture/features/scenarios/research/proposals/status를 한 레포에 축적 | 블로그 프로젝트별 wiki cluster, 리서치 로그, "질문거리→proposal" 흐름 |
| `consulting-wiki` | 컨설팅 위키. PROJECT-first → wiki-search → 답변 → wiki-write 루프 | 큰 주제별 `PROJECT.md`/MOC를 두고, 답변 후 새 인사이트를 wiki에 환원 |

## Connections

- [[second-brain-rag]] - LLM Wiki는 Second Brain + RAG 아이디어에서 검색 중심 부분을 줄이고, LLM이 유지하는 정제 Markdown 레이어를 앞세운 구현 패턴이다.
- [[zettelkasten]] - LLM Wiki의 wikilink와 cross-reference는 Zettelkasten의 연결 중심 지식 조직을 LLM 유지보수 루프로 자동화한다.
- [[블로그-검색-실험]] - 이 블로그의 RAG/검색 실험은 raw/source 검색 계층이고, LLM Wiki는 그 결과를 누적하는 curated synthesis 계층이다.
- [[obsidian-notion-sync]] - 팀 위키 사례처럼 Obsidian을 authoring UI로 쓰면 raw 작성 경험을 유지하면서 Git/웹 배포/LLM 정제를 붙일 수 있다.

## Footnotes

[^1]: [Karpathy, "LLM Wiki" gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
[^2]: [Starmorph, "How to Build Karpathy's LLM Wiki"](https://blog.starmorph.com/blog/karpathy-llm-wiki-knowledge-base-guide)
[^3]: [MindStudio, "Where RAG Breaks Down: The Karpathy LLM Wiki Alternative"](https://www.mindstudio.ai/blog/karpathy-llm-wiki-pattern-knowledge-base-without-rag)
[^4]: [Atlan, "LLM Wiki vs RAG: The Karpathy Concept and Enterprise Reality"](https://atlan.com/know/llm-wiki-vs-rag-knowledge-base/)
[^5]: private repository example A — inspected files: `README.md`, `CLAUDE.md`, `docs/02-ai-curation.md`, `.claude/skills/wiki-curator/`
[^6]: private repository example B — inspected files: `README.md`, `00-overview.md`, `research-log/`, `proposals/`
[^7]: private repository example C — inspected files: `CLAUDE.md`, `docs/wiki/PROJECT.md`, `docs/wiki/99_Settings/`
