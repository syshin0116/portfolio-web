---
title: "Nuartz: Quartz를 Next.js로 다시 만들기까지의 여정"
date: 2026-03-01
tags:
  - Projects
  - Nuartz
  - Nextjs
  - Quartz
  - Digital-Garden
draft: false
enableToc: true
description: Quartz 기반 블로그의 UI 한계를 느끼고, Next.js + shadcn/ui + AI Agent를 결합한 디지털 가든 nuartz를 기획하기까지의 기술 의사결정 과정을 기록한다.
summary: "Obsidian으로 노트를 관리하다 웹 퍼블리싱이 필요해졌고, Obsidian 호환성이 가장 좋은 Quartz를 선택했다. 그런데 UI 커스터마이징 한계와 AI Agent 연동 욕심이 생기면서 shadcn/ui + Next.js 기반으로 직접 다시 만들기로 했다. 처음엔 Quartz를 통째로 래핑하는 전략을 썼다가 구조적 문제를 발견했고, 결국 필요한 것만 가져오는 현실적인 전략으로 방향을 바꿨다. 이 글은 그 과정에서 고민한 것들의 기록이다."
---
> [!info] 아이러니
> 이 글 자체는 Quartz 위에서 작성되고 서빙된다. nuartz가 완성되면 이 글도 그 위에서 보이게 될 것이다.

---

## 목적

노트 관리 도구로 Obsidian을 쓰기 시작하면서 자연스럽게 웹 퍼블리싱이 필요해졌다. wikilink, callout, backlink, graph view - Obsidian의 핵심 기능들이 웹에서도 똑같이 동작해야 했다. 여러 도구를 찾아보다 [Quartz](https://quartz.jzhao.xyz/)를 발견했다. Obsidian 볼트를 그대로 웹사이트로 변환해주는 정적 사이트 생성기로, Obsidian 호환성만큼은 타의 추종을 불허했다.

한동안은 만족스러웠다. 그런데 쓰다 보니 두 가지가 계속 걸렸다.

첫째, **UI가 마음에 안 든다.** Quartz의 기본 디자인은 나쁘지 않지만, shadcn/ui 기반으로 직접 만들고 싶었다. 커스터마이징 여지도 생기고, React 생태계의 컴포넌트를 자유롭게 쓸 수 있으니까.

둘째, **AI Agent를 붙이고 싶다.** 단순히 글을 보여주는 것을 넘어서, 내 Obsidian 노트를 기반으로 질문에 답하고, 노트 간 연결을 탐색하고, 파일 기반 검색이 가능한 시스템을 만들고 싶었다. 결국 지식 관리 도구로 확장하고 싶었다.

그래서 목표는 이렇게 정리됐다:

```
Obsidian으로 노트 관리
    +
Next.js + shadcn/ui로 웹 서빙
    +
LangGraph + RAG으로 AI Agent 채팅
```

이 프로젝트 이름을 **nuartz**라고 붙였다. Next.js + Quartz.

---

## 첫 번째 접근: sync-quartz

### 아이디어

처음 떠올린 전략은 단순했다. Quartz를 그대로 쓰되, Next.js 위에서 돌아가도록 래핑하자.

```
upstream/quartz/ (Quartz 소스코드 clone)
    ↓ sync-quartz.ts 스크립트로 복사
packages/nuartz/quartz/ (복사된 Quartz 플러그인)
    ↓ nuartz 코드가 래핑
packages/nuartz/src/ (Next.js 통합 레이어)
```

`sync-quartz.ts` 스크립트가 Quartz 레포를 clone하고, 필요한 파일들을 복사해오는 방식이다. Quartz가 업데이트되면 스크립트를 다시 돌리면 된다는 아이디어였다.

```typescript
// scripts/sync-quartz.ts
const SYNC_TARGETS = [
  { from: 'quartz/plugins', to: 'plugins' },
  { from: 'quartz/util', to: 'util' },
  { from: 'quartz/components', to: 'components' },
  // ...
]

// upstream Quartz에서 파일 복사
await cp(sourcePath, destPath, { recursive: true })
```

혼자 유지보수할 시간이 없으니, Quartz 개발자들이 업데이트하는 걸 가져오는 식으로 하자는 생각이었다.

### 왜 문제였나

실제로 만들어보니 구조적인 문제가 있었다.

> [!warning] "auto-sync"의 실체
>
> sync-quartz 전략은 결국 **파일 복사**다.
>
> ```diff
> - 진짜 auto-sync: 버전 의존성으로 관리
> + 실제 동작: Quartz 소스코드를 cp로 복사
> ```
>
> Quartz 내부 구조가 바뀌면 복사해도 타입 에러, 런타임 에러가 난다. 결국 Quartz 내부 변화를 직접 추적해야 한다. 포크를 유지보수하는 것과 난이도가 비슷하다.

게다가 실제로 구현을 시작하자마자 막혔다. Quartz의 transformer 플러그인들이 **inline script**를 emit하는데, 이 스크립트들이 Quartz 자체 런타임을 가정하고 있어서 Next.js에서 그대로 쓸 수가 없었다.

결국 transformer wrapper는 전부 빈 배열을 반환하는 상태로 멈췄다:

```typescript
// packages/nuartz/src/plugins/transformers/index.ts
export function getDefaultTransformers(): QuartzTransformerPluginInstance[] {
  // TODO: inline script 이슈 해결 후 구현
  return []  // ← 아무것도 안 함
}
```

README에는 "✅ Full Obsidian Compatibility"라고 써있지만, wikilink도 callout도 아무것도 처리하지 않는 상태였다.

왜 막혔는지 제대로 파악하려면 Quartz 플러그인 구조를 직접 뜯어봐야 했다. → [[02-Quartz-Internals|Quartz 플러그인 해부]]

---

## AI 스택 선택

### Next.js가 맞는 이유

AI Agent 기능이 들어가는 순간 서버가 필요하다.

```
사용자 질문 → API Route → LLM 호출 → 스트리밍 응답
```

Quartz, Astro(static), GitHub Pages로는 불가능하다. Next.js의 API Routes / Server Actions가 자연스러운 선택이다.

### Vercel AI SDK vs LangGraph

처음엔 Vercel AI SDK를 고려했다. Next.js와 통합이 제일 깔끔하고, streaming UI도 `useChat` 훅 하나로 된다.

그런데 실제 docs를 보니 "Skills/Harness" 개념이 다르다는 걸 알았다.

> [!warning] Vercel AI SDK의 "Skills"는 다른 개념
>
> Vercel Skills = `SKILL.md` 파일 기반 "플러그인 프롬프트"
>
> 코드 에이전트(Cursor 같은 것)에 명령 파일을 로드하는 개념이다. 내가 원하는 graph-based skill routing이 아니다.

Vercel AI SDK의 실제 한계 (공식 docs 명시):
- 체크포인팅 없음 → 직접 구현해야 함
- Human-in-the-loop 없음
- 문서에서 직접 "비결정적(non-deterministic)으로 설계됐다"고 인정

내가 원하는 harness 패턴은 LangGraph의 개념이다.

### LangGraph JS vs Python

| | LangGraph JS | LangGraph Python |
|---|---|---|
| 성숙도 | v1.0.x, production 가능 | 레퍼런스 구현, 가장 성숙 |
| Next.js 통합 | 동일 코드베이스 | 별도 Python 서버 필요 |
| 체크포인팅 | PostgreSQL adapter 있음 | AsyncPostgresSaver (battle-tested) |
| deepagents harness | 없음 | ✅ 있음 |
| ML 생태계 | 보통 | 압도적 |
| 새 기능 | Python 이후 도착 | 먼저 나옴 |

> [!quote] 내가 내린 결론
>
> AI 개발자로서 제대로 만들려면 **LangGraph Python + deepagents harness**가 맞다.
>
> deepagents는 LangChain이 만든 agent harness 프레임워크로, planning → task decomposition → subagent spawn → skill routing이 전부 구현되어 있다. Python이 가진 ML 생태계(벡터 DB, 문서 로더, 임베딩)와 함께 쓰면 RAG 파이프라인도 훨씬 풍부하다.
>
> Next.js와의 통합은 기존 `portfolio-ai` 패턴처럼 Python 서버를 별도로 띄우고 API로 호출하면 된다.

RAG 실험 자체는 [[Projects/Blog-rag/00-Overview|blog-rag]] 프로젝트에서 다룬다.

---

## 참고자료

- [Quartz - jackyzha0](https://quartz.jzhao.xyz/)
- [Quartz GitHub](https://github.com/jackyzha0/quartz)
- [LangGraph Python Docs](https://langchain-ai.github.io/langgraph/)
- [LangGraph JS Docs](https://docs.langchain.com/oss/javascript/langgraph/overview)
- [Vercel AI SDK Docs](https://ai-sdk.dev/docs/foundations/agents)
- [[LangGraph]]
- [[2025-06-04-Agent Architecture Comparison]]
