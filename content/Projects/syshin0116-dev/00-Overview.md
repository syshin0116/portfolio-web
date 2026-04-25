---
title: "syshin0116.dev 리팩토링 계획: 블로그와 포트폴리오 통합"
date: 2026-03-06
tags:
  - Projects
  - syshin0116-dev
  - blog-rag
  - Nuartz
  - Refactoring
  - Architecture
  - MoAI-ADK
draft: false
enableToc: true
description: 흩어져 있던 4개 레포를 3개로 재편하고, 블로그와 포트폴리오를 하나로 합치는 리팩토링 계획.
summary: "portfolio-web, portfolio-ai, nuartz, syshin0116.github.io 4개 레포를 syshin0116.dev + blog-rag + nuartz 3개로 재편한다. syshin0116.dev는 Nuartz 기반 블로그 + 포트폴리오 통합 사이트, blog-rag는 Modular RAG 백엔드다. MoAI-ADK의 SPEC-First 방식을 blog-rag 설계에 도입하기로 했다."
---
> [!info] 관련 글
> 레포 재편 결정 과정은 [[Projects/Nuartz/04-Headless-and-Ecosystem|Nuartz — Headless 설계와 레포 생태계 재편]]에서 먼저 다뤘다.

---

## 왜 다시 리팩토링인가

[[Projects/Nuartz/04-Headless-and-Ecosystem|Headless 설계 글]]에서 레포 재편 방향을 잡았다. 그 이후 실제로 작업에 들어가면서 생각이 더 구체화됐다.

기존 구조의 문제를 한 줄로 요약하면 이렇다: **블로그가 있는데 포트폴리오가 없고, 포트폴리오가 있는데 블로그가 없다.**

| 레포 | 역할 | 문제 |
|------|------|------|
| `syshin0116.github.io` | Quartz 블로그 | GitHub Pages 제약, Quartz UI 커스터마이징 한계 |
| `portfolio-web` | 포트폴리오 프론트 | 블로그 없음, blog-rag와 분리됨 |
| `portfolio-ai` | RAG 백엔드 | portfolio-web과 분리, 단일 검색 전략 |
| `nuartz` | 오픈소스 라이브러리 | 문제 없음 |

방문자 입장에서 블로그와 포트폴리오를 따로 봐야 하고, 관리하는 입장에서도 두 개의 프론트를 유지하는 건 비효율이다.

---

## 새 구조

```
nuartz          ← 오픈소스 라이브러리, 그대로 유지
syshin0116.dev  ← 블로그 + 포트폴리오 통합 (portfolio-web 리팩토링)
blog-rag        ← Modular RAG 백엔드 (portfolio-ai 재설계)
```

**이관 처리:**
- `syshin0116.github.io` → content/ 폴더 이사 후 archive
- `portfolio-web` → `syshin0116.dev`로 리팩토링
- `portfolio-ai` → `blog-rag`로 재설계

---

## syshin0116.dev 구조

Nuartz가 headless 데이터 레이어를 담당하고, syshin0116.dev는 그 위에 포트폴리오에 맞는 UI를 얹는다.

### 사이트 라우트

```
/                  ← 랜딩 + 채팅 히어로 (blog-rag 연동)
/blog              ← Nuartz 기반 블로그 (전체 글 목록)
/blog/[slug]       ← 개별 글
/projects          ← 프로젝트 타임라인
/projects/[id]     ← 프로젝트 상세
/about             ← 소개
```

### 홈 메인 = 채팅

홈에 blog-rag 연동 채팅을 전면에 두기로 했다.

이유가 두 가지다. 하나는 방문자가 "이 사람이 뭘 했는지" 자연스럽게 탐색할 수 있다. "SK Chemical 프로젝트 말해줘", "RAG 관련 글 있어?" 같은 질문으로 블로그와 프로젝트를 함께 찾게 된다. 다른 하나는 blog-rag 자체가 포트폴리오 프로젝트이기도 하다. 홈에서 바로 동작을 보여주는 게 어떤 설명보다 낫다.

### Nuartz 연동

```ts
import { getAllMarkdownFiles, renderMarkdown, buildSearchIndex } from 'nuartz'

// /blog 라우트: 전체 글 목록
const files = await getAllMarkdownFiles('./content')

// /blog/[slug]: 개별 글 렌더링
const { html, toc, frontmatter } = await renderMarkdown(file)
```

UI는 포트폴리오 전용으로 자유롭게 구성한다. Nuartz는 데이터만 준다.

---

## blog-rag 아키텍처

portfolio-ai를 그냥 rename하는 게 아니라 아키텍처를 완전히 재설계한다.

기존 portfolio-ai는 단일 검색 전략(벡터 검색)으로 모든 쿼리를 처리했다. 블로그에 들어오는 쿼리는 성격이 제각각이라 이걸로는 커버가 안 된다.

> [!note] blog-rag 상세 내용
> 왜 Modular RAG인지, 검색 모듈 설계, 평가 방식은 [[Projects/Blog-rag/00-Overview|blog-rag 개요]]와 [[Projects/Blog-rag/01-Motivation|blog-rag 동기]]에서 따로 다뤘다.

### 검색 모듈

| 모듈 | 방식 | 적합한 쿼리 |
|------|------|------------|
| **Semantic** | 벡터 임베딩 | "RAG가 뭐야?" |
| **Keyword** | BM25 | "context engineering" (영어 용어) |
| **Metadata** | 태그/날짜 필터 | "LangGraph 태그 달린 글 목록" |
| **File** | tool use 직접 읽기 | "nuartz 프로젝트 전체 내용" |
| **Graph** | wikilink 탐색 | "Nuartz랑 연결된 개념들" |

---

## 개발 방법론: SPEC-First 도입

이번 작업을 시작하면서 [BMAD Method, MoAI-ADK, GitHub Spec Kit 세 가지 AI 개발 방법론을 비교](../../../AI/2026-02-26-AI-개발-방법론-비교-BMAD-MoAI-ADK-Spec-Kit)했다.

결론은 이렇다: **도구는 Claude Code 그대로, 방법론은 MoAI-ADK의 SPEC-First 아이디어를 가져온다.**

MoAI-ADK를 풀로 설치하지 않는 이유:
- 1인 개인 프로젝트라 Agent 병렬 실행의 이점이 반감
- CLI, YAML, 에이전트 워크플로 학습 오버헤드가 지금 단계엔 크다
- Claude Code로 이미 잘 되고 있다

MoAI-ADK에서 빌려오는 것:
- **구현 전 SPEC 문서 먼저 작성** — 특히 blog-rag 모듈 인터페이스 정의

> [!tip]
> MoAI-ADK의 핵심 주장: "LLM의 성능은 이미 믿고 맡길 수준. 중요한 건 컨텍스트의 품질이다." SPEC 문서가 먼저 있으면 AI가 범위 밖으로 벗어날 여지가 줄어든다.

blog-rag에 적용하면 이렇게 된다:

```
blog-rag/
└── specs/
    ├── retrieval-module-interface.md  ← 구현 전 모듈 인터페이스 먼저 정의
    ├── evaluation-criteria.md         ← 평가 기준 먼저 설계
    └── pipeline-design.md             ← 파이프라인 흐름 먼저 그리기
```

syshin0116.dev는 UI 작업 위주라 SPEC 오버헤드가 필요 없다.

---

## 로드맵

### Phase 1 — 기반 정리

**syshin0116.dev**
- 레포 rename (portfolio-web → syshin0116.dev)
- 사이트 구조 재편 (라우트 구성)
- Nuartz 연동, `/blog` 섹션 구현
- 기존 `projects.ts` 데이터 이식
- 홈 채팅 UI (일단 현재 portfolio-ai API 연결)

**blog-rag**
- 레포 rename (portfolio-ai → blog-rag)
- SPEC 문서 작성 (모듈 인터페이스, 평가 기준)
- Modular RAG 아키텍처 구현 (Semantic 먼저)
- LangSmith 연동
- 배포 옵션 리서치

### Phase 2 — 통합

- blog-rag API 교체 (syshin0116.dev 채팅 연결)
- Supabase 세션 연동 (채팅 히스토리)

### Phase 3 — 평가 & 포스팅

- 평가 데이터셋 구축
- 모듈 조합 실험 (LangSmith 정량 비교)
- 실험 결과 블로그 시리즈

### 우선순위

```
1순위  syshin0116.dev 구조 + Nuartz 블로그 연동
2순위  blog-rag SPEC 문서 + Semantic 기본 구현 (병렬)
3순위  blog-rag 배포 결정 + syshin0116.dev 채팅 연결
4순위  나머지 RAG 모듈 + LangSmith 평가
```

---

## 시리즈

- [[00-Overview|00. 리팩토링 계획 (현재 글)]]
- *(진행되는 대로 추가)*

---

## 관련 프로젝트

- [[Projects/Nuartz/00-Overview|Nuartz]] — headless 데이터 레이어
- [[Projects/Blog-rag/00-Overview|blog-rag]] — Modular RAG 백엔드
