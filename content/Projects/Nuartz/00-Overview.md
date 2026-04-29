---
title: "Nuartz: Obsidian을 Next.js 블로그로"
date: 2026-03-01
modified: 2026-03-06
tags:
  - Projects
  - Nuartz
  - Nextjs
  - Quartz
  - Digital-Garden
  - Obsidian
draft: false
enableToc: true
description: Obsidian 노트를 Next.js로 서빙하는 오픈소스 라이브러리. Quartz를 headless 데이터 레이어로 재해석한다.
summary: "Obsidian으로 관리하는 노트를 웹에 퍼블리싱하고 싶었다. Quartz를 쓰다 UI 한계와 AI Agent 연동 욕심이 생겼고, shadcn/ui + Next.js 기반으로 직접 만든 게 Nuartz다. UI는 없고 데이터 레이어만 제공하는 headless 라이브러리로, 어떤 Next.js 앱이든 가져다 자기 UI로 감쌀 수 있다."
---
---

## 프로젝트 소개

**Nuartz**는 Obsidian 볼트를 Next.js 앱으로 서빙하기 위한 오픈소스 라이브러리다. 이름은 **Next.js + Quartz**의 합성어.

Quartz가 완성된 정적 사이트 생성기라면, Nuartz는 마크다운 파싱과 콘텐츠 유틸만 제공하는 **headless 데이터 레이어**다. UI는 소비하는 앱이 직접 만든다.

```ts
import { getAllMarkdownFiles, renderMarkdown, buildSearchIndex } from 'nuartz'

// 데이터만 가져오고, UI는 자유롭게
const files = await getAllMarkdownFiles('./content')
const { html, toc } = await renderMarkdown(file)
```

- GitHub: [syshin0116/nuartz](https://github.com/syshin0116/nuartz)
- npm: [nuartz](https://www.npmjs.com/package/nuartz)
- 데모/문서: [nuartz.vercel.app](https://nuartz.vercel.app)

---

## 핵심 기능

| 기능 | 설명 |
|------|------|
| 마크다운 파싱 | remark/rehype 파이프라인 + OFM 플러그인 |
| Obsidian 호환 | wikilink, callout, backlink, tag, graph view |
| 파일 시스템 | `getAllMarkdownFiles()`, `buildFileTree()`, draft 필터링 |
| 검색 | FlexSearch 기반 CJK-aware 인덱스 |
| 백링크 | `buildBacklinkIndex()`, `getBacklinks()` |
| TOC | 헤딩 추출 및 계층 구조 생성 |
| 설정 | `nuartz.config.ts`로 홈페이지, 타이틀 등 커스터마이즈 |

---

## 기술 스택

| 레이어 | 기술 |
|--------|------|
| 프레임워크 | Next.js 15 (App Router) |
| UI | shadcn/ui + Tailwind v4 |
| 마크다운 | unified + remark + rehype |
| Obsidian 파싱 | OFM (Quartz 플러그인 직접 활용) |
| 검색 | FlexSearch |
| 그래프 뷰 | D3.js |
| 패키지 매니저 | bun (monorepo) |
| 배포 | Vercel |

---

## 구조

```
nuartz/
├── packages/nuartz/     ← npm 패키지 (데이터 레이어)
│   └── src/
│       ├── markdown.ts  ← renderMarkdown()
│       ├── fs.ts        ← getAllMarkdownFiles(), buildFileTree()
│       ├── search.ts    ← buildSearchIndex()
│       └── backlinks.ts ← buildBacklinkIndex()
└── apps/web/            ← 공식 데모/문서 사이트 (Next.js)
```

---

## 시리즈

- [[01-Motivation|01. 출발점 - Quartz의 한계에서 시작된 여정]]
- [[02-Quartz-Internals|02. Quartz 플러그인 해부: 무엇을 재사용할 수 있나]]
- [[03-Vercel-Deployment|03. 첫 배포: 구현 내용과 Vercel에서 만난 것들]]
- [[04-Headless-and-Ecosystem|04. Headless 설계와 레포 생태계 재편]]
- [[05-Publishing|05. npm 배포: 버전 관리와 자동화]]

---

## 관련 프로젝트

- [[Projects/Blog-rag/00-Overview|blog-rag]] - Nuartz 기반 블로그를 RAG 대상으로 실험하는 프로젝트
