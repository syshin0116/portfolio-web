---
title: "Moonlight AI 논문 리더"
type: tool
tags:
  - ai
  - research
  - paper-reading
  - chrome-extension
  - rag
  - llm
  - productivity
summary: "Moonlight는 학술 논문 PDF에 AI를 붙여주는 크롬 확장 프로그램이다. 3줄 요약, 자동 하이라이트(기여점/방법론/결과), 드래그 설명, 스마트 인용, Scholar Deep Search(RAG 기반 관련 논문 추천) 기능을 제공하며, 한국 AI 회사 Corca가 개발했다."
sources:
  - content/Tools/2026-03-03-Moonlight-AI-논문-리더-활용법.md
created: 2026-04-26
updated: 2026-04-26
author: wiki-curator
draft: false
---

## Key Claims

- Moonlight는 arXiv, Semantic Scholar, PubMed 등 웹에서 열리는 논문 PDF라면 어디서든 작동하는 크롬/엣지 확장 프로그램이다.[^1]
- 핵심 기능: 3줄 요약 + 방법론 요약, 색상별 자동 하이라이트(노벨티/방법론/결과), 드래그 선택 즉시 설명, 스마트 인용 팝업, AI 채팅, 수식 LaTeX 복사, 어노테이션.[^1]
- 플랜: Free(3개/주), Pro(무제한), Premium. 사용 가능 모델: Gemini 2.5 Flash Lite/Flash, Gemini 3 Flash, GPT-5 nano/mini.[^1]
- 논문 스크리닝 워크플로우(10분): 자동 하이라이트 확인(2분) → 3줄 요약(1분) → AI 채팅으로 가치 판단(5분) → 인용 논문 체크(2분).[^1]
- Scholar Deep Search(v1.3.0+): 라이브러리 폴더 내 논문을 벡터 임베딩으로 인덱싱하고 유사 논문을 추천하는 RAG 패턴.[^1]
- Citation 탭(v1.6.0+): 해당 논문이 인용한 논문 / 해당 논문을 인용한 논문의 계보를 시각화.[^1]
- 개발사: 한국 AI B2B SaaS 회사 Corca(TypeScript + Python). 이전 오픈소스 프로젝트 EVAL(LangChain 기반 에이전트)의 기술 경험이 기반.[^1]
- 내부 추정 아키텍처: Manifest V3 Chrome Extension + 학술 논문 특화 PDF 파서(다단 레이아웃, 수식 LaTeX 변환) + LLM 레이어(OpenAI API) + 벡터 DB.[^1]

## Examples / Code

논문 이해를 위한 AI 채팅 질문 패턴:

```
"이 논문의 핵심 contribution이 뭐야?"
"기존 방법들과 비교해서 어떤 점이 다른 거야?"
"이 방법의 한계나 약점은 뭐야?"
"이 논문 이해하려면 뭘 알아야 해?"
"이 방법을 [내 업무 상황]에 적용하면 어떻게 될까?"
```

추정 내부 구조:

```
[Extension]
  ├── Content Script  — PDF 감지, 사이드바 DOM 주입, 텍스트 선택 이벤트
  ├── Service Worker  — 백엔드 API 프록시, 인증 토큰
  └── Sidebar UI      — React/Preact 기반

[Corca 백엔드] → [OpenAI API]
  ↑
구조화된 논문 JSON 캐시 + 벡터 임베딩 DB
```

## Footnotes

[^1]: content/Tools/2026-03-03-Moonlight-AI-논문-리더-활용법.md
