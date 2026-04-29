---
title: "LangFlow - 시각적 AI 워크플로우 빌더"
type: tool
tags:
  - ai
  - llm
  - workflow
  - no-code
  - low-code
  - open-source
  - python
  - rag
  - agent
  - pipeline
summary: "LangFlow는 드래그 앤 드롭으로 AI 워크플로우를 구성하는 MIT 라이선스 오픈소스 도구다(68.5k GitHub stars). LangChain 기반으로 RAG, 에이전트, 멀티에이전트 시스템을 시각적으로 설계하고 API로 배포할 수 있으나, 실제로는 low-code 수준의 학습 곡선이 존재한다."
sources:
  - content/Tools/LangFlow.md
created: 2026-04-26
updated: 2026-04-26
author: wiki-curator
draft: false
---

## Key Claims

- LangFlow는 LangChain 기반의 시각적 AI 워크플로우 빌더로, MIT 라이선스 오픈소스다(68.5k GitHub stars, 2025).[^1]
- 주요 기능: Visual Builder(드래그 앤 드롭), Playground(즉시 테스트), Multi-agent 오케스트레이션, API 배포, LangSmith/LangFuse 관찰 가능성 통합.[^1]
- Python 3.10~3.13 호환. 모든 주요 LLM, 벡터 DB 지원.[^1]
- 스타터 프로젝트 3가지: Basic Prompting, Vector Store RAG(Astra DB), Simple Agent(Calculator + URL 도구).[^1]
- 실사용 평가: "노코드를 표방하지만 실제로는 low-code 수준. n8n의 하위호환 같은 느낌이며 완성도와 안정성에서 개선 여지 많음."[^1]
- 경쟁 도구 비교:

| 도구 | 특징 | 최적 사용 사례 |
|------|------|--------------|
| LangFlow | LangChain 기반, AI 특화 | RAG, 에이전트 프로토타이핑 |
| Flowise | LangChain 기반, 직관적 UI | 간단한 AI 워크플로우 |
| n8n | 범용 자동화, 400+ 통합 | 비즈니스 프로세스 자동화 |
| Make | 기업용 안정성, 1000+ 통합 | 엔터프라이즈 자동화 |

[^1]

- LangFlow는 다중 시스템 API 통합이나 외부 웹훅 트리거에는 적합하지 않음. 그 경우 n8n이 더 적합.[^1]

## Connections

- [[misen]] - misen은 Python dict→dict Block 인터페이스로 AI 파이프라인을 구성하는 라이브러리로, LangFlow의 코드 기반 대안

## Footnotes

[^1]: content/Tools/LangFlow.md
