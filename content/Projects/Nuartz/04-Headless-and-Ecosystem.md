---
title: "Nuartz를 headless 라이브러리로: 설계 방향과 레포 생태계"
date: 2026-03-06
tags:
  - Projects
  - Nuartz
  - Architecture
  - Monorepo
  - Headless
draft: false
enableToc: true
description: Nuartz를 UI 없는 데이터 레이어로 유지하기로 결정한 이유, 그리고 개인 블로그/포트폴리오를 포함한 레포 생태계를 어떻게 재편했는지 기록한다.
summary: "Nuartz를 headless로 유지하기로 했다. 공식 데모 사이트와 개인 포트폴리오가 UI가 달라야 해서, packages/nuartz는 데이터 레이어만 export한다. 기존 4개 레포(syshin0116.github.io, portfolio-web, portfolio-ai, nuartz)를 nuartz + syshin0116.dev + blog-rag 3개로 재편했다."
---
> [!info] 이전 글
> Nuartz 첫 배포 과정은 [[03-Vercel-Deployment|이전 글]]에서 다뤘다.

Phase 1 배포를 마치고 나서 다음 단계를 준비하다 보니 두 가지 질문이 생겼다.

1. **Nuartz는 어디까지 담당해야 하나?** 마크다운 파싱만? 아니면 사이드바, 내비게이션 같은 UI 컴포넌트까지?
2. **블로그와 포트폴리오를 어떻게 구성하지?** 기존에 흩어져 있는 레포들을 어떻게 정리할까?

두 질문의 답이 서로 맞물려 있었다.

---

## Nuartz를 headless로 유지하기로 한 이유

처음엔 Nuartz에서 UI 컴포넌트(사이드바, 내비게이션, 레이아웃)도 제공하면 쓰기 편하지 않을까 생각했다. 그런데 이 방향에는 문제가 있다.

**Nuartz를 사용하는 앱이 둘이다.**


![[assets/nuartz-architecture.png]]

두 앱이 원하는 UI는 완전히 다르다. 공식 데모 사이트는 Nuartz 기능을 보여주는 게 목적이고, 개인 사이트는 포트폴리오 느낌이 나야 한다. 사이드바 구조도, 내비게이션 스타일도, 전체 레이아웃도 달라야 한다.

Nuartz가 UI를 강제하면 둘 중 하나는 오버라이드 지옥에 빠진다.

### headless란 구체적으로 무엇인가

`packages/nuartz`가 export하는 것:

```ts
// 파일 시스템 유틸
export { getAllMarkdownFiles, buildFileTree } from './fs'

// 마크다운 파싱
export { renderMarkdown } from './markdown'

// 검색 인덱스
export { buildSearchIndex } from './search'

// 백링크
export { buildBacklinkIndex, getBacklinks } from './backlinks'

// 타입
export type { Frontmatter, TocEntry, RenderResult } from './types'
```

UI 컴포넌트는 없다. 각 앱이 이 데이터를 가져다 자기 방식대로 렌더링한다.

```ts
// syshin0116.dev에서 쓰는 방식
import { getAllMarkdownFiles, renderMarkdown } from 'nuartz'

export default function BlogLayout() {
  return (
    <div>
      <MyPortfolioNavbar />   {/* 내 사이트 전용 UI */}
      <MyCustomSidebar />
      <Content />
    </div>
  )
}
```

React Query, Zod 같은 라이브러리가 UI 없이 로직만 제공하는 것과 같은 패턴이다.

> [!tip] Quartz와 비교하면
>
> Quartz는 완성된 UI까지 포함한 정적 사이트 생성기다. 쓰기 편하지만 커스터마이징이 어렵다.
> Nuartz는 데이터 레이어만 담당한다. UI는 소비하는 앱이 알아서 만든다. 자유도가 높은 대신 세팅이 필요하다.

---

## 레포 생태계 재편

이 결정이 나면서 기존 레포 구조도 정리할 때가 됐다.

### 기존 상황

| 레포 | 역할 | 문제 |
|------|------|------|
| `syshin0116.github.io` | Quartz 기반 블로그 | GitHub Pages 제약, Quartz UI |
| `portfolio-web` | 포트폴리오 프론트 | 블로그와 분리됨 |
| `portfolio-ai` | RAG 백엔드 | 위와 분리됨 |
| `nuartz` | 오픈소스 라이브러리 | 유지 |

`portfolio-web`에 블로그가 없고, 블로그에 포트폴리오가 없다. 둘을 따로 유지하는 건 방문자 입장에서도 혼란스럽고, 관리하는 입장에서도 비효율이다.

### 새 구조

```
nuartz            ← 오픈소스 라이브러리, 그대로 유지
syshin0116.dev    ← 블로그 + 포트폴리오 통합 (portfolio-web 흡수)
blog-rag          ← RAG 실험 백엔드 (portfolio-ai 리네임)
```

**`syshin0116.dev`** 내부 구조:

```
syshin0116.dev/
├── content/          ← 기존 syshin0116.github.io의 마크다운 그대로 이사
│   ├── AI/
│   ├── Dev/
│   ├── Projects/
│   └── ...
└── apps/web/         ← Nuartz 기반 Next.js 앱
```

Nuartz가 headless로 데이터 레이어만 제공하기 때문에, `syshin0116.dev`는 포트폴리오에 맞는 UI를 자유롭게 구성할 수 있다.

### 기존 레포 처리

- `syshin0116.github.io` → content/ 폴더로 이사 후 archive
- `portfolio-web` → `syshin0116.dev`로 흡수 후 archive
- `portfolio-ai` → `blog-rag`으로 rename

---

## 앞으로

레포 재편이 마무리되면 Nuartz 기반 블로그 위에서 RAG를 실험할 차례다. 블로그 콘텐츠를 대상으로 다양한 RAG 방법론을 테스트하고 비교하는 것은 [[Projects/Blog-rag/00-Overview|blog-rag]] 프로젝트에서 별도로 다룬다.

Nuartz 자체는 데이터 레이어에 집중한다. 파싱이 안정화되면 wikilink 해석, 백링크 인덱스, 검색 품질 개선 쪽으로 이어갈 예정이다.
