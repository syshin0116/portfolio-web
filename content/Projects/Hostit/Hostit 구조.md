---
title: Hostit 구조
date: 2025-05-04
tags:
- project
- HostIt
- architecture
- file-structure
- development
draft: false
enableToc: true
description: Hostit 프로젝트의 파일 구조와 아키텍처 설계에 대한 상세 가이드
summary: "Hostit 프로젝트의 파일 구조와 아키텍처 설계에 대한 상세 가이드"
published: 2025-05-04
modified: 2025-05-04
---
### Hostit 구조
src/
├── lib/
│   ├── core/                        👈 핵심 기능
│   │   ├── store.ts                 👈 단일 스토어
│   │   ├── config.ts                👈 전역 설정 정의
│   │   └── types/                   👈 공통 타입 정의
│   │       ├── index.ts             👈 공통 타입 내보내기
│   │       ├── chat.ts              👈 채팅 관련 타입
│   │       └── api.ts               👈 API 관련 타입
│   │
│   ├── mcp/                         👈 MCP 기능
│   │   ├── client.ts                👈 MCP 클라이언트
│   │   ├── registry.ts              👈 도구 등록 관리
│   │   ├── connector.ts             👈 도구 연결 관리 
│   │   ├── status.ts                👈 연결 상태 관리 (신규)
│   │   ├── types.ts                 👈 MCP 관련 타입
│   │   └── adapters/                👈 다양한 도구 어댑터 (신규)
│   │       ├── stdio.ts             👈 stdio 어댑터
│   │       └── sse.ts               👈 SSE 어댑터
│   │
│   ├── ai/                          👈 AI 관련
│   │   ├── models/                  👈 모델 관리
│   │   │   ├── index.ts             👈 모델 공통 인터페이스
│   │   │   ├── anthropic.ts         👈 Anthropic 모델
│   │   │   └── openai.ts            👈 OpenAI 모델 (신규)
│   │   │
│   │   ├── agents/                  👈 에이전트 관리
│   │   │   ├── index.ts             👈 에이전트 공통 코드
│   │   │   ├── react.ts             👈 React 에이전트
│   │   │   └── plan-execute.ts      👈 Plan-Execute 에이전트
│   │   │
│   │   ├── tools/                   👈 AI 도구 (기존 langchain/tools)
│   │   │   ├── index.ts
│   │   │   └── web-search.ts
│   │   │
│   │   └── integration/             👈 MCP + AI 통합
│   │       ├── registry.ts          👈 도구 등록
│   │       └── tool-provider.ts     👈 도구 제공자
│   │
│   ├── auth/                        👈 인증 관련 (신규)
│   │   ├── keys.ts                  👈 API 키 관리
│   │   └── session.ts               👈 세션 관리
│   │
│   └── utils/                       👈 유틸리티
│       ├── api.ts                   👈 API 통신
│       ├── env.ts                   👈 환경 관련
│       ├── logger.ts                👈 로깅 (신규)
│       └── validation.ts            👈 유효성 검사 (신규)
