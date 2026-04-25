---
title: LangGraph
date: 2024-03-06
tags:
- ai
- deep-learning
- langchain
- langgraph
- agent
- llm
draft: false
enableToc: true
description: LangGraph 라이브러리의 개념과 다중 에이전트 협업 시스템 구현 방법 설명
summary: "LangGraph는 LangChain 위에 구축된 상태 유지형 다중 에이전트 애플리케이션을 구축하기 위한 라이브러리다. 주요 특징은 LLM 애플리케이션에 순환(cycle) 기능을 추가하는 것으로, 이는 에이전트가 다음 행동을 결정하는 반복적 프로세스에 중요하다. 다중 에이전트 협업 모델에서는 각 작업이나 도메인에 전문화된 에이전트를 할당하여 \"분할 정복\" 방식으로 복잡한 문제를 해결한다."
published: 2024-03-06
modified: 2024-03-06
---
## 개요

LangGraph는 LangChain에서 개발한 라이브러리로, 상태 유지 기능과 다중 에이전트 시스템을 구축할 수 있는 프레임워크다. 이 문서에서는 LangGraph의 기본 개념과 다중 에이전트 협업 모델 구현 방법에 대해 알아본다.

### 참고자료
- **공식 문서**: [LangGraph 문서](https://python.langchain.com/docs/langgraph)
- **GitHub**: [LangGraph 리포지토리](https://github.com/langchain-ai/langgraph)
- **유튜브 튜토리얼**: [TeddyNote - LangGraph 소개](https://www.youtube.com/watch?v=1scMJH93v0M)

---

## LangGraph 기본 개념

LangChain 공식 홈페이지에서는 LangGraph를 다음과 같이 정의한다:

> LangGraph는 LLM을 활용한 상태 유지형 다중 에이전트 애플리케이션을 구축하기 위한 라이브러리로, LangChain 위에 구축되었다. LangChain Expression Language를 확장하여 여러 체인(또는 액터)을 순환적인 방식으로 여러 계산 단계에 걸쳐 조정할 수 있는 기능을 제공한다. Pregel과 Apache Beam에서 영감을 받았으며, 현재 인터페이스는 NetworkX에서 영감을 받았다.

### 핵심 특징
- **순환(Cycles) 지원**: LLM 애플리케이션에 순환 기능을 추가한다.
- **비 DAG 프레임워크**: 단순 방향성 비순환 그래프(DAG)가 아닌, 순환이 가능한 구조를 제공한다.
- **에이전트 행동 모델링**: 다음 행동을 결정하기 위해 LLM을 반복적으로 호출하는 패턴에 적합하다.

> [!Note]
> DAG(Directed Acyclic Graph) 기능만 필요한 경우 LangChain Expression Language를 직접 사용하는 것이 권장된다.

---

## 다중 에이전트 협업 모델

LangGraph의 가장 강력한 활용 사례 중 하나는 다중 에이전트 협업 시스템 구축이다.

![다중 에이전트 협업 아키텍처](https://i.imgur.com/CUNZuok.png)

### 분할 정복 접근법
다중 에이전트 시스템에서는 "분할 정복(divide-and-conquer)" 전략을 사용한다:

1. 각 작업이나 도메인에 특화된 전문 에이전트 생성
2. 작업을 적절한 '전문가' 에이전트에게 라우팅
3. 에이전트 간 협업을 통한 문제 해결

### 에이전트 유형 예시
- **검색 에이전트**: 정보 검색에 특화
- **차트 생성 에이전트**: 데이터 시각화 담당
- **코드 작성 에이전트**: 프로그래밍 작업 수행

### 구현 참고 자료
- 연구 논문: [AutoGen: Enabling Next-Gen LLM Applications via Multi-Agent Conversation](https://arxiv.org/abs/2308.08155)
- 샘플 노트북: [Multi-Agent Collaboration Example](https://github.com/langchain-ai/langgraph/blob/main/examples/multi_agent/multi-agent-collaboration.ipynb)

---

## LangGraph 구현 방법

LangGraph를 사용한 다중 에이전트 시스템 구현 방법에 대해 간략히 살펴본다.

### 기본 구현 단계
1. 각 에이전트 역할 및 능력 정의
2. 에이전트 간 상호작용 그래프 설계
3. 상태 관리 및 전이 함수 구현
4. 메시지 라우팅 및 의사결정 로직 설정

### 코드 예시
```python
from langgraph.graph import Graph, StateGraph
from langchain.agents import Tool
from langchain.chat_models import ChatOpenAI

# 1. 상태 정의
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]
    next_agent: str

# 2. 노드 정의 (각 에이전트)
def search_agent(state):
    # 검색 에이전트 로직
    return {"messages": [search_result], "next_agent": "analyze"}

def analyze_agent(state):
    # 분석 에이전트 로직
    return {"messages": [analysis_result], "next_agent": "decide"}

# 3. 라우팅 함수
def router(state):
    return state["next_agent"]

# 4. 그래프 구성
workflow = StateGraph(AgentState)
workflow.add_node("search", search_agent)
workflow.add_node("analyze", analyze_agent)
workflow.add_node("decide", decide_agent)

# 5. 에지 추가
workflow.add_edge("search", router)
workflow.add_edge("analyze", router)
workflow.add_edge("decide", router)

# 6. 컴파일 및 실행
app = workflow.compile()
```

---

## 결론

LangGraph는 LangChain 생태계의 강력한 확장으로, 순환 구조와 상태 유지 기능을 통해 복잡한 다중 에이전트 시스템 구축을 가능하게 한다. 특히 분할 정복 접근법을 통한 다중 에이전트 협업 모델은 복잡한 문제를 효과적으로 해결하는 방법을 제공한다.

LangGraph에 대해 더 자세히 알아보려면 [[LangChain]], [[Agent 사용 RAG+Tavily]], [[LLM Chain Chatbot + RAG]] 문서를 참조하자. 이러한 기술들을 결합하면 더욱 강력한 AI 애플리케이션을 구축할 수 있다. 