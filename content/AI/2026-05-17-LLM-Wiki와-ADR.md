---
title: "LLM Wiki와 ADR로 블로그를 누적 지식베이스로 키우기"
date: 2026-05-17
tags:
  - AI
  - LLM
  - knowledge-base
  - PKM
  - LLM-Wiki
  - ADR
  - architecture-decision-records
  - Karpathy
  - markdown
  - agent-memory
  - obsidian
  - RAG
  - second-brain
draft: false
enableToc: true
description: Karpathy의 LLM Wiki 패턴에 ADR(Architecture Decision Records)을 결합해 개인 블로그를 누적 지식베이스로 발전시키는 방법. 패턴의 원전, 실제 사례 3종, 2026 연구 결과, 실패 모드와 스케일 한계까지 정리한다
summary: "LLM Wiki는 RAG의 대체재가 아니라 그 위에 올라가는 정제 레이어다. 여기에 append-only ADR 레이어를 더하면 mutable wiki가 잃어버리는 결정의 history까지 함께 잡을 수 있다. Karpathy의 원전 패턴과 2026년 ADR 자동화 연구를 종합해 개인 블로그(syshin0116.dev)를 누적 지식베이스로 진화시키는 설계를 정리한다."
published: 2026-05-17
modified: 2026-05-17
---

## 들어가며

블로그를 4년쯤 쓰면 글이 280개를 넘고, 그 중 절반은 본인도 어디에 뭘 썼는지 모른다. AI 시대에 이게 더 답답한 이유는 단순하다. **글이 많이 쌓일수록 LLM에 던졌을 때 잘 회상되지 않는다.** RAG를 붙여도 chunk 단위로 잘려 나오고, 같은 주제가 여러 글에 흩어져 있으면 검색은 빠지고 답은 일반론이 된다.

Karpathy가 2026년 봄에 올린 ["LLM Wiki"](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) gist는 이 문제에 다른 각을 제시한다. **LLM이 원문을 읽어서 "정제된 위키"를 직접 만들고 계속 갱신한다.** 질문은 위키 페이지를 보고 답하고, 답하다가 새 인사이트가 생기면 위키에 다시 환원한다. RAG가 매번 원문 chunk를 검색해 종합한다면, LLM Wiki는 종합을 ingest 시점에 한 번만 한다.

이 글은 LLM Wiki 패턴을 정리하고, 그 약점인 **"왜 이 결정을 했는지의 history"** 를 보완하는 ADR(Architecture Decision Records) 레이어를 같이 묶는다. 그리고 그 둘을 합쳐 이 블로그(syshin0116.dev)에 어떻게 적용할지 설계한다.

> [!note] 사전 지식 참고
> [[블로그-검색-실험]] 시리즈에서 다룬 BM25/벡터/하이브리드 검색이 RAG 관점의 실험이라면, 이 글은 그 위에 올라가는 **정제 지식 레이어** 이야기다. RAG와 LLM Wiki는 경쟁이 아니라 같은 스택의 다른 층이다. 발상의 계보로 보면 [[second-brain-rag|Second Brain + RAG]]가 누적된 개인 노트를 *검색 중심*으로 활용하려 했고, LLM Wiki는 같은 문제를 *정제 중심*으로 푼다.

---

## LLM Wiki란 무엇인가

Karpathy의 원전 비유가 가장 짧다.

> *"Obsidian이 IDE, LLM이 프로그래머, 위키가 코드베이스다."*

코드베이스가 시간이 가면서 정제되고 리팩터되듯, **지식도 LLM이라는 프로그래머가 계속 정제·리팩터하는 산출물**이라는 시각이다. 위키 자체가 첫 클래스 산출물이고, 사람은 그걸 읽고 LLM은 그걸 갱신한다.

### 표준 3층 구조

세 폴더가 책임을 가른다.[^karpathy][^starmorph]

| 폴더 | 누가 작성 | mutability |
|------|-----------|------------|
| `raw/` | 사람 (또는 외부 수집) | immutable 원천 자료 |
| `wiki/` | LLM (사람은 가끔 교정) | mutable, 정제된 페이지 |
| `AGENTS.md` / `CLAUDE.md` | 사람 | 스키마와 운영 규칙 |

운영 사이클은 셋이다.

- **ingest** - 새 raw 자료를 읽고 관련 위키 페이지를 만들거나 갱신
- **query** - 위키를 보고 답하고, 답하면서 생긴 인사이트를 다시 위키에 파일링
- **lint** - 주기적으로 broken link, orphan, stale claim, contradiction을 점검

결국 신기술이 들어간 게 아니라 **"LLM이 Markdown을 읽고 쓰는 루프를 일관되게 돌린다"**가 전부이고, 이 단순함이 곧 강점이 된다.

### LLM Wiki vs RAG

흔한 오해는 *"이게 RAG 대체재인가"* 다. 답은 "아니오". 두 패턴은 **다른 시점에 종합을 한다**.

| 관점 | RAG | LLM Wiki |
|------|-----|----------|
| 종합 시점 | 질문할 때마다 retrieval → synthesis | ingest 때 한 번 정제, 페이지로 보존 |
| 저장 형태 | 원문 chunk + embedding + vector DB | Markdown 파일 + wikilink + index |
| 강점 | 대규모, 동적, 권한 제어, 다중 소스 | 작고 curated한 코퍼스, 투명한 provenance, git diff/review |
| 실패 모드 | chunking 손실, retrieval miss, opaque | stale page, 잘못된 LLM 편집, index 부실 |
| 스케일 한계 | 본질적으로 무제한 | LLM 컨텍스트 + 사람이 읽을 만한 규모 |

[Atlan](https://atlan.com/know/llm-wiki-vs-rag-knowledge-base/)과 [MindStudio](https://www.mindstudio.ai/blog/karpathy-llm-wiki-pattern-knowledge-base-without-rag)의 해석을 빌리면, **LLM Wiki는 bounded corpus에 대한 compile-time synthesis**다. 문서가 수만~수십만 토큰 규모이고 큐레이션이 가능한 영역(개인 노트, 회사 위키, 컨설팅 프로젝트)에서 단순하고 투명하지만, 수백만 문서·고빈도 변경·세밀한 권한 제어가 있는 엔터프라이즈 지식에는 여전히 RAG와 데이터 카탈로그가 필요하다.

### 스케일이 결정한다

페이지 수를 임계치로 보면 어디서 RAG가 다시 들어와야 하는지가 또렷해진다.

| 페이지 수 | 운영 방식 |
|-----------|-----------|
| ~50 | LLM이 `index.md`만 보고 답 가능 |
| ~500 | index + 관련 페이지 selective load 필요. 요약 품질이 결정적 |
| 1000~ | 결국 RAG가 필요. LLM Wiki는 RAG의 **정제 인덱스** 역할로 후퇴 |

이 블로그가 지금 wiki 페이지 24개라는 걸 감안하면 *"한참 여유 있는 구간"* 이다. 페이지 품질에 집중할 시기.

---

## ADR 레이어: append-only로 '왜'를 기록하기

LLM Wiki의 진짜 약점은 단순하다. **mutable**이라는 점이다. 페이지는 계속 정제·갱신되니 "지금 X는 뭔가?"에는 잘 답하지만, **"왜 X로 결정했나?"는 git diff에 묻혀 잘 회상되지 않는다.** Wiki 페이지의 최신 버전만 봐서는 그 페이지가 어떤 가설을 거쳐 지금 모습이 됐는지 모른다.

ADR(Architecture Decision Records)은 정확히 이 결손을 보완한다. Michael Nygard가 2011년에 제안한 단순한 규약이다.[^nygard]

- **한 결정 = 한 파일** (번호가 매겨짐: ADR-0001, ADR-0002, ...) - [[zettelkasten]]의 ID 기반 immutable 노트와 같은 발상이다
- **immutable** - 한 번 작성되면 내용은 안 바뀐다
- **append-only** - 결정이 뒤집힐 때는 새 ADR을 추가하고 이전 ADR을 `superseded-by`로 가리킨다

### 3-layer 비교

LLM Wiki와 RAG와 ADR을 한 표에 놓으면 분업이 명확해진다.

| 레이어 | 시간 모델 | 답하는 질문 | 실패 모드 |
|--------|-----------|-------------|-----------|
| **RAG / 원문 검색** | 검색 시점 snapshot | "X에 대한 원문 어디?" | retrieval miss, chunk 손실 |
| **LLM Wiki** | mutable, 최신 상태 | "X는 지금 뭔가?" | stale, drift, contradiction |
| **ADR** | append-only, immutable | "왜 X로 결정했나?" | 결정 누락, 사후 합리화 |

### Agent memory 문헌과의 매핑

LLM 에이전트 메모리 연구는 working/semantic/episodic 3계열을 표준 분류로 쓴다.[^memory]

- **Working memory** - 지금 컨텍스트 윈도우에 들어가 있는 것
- **Semantic memory** - distilled fact/concept. 시간 정보 없이 "X는 이런 거다"
- **Episodic memory** - 시간순 사건 기록. "언제 무엇이 있었다"

이 분류로 보면 **LLM Wiki는 semantic memory**, **ADR은 episodic memory**에 정확히 대응한다. 한 시스템 안에서 두 종류 memory를 분업시킨다고 보면 된다. ["AI Agent Memory: When Markdown Files Are All You Need"](https://dev.to/imaginex/ai-agent-memory-management-when-markdown-files-are-all-you-need-5ekk)는 이미 이 분업을 자연스럽게 채택한다 - `MEMORY.md`(mutable, 정제)와 `memory/YYYY-MM-DD.md`(append-only, 로그)를 같이 둔다.[^markdown-memory]

### 3-layer 아키텍처 다이어그램

![[assets/llm-wiki-adr-layers.svg]]

> Codex가 만든 Mermaid 정의를 SVG로 미리 렌더해 저장했다. 편집용 소스는 [llm-wiki-adr-layers.mmd](assets/llm-wiki-adr-layers.mmd) (Mermaid)와 [llm-wiki-adr-layers.excalidraw](assets/llm-wiki-adr-layers.excalidraw) (Excalidraw)에 같이 보관한다.

---

## 2026 연구가 말하는 LLM × ADR

2026년 들어 ADR을 LLM으로 자동 생성하거나 LLM에 컨텍스트로 먹이는 연구가 빠르게 늘었다. 두 가지 결과가 LLM Wiki 설계에 직접 영향을 준다.

### Last-K 컨텍스트 전략이 우승했다

[arXiv 2604.03826](https://arxiv.org/html/2604.03826v1) "Context Matters: Evaluating Context Strategies for Automated ADR Generation Using LLMs"는 다섯 가지 컨텍스트 전략을 비교했다.[^context-matters]

- **Last-K** - 최근 K개 ADR을 컨텍스트로
- **All-History** - 전체 ADR 다 줌
- **First-K** - 초기 ADR을 줌
- **RAFG** - retrieval-augmented (벡터 검색)
- **None** - 컨텍스트 없이

결과는 명확했다. **Last-K(3~5개)가 All-History와 거의 동일한 품질을 내면서 토큰을 압도적으로 적게 쓴다.** 즉 ADR이 100개 쌓여도 매번 100개를 다 로드할 필요 없다는 거다. 새 ADR을 쓸 때는 직전 3~5개만 보여주면 된다. 페이지 수가 늘어도 운영 비용이 폭증하지 않는 구조.

추가로, Gemma3-4B 같은 작은 로컬 모델도 컨텍스트만 잘 주면 GPT-5급 모델과 비슷한 ADR 품질을 낸다고 보고됐다. 모델 크기보다 컨텍스트 엔지니어링 쪽이 결과를 더 크게 좌우한다는 뜻이다.

### Self-contained ADR이 더 잘 동작한다

같은 논문에서 흥미로운 부수 결과가 나왔다. **외부 wiki/design doc로 링크 거는 ADR보다, rationale을 안에 다 적은 self-contained ADR이 LLM 이해도가 훨씬 높다.**

이게 흥미로운 이유는 **LLM Wiki의 설계 원칙과 정면으로 충돌**하기 때문이다.

| | LLM Wiki | ADR |
|---|----------|-----|
| 연결 전략 | wikilink로 거미줄을 짠다 | 안쪽으로 닫는다 (self-contained) |
| 이유 | 페이지가 모듈처럼 재사용 | 결정의 컨텍스트가 그 자체로 보존돼야 함 |

함의는 분명하다. ADR과 Wiki를 같이 쓸 때 **방향성 있는 링크 규칙**을 둬야 한다.

- **Wiki → ADR 링크**: 허용 (위키 페이지가 "이 결정에 따랐다"고 ADR을 가리킴)
- **ADR → Wiki 링크**: 최소화 (ADR은 자기 안에 컨텍스트를 다 적음)

### MADR 4.0.0 / YADR 표준

ADR 템플릿 표준은 [MADR 4.0.0](https://adr.github.io/madr/) (2024-09 릴리스)이 사실상 정착했다. 2026년 3월에는 YAML 변형인 YADR도 나왔다.

MADR 4.0.0의 구조는 단순하다.

```markdown
---
status: accepted   # proposed | rejected | accepted | deprecated | superseded by ADR-XXXX
date: 2026-05-17
decision-makers: [syshin0116]
consulted: []
informed: []
---

# {결정 제목}

## Context and Problem Statement
{2~3문장으로 문제 진술}

## Decision Drivers
- {제약/관심사 1}
- {제약/관심사 2}

## Considered Options
- {옵션 A}
- {옵션 B}

## Decision Outcome
선택: **옵션 A**. 이유: ...

### Consequences
- 좋아지는 것: ...
- 나빠지는 것: ...
```

이 블로그 wiki 페이지가 쓰는 frontmatter(`title`, `type`, `tags`, `summary`, `sources`, `created`, `updated`)에 `status`, `supersedes`, `superseded-by`만 더하면 `type: decision` 페이지로 자연스럽게 합쳐진다.

### Multi-agent ADR 생성

[AgenticAKM](https://arxiv.org/html/2602.04445v1)을 비롯한 2026년 연구들은 ADR 자동 생성을 **Extract → Retrieve → Generate → Validate** 4단계 멀티 에이전트로 푼다. 이 블로그의 wiki-curator 스킬에 `decide` 액션을 추가한다면 동일한 4단계로 쪼개는 게 자연스럽다.

---

## 운영 패턴: 팀으로 확장할 때의 원칙

LLM Wiki를 팀 단위로 확장할 때 중요한 건 특정 구현 사례가 아니라 역할 분리다.

- 사람은 원천 메모와 결정 승인을 담당한다.
- agent는 원천 자료를 읽고 wiki 초안, 정리 PR, 검증 로그를 만든다.
- `content/`처럼 배포되는 공개 콘텐츠와 내부 운영 상태(hash ledger, review queue, 내부 로그)는 분리한다.
- wiki는 최신 지식의 mutable layer로 두고, decision history는 ADR처럼 append-only layer로 남긴다.

이 정도만 지켜도 개인 블로그의 wiki 구조를 팀 지식베이스로 확장할 때 생기는 대부분의 문제를 줄일 수 있다.

---

## 실패 모드: 운영자가 미리 알아야 할 것

LLM Wiki는 단순한 만큼, 실패 모드도 단순하고 반복적이다. 미리 알면 lint 단계에서 잡을 수 있다.

### Hallucinated synthesis

LLM이 raw에 없는 내용을 그럴듯하게 위키 페이지에 추가하는 경우. ingest 시점에 *"인용 가능한 source 라인을 footnote로 박아라"* 같은 규칙을 강제하지 않으면 자주 발생한다. **모든 주장에 source/footnote 강제 + lint 단계에서 verify**가 기본 방어선.

### Stale claim

원본 글이 갱신됐는데 그걸 정제한 wiki 페이지는 그대로 남는 경우. raw 파일의 mtime이나 hash를 추적해 변경된 raw를 가리키는 wiki 페이지를 stale로 마킹해야 한다. hash ledger를 별도로 두는 이유.

### Contradiction drift

같은 주제가 여러 페이지에 흩어지면서 서로 모순이 누적되는 경우. 페이지 수가 50을 넘기 시작하면 자연스럽게 발생한다. 주기적인 `reflect` 작업으로 *"같은 주장을 다르게 적은 페이지 쌍"* 을 찾아 통합하거나 cross-link해야 한다.

### Link rot / orphan

wikilink target이 사라지거나, 어디서도 인용되지 않는 페이지가 누적. `verify-wiki` 스크립트가 모든 wikilink를 basename으로 resolve할 수 있는지 검사하고, backlink 0인 페이지는 orphan 후보로 보고한다.

### Tag entropy

비슷한 의미의 태그가 무한 증식한다. `ai-agent`와 `agent`, `knowledge-management`와 `pkm`처럼. 주기적인 `migrate` 작업으로 controlled vocabulary로 정리해야 한다. 이 블로그 `content/wiki/log.md`에 이미 한 번 겪은 흔적이 남아 있다 - 26 페이지에서 `ai-agent → agent`(4 페이지), `knowledge-management → pkm`(2 페이지) 통합.

### ADR 쪽 실패 모드

ADR도 자기만의 실패 모드가 있다.

- **결정 누락** - 중요한 결정이 ADR로 기록되지 않고 코드/위키에만 남는다. *"이 변경은 ADR이 필요한가?"* 를 PR 체크리스트에 넣어야 한다
- **사후 합리화** - 결정 *후*에 ADR을 적으면 "왜 그렇게 안 했지?" 옵션을 충분히 적지 않는 경향. *"considered options에 진짜 reject된 옵션이 있는가"* 가 ADR 품질 시그널
- **Superseded chain 단절** - ADR-0007이 ADR-0003을 supersede했는데 ADR-0003에 `superseded-by` 표시가 안 되는 경우. 양방향 링크 검증이 lint에 들어가야 한다

---

## 개인 vs 팀 위키: 무엇이 다른가

위 세 사례는 모두 **팀 위키**다. 개인 블로그에 그대로 옮기면 과한 오버헤드가 생긴다. 차이를 정리해 둔다.

| | 팀 위키 | 개인 위키 |
|---|---------|----------|
| path-guard CI / pre-commit hook | 필요 (사람이 여럿이라 직접 수정 충돌) | 과함 - 본인이 직접 수정해도 무방 |
| PR 기반 워크플로우 | 필요 (리뷰가 핵심) | 선택 - 큰 변경만 PR로 |
| 권한 분리 (raw 작성자 vs wiki 편집자) | 필요 | 무관 |
| ADR의 `decision-makers` | 여러 명 명시 | 본인 1명, 거의 생략 가능 |
| ADR이 다루는 결정 | 팀 합의 사항 | 본인 가설 / 설계 선택 |
| 운영 비용 압박 | 토큰 비용·시간 모두 의식 | 토큰 비용 위주 |

개인 위키에서 **중요한 건 따로 있다**.

- **Low-friction ingest** - Obsidian 단축키 한 번, 블로그 PR 자동 등 마찰 0에 가깝게
- **Draft 상태 유지** - frontmatter `draft: true` 페이지가 자유롭게 있을 수 있어야 함
- **자기참조** - 블로그 검색 챗봇이 wiki를 우선 읽도록 강제

---

## 이 블로그에 어떻게 적용하는가

`syshin0116.dev`는 이미 LLM Wiki 패턴의 골격을 갖고 있다.

- 원문 레이어: `content/AI/`, `content/Tools/`, `content/Study/`, `content/Projects/` 등 기존 글 (immutable)
- 정제 레이어: `content/wiki/` 24 페이지
- 스키마: `AGENTS.md`, `CLAUDE.md`의 *"source posts immutable, wiki curated"* 규칙
- 렌더링: Quartz/Nuartz가 frontmatter, wikilink, graph view, backlink를 모두 처리

다음 6단계로 강화하면 ADR 레이어까지 포함하는 누적 지식베이스가 된다.

### 1. raw / source 경계 명확화

기존 source post는 계속 immutable로 두고, 새로 수집하는 외부 자료(예: 다른 사람 글 발췌, 논문 메모)는 `content/raw/` 또는 `.wiki-cache/raw/`처럼 별도 원문 폴더로 분리한다. 공개하고 싶은 raw만 `content/` 아래에 둔다.

### 2. wiki-curator 스킬 액션 확장

이 블로그 `.claude/skills/wiki-curator/`는 이미 `ingest`, `lint`, `reflect`, `migrate`를 분리해 갖고 있다. 여기에 **`decide`**(ADR 작성/갱신/supersede)를 추가한다. 4단계 멀티 에이전트 패턴(Extract → Retrieve → Generate → Validate)을 그대로 따른다.

### 3. content/wiki/decisions/ 폴더 신설

`type: decision` frontmatter를 새 type으로 도입한다. MADR 4.0.0 호환 필드(`status`, `supersedes`, `superseded-by`, `decision-makers`)를 추가한다. 처음 작성할 ADR은 다음 같은 것들이다.

- ADR-0001: 왜 raw/wiki를 분리하는가
- ADR-0002: 왜 wikilink는 한글 basename을 허용하는가
- ADR-0003: 왜 type을 4종(pattern/concept/reference/tool)으로 한정했는가
- ADR-0004: 왜 ADR을 추가하기로 했는가 *(이 글의 결과)*

### 4. 검증 게이트

`verify-wiki` 스크립트를 만든다. 다음을 검사한다.

- wikilink가 실제 파일 basename으로 resolve되는가
- 필수 frontmatter(`title`, `type`, `tags`, `sources`, `summary`, `created`, `updated`, `author`, `draft`)가 있는가
- footnote/source가 비어 있지 않은가
- ADR의 경우 `status`가 유효한 값이고, `supersedes` 양방향이 일관되는가

### 5. 자동 PR 루틴

source post 또는 raw 자료가 추가되면 GitHub Actions가 Anthropic Routine을 fire하고, 루틴이 `content/wiki/` 변경만 담은 PR을 만든다. main 직접 push보다 PR diff로 검토하는 편이 hallucination 방어에 효과적이다. 결정 사안은 별도로 `decide` 액션이 ADR PR을 만든다.

### 6. 검색 챗봇과의 연결

현재 RAG/검색 챗봇은 먼저 `content/wiki/index.md`와 관련 wiki 페이지를 읽고, 부족할 때만 원문 검색으로 내려간다. 결정 관련 질의("왜 X를 선택했나")가 들어오면 **최근 ADR 3~5개를 Last-K 전략으로 동봉**한다. 2026 연구가 권하는 컨텍스트 전략 그대로다.

---

## 운영 메트릭: 위키 건강도

*"lint를 돈다"* 만으로는 부족하다. 무엇을 측정해 어떻게 건강도를 판단할지가 있어야 한다. 이 블로그 `content/wiki/log.md`가 이미 색상(red/yellow/blue) 분류를 쓰고 있으니, 그 기준을 메트릭화하면 다음 정도가 된다.

| 메트릭 | 정의 | 목표 |
|--------|------|------|
| coverage | source post 중 wiki page로 정제된 비율 | 60% 이상 |
| link density | page당 평균 wikilink 수 | 3~5 |
| freshness | 90일 내 updated 비율 | 30% 이상 |
| orphan ratio | backlink 0인 page 비율 | 10% 이하 |
| tag entropy | 사용 1회뿐인 tag 비율 | 20% 이하 |
| stale source | source post hash 변경 후 wiki 갱신 안 된 비율 | 5% 이하 |

ADR 쪽은 다른 메트릭이 적절하다.

| 메트릭 | 정의 | 목표 |
|--------|------|------|
| ADR coverage of major changes | "이 PR에 ADR이 필요했는가" 휴리스틱 통과율 | 가능한 한 높게 |
| supersede 양방향 일관성 | `supersedes` ↔ `superseded-by` 매치 | 100% |
| considered options 충분성 | 옵션이 1개뿐인 ADR 비율 | 0% (1개면 결정이 아님) |

---

## 다른 PKM/AI 도구와의 관계

LLM Wiki는 새로운 도구가 아니라 **운영 패턴**이다. 비슷한 방향으로 가는 도구들이 있다.

- **Obsidian + Smart Connections** - vault 안에서 RAG와 vault 그래프를 같이 쓴다. LLM Wiki와 가까운 위치
- **Logseq AI** - block-level 단위 정제. 페이지 단위인 LLM Wiki보다 입자가 작다
- **Notion AI** - 페이지 단위 요약/생성이 가능하지만 *"LLM이 위키 전체를 유지한다"* 보다는 *"개별 페이지를 보조한다"* 에 가까움
- **Cursor + AGENTS.md / CLAUDE.md** - 코드베이스 자체를 LLM이 유지하는 형태. Karpathy의 원래 비유가 코드베이스였던 만큼 같은 뿌리이고, 이쪽 흐름은 [[vibe-coding]]으로 따로 이름이 붙었다

이 블로그는 **Obsidian + Quartz + 자체 wiki-curator 스킬**의 조합으로 LLM Wiki를 구현한다고 정리할 수 있다. Obsidian이 ingest 인터페이스, Quartz가 publish 인터페이스, wiki-curator가 LLM 운영 루프.

---

## 정리

LLM Wiki는 *"LLM이 Markdown을 읽고 쓰는 루프를 일관되게 돌린다"* 가 전부인 단순한 패턴이다. 단순한 만큼 한계도 명확하다.

- 페이지 수 100을 넘기면 RAG의 도움이 필요해진다
- mutable이라 "왜"를 잃기 쉽다 - 여기서 ADR이 들어온다
- self-contained ADR vs 거미줄 wikilink는 정반대 원칙 - 방향성 있는 링크 규칙이 필요하다

이 블로그에 적용하면 6단계 강화로 LLM Wiki + ADR을 다 가질 수 있다. 단번에 다 만들 일은 아니고, 페이지 24개 → 50개 가는 동안 우선 wiki를 굳히고, decisions/ 폴더는 첫 4~5개 ADR로 시작해 천천히 늘리는 정도가 적절해 보인다.

기술 면에서 새로운 게 거의 없다는 게 이 패턴의 가장 큰 매력이다. Markdown, wikilink, footnote, frontmatter처럼 이미 우리가 쓰는 도구를 LLM이 일관되게 정제하는 루프 위에 얹기만 하면 된다.

---

## 참고 자료

### LLM Wiki

- [Karpathy, "LLM Wiki" gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
- [Starmorph, "How to Build Karpathy's LLM Wiki"](https://blog.starmorph.com/blog/karpathy-llm-wiki-knowledge-base-guide)
- [MindStudio, "Where RAG Breaks Down: The Karpathy LLM Wiki Alternative"](https://www.mindstudio.ai/blog/karpathy-llm-wiki-pattern-knowledge-base-without-rag)
- [Atlan, "LLM Wiki vs RAG: The Karpathy Concept and Enterprise Reality"](https://atlan.com/know/llm-wiki-vs-rag-knowledge-base/)

### ADR

- [Michael Nygard, "Documenting Architecture Decisions" (2011)](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions)
- [MADR (Markdown Architectural Decision Records) 4.0.0](https://adr.github.io/madr/)
- [ADR Templates](https://adr.github.io/adr-templates/)

### 2026 연구

- [Context Matters: Evaluating Context Strategies for Automated ADR Generation Using LLMs (arXiv:2604.03826)](https://arxiv.org/html/2604.03826v1)
- [AgenticAKM: Enroute to Agentic Architecture Knowledge Management (arXiv:2602.04445)](https://arxiv.org/html/2602.04445v1)
- [Building an ADR Writer Agent - Piethein Strengholt](https://piethein.medium.com/building-an-architecture-decision-record-writer-agent-a74f8f739271)

### Agent memory

- [A Practical Guide to Memory for Autonomous LLM Agents - TDS](https://towardsdatascience.com/a-practical-guide-to-memory-for-autonomous-llm-agents/)
- [AI Agent Memory Management: When Markdown Files Are All You Need - dev.to](https://dev.to/imaginex/ai-agent-memory-management-when-markdown-files-are-all-you-need-5ekk)
- [Design Patterns for Long-Term Memory in LLM-Powered Architectures - Serokell](https://serokell.io/blog/design-patterns-for-long-term-memory-in-llm-powered-architectures)

[^karpathy]: Karpathy의 gist는 IDE/programmer/codebase 비유와 raw/wiki/AGENTS.md 3층 구조를 같이 제시한다.
[^starmorph]: Starmorph 가이드는 ingest/query/lint 3 루프를 정형화했다.
[^nygard]: Nygard의 2011년 원전은 ADR을 *"커밋과 함께 가는 가벼운 결정 노트"* 로 정의했다.
[^memory]: 2025~2026년 LLM 에이전트 메모리 서베이들이 working/semantic/episodic 3계열 분류를 표준화했다.
[^context-matters]: arXiv 2604.03826의 결론: Last-K(3~5)가 All-History와 동등, RAFG는 cross-cutting 결정에만 우위, First-K는 underperform, 모델 크기보다 컨텍스트 엔지니어링이 결정적.
[^markdown-memory]: dev.to imaginex의 글은 MEMORY.md(mutable, 정제)와 memory/YYYY-MM-DD.md(append-only, 로그) 분업을 자연스럽게 채택한다.
