---
title: TeddyNote - Agentic RAG 세미나
date: 2024-09-07
tags:
- rag
- agent
- llm
- langgraph
- agentic-rag
- semantic-search
- teddynote
draft: false
enableToc: true
description: Agentic RAG의 개념과 구현 방법을 다룬 TeddyNote 세미나 정리
summary: "TeddyNote의 Agentic RAG 세미나 내용을 정리한 노트이다. Agent의 정의와 경계, Tool Calling의 개념, RAG와 Agent의 결합인 Agentic RAG의 특징, LangGraph를 활용한 복잡한 워크플로우 구현, 그리고 실제 구현 예시와 사례 연구를 포함한다. Agent가 도구를 능동적으로 선택하고 활용하여 더 정확한 답변을 생성하는 과정을 다룬다."
published: 2024-09-07
modified: 2024-09-07
---
테디노트 유튜브 링크 [https://www.youtube.com/watch?v=J610NhUrj-s&t=2236s](https://www.youtube.com/watch?v=J610NhUrj-s&t=2236s)


## Agent란?
- 경계가 명확하지 않아 쉽게 정의 내리기 어렵다
- Tool을 사용한다면 Agent인가?

		→ Tool Calling이 아니더라도 Tool이지 않나?
		- ex) RAG를 Tool Calling으로 호출하지 않아도 RAG는 도구지 않나?

![](https://i.imgur.com/tbTh6Vg.png)

### Agentic 함이란?
- 뒤에 일어날 많은 로직들을 어떻게, 어떤 순서로 실행할지를 LLM에게 맡김

### Tips

- 계획을 짜주는 LLM을 둠으로써 전체 로직 컨트롤
	- 두지 않을 시, Agent끼리 원하지 않는 티키타카 현상 발생


### Agent Frameworks

![](https://i.imgur.com/pihyqzQ.png)

최근에 N8N(?) - No Code tool 이지만 생각보다 Customizing을 많이 할 수 있다

> LangGraph 왜 배웠지 회의감 든다고 하신다ㅋㅋ


그럼에도 코드가 필요한 이유가 존재:
- 입출력 설정
- 기존 시스템과 결합



### CrewAI
- LangChain 기반 프레임워크 → 기존에 쓰던 LangChain과 호환성이 높음
- AutoGen이나 LangGraph에 비해 Code를 쓴다기 보다 명세서를 작성하는 느낌이 큼(반 노코드 툴)


### AutoGen
- Microsoft 제작
- 