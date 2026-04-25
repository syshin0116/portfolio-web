---
title: "blog-rag 프로젝트 개요: 블로그 기반 Modular RAG 시스템"
date: 2026-03-06
tags:
  - Projects
  - blog-rag
  - RAG
  - Modular-RAG
  - LangGraph
  - Python
  - AI
draft: false
enableToc: true
description: 개인 블로그를 지식 베이스로 삼아 Modular RAG 아키텍처를 구축하고, 다양한 검색 모듈 조합을 실험하는 프로젝트.
summary: "Modular RAG 아키텍처로 검색 전략을 갈아끼울 수 있게 만들고, 시맨틱/키워드/메타데이터/파일/그래프 기반 검색 모듈을 조합해 내 블로그에서 어떤 조합이 가장 잘 동작하는지 실험한다. LangSmith로 전 과정을 추적하고, 체계적인 평가 기준을 만들어 조합 간 결과를 정량 비교하는 것까지 포함한다."
---
---

## 프로젝트 소개

**blog-rag**는 내 개인 블로그([[Projects/Nuartz/00-Overview|Nuartz]] 기반)를 지식 베이스로 삼아 Modular RAG 아키텍처를 구축하고 다양한 검색 전략을 실험하는 프로젝트다.

두 가지 축으로 프로젝트를 구성한다.

첫 번째는 **검색 모듈의 교체 가능성**이다. 시맨틱 검색, 키워드 검색, 메타데이터 필터링, 파일 직접 접근, 그래프 탐색을 독립적인 모듈로 구현하고 조합할 수 있게 만든다.

두 번째는 **평가**다. 모듈 조합 간 결과를 체감이 아닌 수치로 비교하려면 평가 기준과 데이터셋이 먼저 있어야 한다. LangSmith로 파이프라인 전 과정을 추적하고, 평가 지표를 설계해 조합별 품질을 정량 비교한다.

![[rag-pipeline.png]]

- GitHub: [syshin0116/blog-rag](https://github.com/syshin0116/blog-rag)

---

## 검색 모듈

| 모듈 | 방식 | 특징 |
|------|------|------|
| **Semantic** | 벡터 임베딩 유사도 | 의미 기반, 표현이 달라도 검색 |
| **Keyword** | BM25 / TF-IDF | 정확한 용어 매칭, 한국어 혼용에 강점 |
| **Metadata** | 태그, 카테고리, 날짜 필터 | "AI 관련 최근 글" 같은 구조적 쿼리 |
| **File** | tool use로 파일 직접 읽기 | 특정 문서 전체 컨텍스트 필요할 때 |
| **Graph** | wikilink 그래프 탐색 | 연결된 노트 탐색, 연관 개념 확장 |

조합 예시:
- `Semantic + Keyword` → Hybrid Search (RRF로 결과 합산)
- `Metadata → Semantic` → 필터링 후 유사도 검색
- `Graph → File` → 연결 노트 발견 후 전문 읽기

---

## 기술 스택

| 레이어 | 기술 |
|--------|------|
| 언어 | Python |
| 오케스트레이션 | LangGraph + deepagents |
| 임베딩 | OpenAI `text-embedding-3-small` |
| 벡터 DB | 미정 (Chroma / pgvector / Qdrant) |
| 키워드 검색 | BM25 (rank-bm25) |
| 그래프 DB | 미정 (Neo4j / NetworkX) |
| LLM | Claude (claude-sonnet-4-6) |
| Observability & Evaluation | LangSmith |
| 서버 | FastAPI |
| 배포 | 미정 |

---

## 구조

> [!note] 구조 미정
> 아직 설계 단계. 구체적인 디렉토리 구조는 구현을 시작하면서 결정할 예정이다.

---

## 프론트엔드 연동

blog-rag는 백엔드 서버로만 존재하고, 실제 사용자는 **syshin0116.dev** (개인 블로그 + 포트폴리오)를 통해 접근한다.

```
syshin0116.dev (Next.js)
  └── /chat 또는 사이드 패널
        ↓ API 호출
  blog-rag (FastAPI)
        ↓ RAG 파이프라인
  블로그 콘텐츠 기반 답변
        ↓ 스트리밍 응답
  사용자
```

프론트엔드 UI 구성은 아직 고민 중이다. 전용 채팅 페이지로 만들지, 노트 페이지 옆에 사이드 패널로 붙일지 결정되지 않았다.

> [!note]
> syshin0116.dev 프로젝트는 별도로 다룰 예정이다.

---

## 시리즈

- [[01-Motivation|01. 왜 블로그를 RAG 대상으로, 왜 Modular RAG인가]]
- *(구현 및 실험 결과는 진행되는 대로 추가)*

---

## 관련 프로젝트

- [[Projects/Nuartz/00-Overview|Nuartz]] — 블로그 콘텐츠를 서빙하는 Next.js 라이브러리
- syshin0116.dev — blog-rag를 연동하는 프론트엔드 *(포스트 예정)*
