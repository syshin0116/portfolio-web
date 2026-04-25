---
title: Agent 사용 RAG+Tavily
date: 2024-05-05
tags:
- rag
- agent
- langchain
- tavily
- llm
- pdf-search
- information-retrieval
draft: false
enableToc: true
description: LangChain Agent와 Tavily 검색 엔진을 활용한 고급 RAG 시스템 구현 방법과 활용 사례 분석
summary: "LangChain Agent와 Tavily 검색 엔진을 결합한 RAG 시스템은 PDF 검색, 웹 검색 등 다양한 정보 소스를 통합하여 더 정확하고 신뢰할 수 있는 응답을 생성한다. 에이전트 기반 접근 방식은 복잡한 질의에 대해 단계적 추론과 정보 탐색이 가능하며, 특히 법률, 의학 등 전문 도메인에서 뛰어난 성능을 보인다."
published: 2024-05-05
modified: 2024-05-05
---
## 개요

RAG(Retrieval-Augmented Generation) 시스템은 LLM의 환각 현상(Hallucination)을 줄이고 최신 정보를 반영할 수 있는 효과적인 방법이다. 여기에 Agent 기반 접근 방식을 도입하면 더욱 강력한 정보 검색 및 추론 시스템을 구축할 수 있다. 이 문서에서는 LangChain Agent와 Tavily 검색 엔진을 결합한 고급 RAG 시스템 구현 방법과 실제 활용 사례를 살펴본다.

[[LLM Chain Chatbot + RAG]]와 [[RAG+Groq]]에서 다룬 기본적인 RAG 시스템보다 더 발전된 접근 방식으로, 복잡한 질의에 대한 정교한 응답을 생성할 수 있다.

---

## Agent 기반 RAG의 개념과 구조

### Agent란 무엇인가?

Agent는 주어진 목표를 달성하기 위해 환경과 상호작용하며 자율적으로 의사결정을 수행하는 AI 시스템이다. LangChain에서 Agent는 다음과 같은 특징을 가진다:

1. **도구 사용 능력**: 다양한 도구(검색, 계산, 코드 실행 등)를 활용할 수 있음
2. **단계적 추론**: 복잡한 문제를 작은 단계로 나누어 해결
3. **자율적 의사결정**: 어떤 도구를 언제 사용할지 스스로 결정

### Tavily 검색 엔진

Tavily는 AI에 최적화된 검색 API로, 다음과 같은 특징을 가진다:

- 웹 검색 최적화: LLM과의 통합을 위해 설계된 검색 결과 제공
- 다양한 검색 모드: 키워드 검색, 시맨틱 검색 등 지원
- 컨텍스트 인식: 질문의 맥락을 이해하여 관련성 높은 결과 제공

### Agent 기반 RAG 시스템의 구조

Agent 기반 RAG 시스템은 다음과 같은 구성 요소로 이루어진다:

1. **LLM**: 시스템의 두뇌 역할을 하는 언어 모델
2. **도구(Tools)**: PDF 검색, 웹 검색 등 다양한 정보 소스에 접근하는 도구
3. **Agent 프레임워크**: 도구와 LLM을 연결하고 의사결정을 조율
4. **메모리 시스템**: 대화 이력과 중간 결과를 저장

---

## 구현 방법

### 환경 설정

```python
# 필요한 라이브러리 설치
!pip install langchain langchain-openai tavily-python

# API 키 설정
import os
os.environ["OPENAI_API_KEY"] = "your-openai-api-key"
os.environ["TAVILY_API_KEY"] = "your-tavily-api-key"
```

### 기본 컴포넌트 설정

```python
from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_react_agent
from langchain_community.tools.tavily_search import TavilySearchResults
from langchain_community.tools import PDFSearchTool

# LLM 설정
llm = ChatOpenAI(model="gpt-4", temperature=0)

# 도구 설정
web_search = TavilySearchResults(max_results=3)
pdf_search = PDFSearchTool(pdf_directory="documents/")

tools = [web_search, pdf_search]
```

### Agent 생성 및 실행

```python
from langchain.prompts import PromptTemplate

# 프롬프트 템플릿 설정
prompt_template = """
당신은 사용자의 질문에 정확하고 도움이 되는 답변을 제공하는 AI 비서입니다.
사용자의 질문에 답변하기 위해 제공된 도구를 사용하세요.

{tools}

사용할 수 있는 도구:
{tool_names}

질문: {input}
{agent_scratchpad}
"""

prompt = PromptTemplate.from_template(prompt_template)

# Agent 생성
agent = create_react_agent(
    llm=llm,
    tools=tools,
    prompt=prompt
)

# Agent 실행기 생성
agent_executor = AgentExecutor(
    agent=agent,
    tools=tools,
    verbose=True,
    handle_parsing_errors=True
)
```

---

## 사용 예시

다음은 법률 정보 검색에 Agent 기반 RAG 시스템을 활용한 예시다:

### 외국인 고용보험 정보 검색

```python
response = agent_executor.invoke({
    "input": "외국인에 대한 고용보험법에 대해 설명해줘"
})
```

**실행 결과:**

```
> Entering new AgentExecutor chain...

Invoking: `pdf_search` with `{'query': '외국인 고용보험'}`

주민등록번호 또는 외국인등록번호가 포함된 자료를 처리할 수 있다. <개정 2012. 7. 10., 2016. 7. 19., 2017. 3. 27.,
2019. 6. 25., 2020. 12. 8., 2021. 6. 8., 2021. 12. 31., 2023. 6. 27.>
1. 법 제10조제1항제3호 단서 및 이 영 제3조의2에 따른 별정직ㆍ임기제 공무원의 고용보험 가입 또는 탈퇴에 관한
사무 
1의2. 다음 각 목에 해당하는 사람의 고용보험 가입에 관한 사무
가. 법 제10조의2제1항에 따른 외국인근로자 
나. 법 제10조의2제2항 및 이 영 제3조의3에 따른 근로계약 체결 외국인, 외국인예술인 및 외국인노무제공자 
...
```

이 예시에서 Agent는 먼저 PDF 검색 도구를 사용하여 외국인 고용보험에 관한 정보를 찾았다. 검색 결과에서 관련된 법률 조항과 규정을 찾아 사용자 질문에 대한 응답을 구성했다.

> [!Note]
> Agent의 단계적 추론 과정이 `AgentExecutor` 실행 로그를 통해 투명하게 표시되어, 어떤 정보를 어떻게 찾았는지 확인할 수 있다.

---

## 고급 활용 방법

### 다양한 도구 통합

Agent 기반 RAG 시스템은 다양한 도구를 통합하여 더 강력한 정보 검색 능력을 가질 수 있다:

```python
from langchain_community.tools import YouTubeSearchTool
from langchain_community.tools.sql_database.tool import QuerySQLDataBaseTool

# 유튜브 검색 도구
youtube_search = YouTubeSearchTool()

# 데이터베이스 쿼리 도구
db_query = QuerySQLDataBaseTool(db=db)

# 도구 확장
tools = [web_search, pdf_search, youtube_search, db_query]
```

### 병렬 정보 검색

여러 정보 소스에서 동시에 검색을 수행하여 성능을 향상시킬 수 있다:

```python
from langchain.agents import AgentExecutor, create_openai_functions_agent
from langchain.tools.render import format_tool_to_openai_function

# 도구를 OpenAI 함수 형식으로 변환
functions = [format_tool_to_openai_function(t) for t in tools]

# 병렬 실행 지원 Agent 생성
agent = create_openai_functions_agent(
    llm=ChatOpenAI(model="gpt-4", temperature=0, functions=functions),
    tools=tools,
    prompt=prompt
)

# 병렬 실행 설정으로 Agent 실행기 생성
agent_executor = AgentExecutor(
    agent=agent,
    tools=tools,
    verbose=True,
    handle_parsing_errors=True,
    max_iterations=5,
    max_execution_time=30,
    early_stopping_method="generate"
)
```

---

## 응용 분야

Agent 기반 RAG 시스템은 다음과 같은 다양한 분야에서 활용될 수 있다:

1. **법률 자문**: 법률 문서와 판례를 검색하여 법적 질문에 대한 정보 제공
2. **의료 정보 검색**: 의학 논문과 임상 가이드라인을 분석하여 의료 질문 답변
3. **교육 지원**: 학습 자료와 교육 콘텐츠를 검색하여 학생들의 질문에 답변
4. **기술 지원**: 기술 문서와 포럼을 검색하여 개발자 질문 해결
5. **연구 보조**: 학술 논문과 데이터를 검색하여 연구자 지원

특히 [[문서(pdf 등) 내 시각 자료와 텍스트의 추출 및 활용 연구]]와 결합하면 이미지와 텍스트를 모두 포함한 문서에서도 효과적인 정보 추출이 가능하다.

---

## 결론

Agent 기반 RAG 시스템은 단순한 정보 검색을 넘어 복잡한 추론과 의사결정이 필요한 작업에서 강력한 성능을 발휘한다. LangChain의 Agent 프레임워크와 Tavily 검색 엔진을 결합함으로써, 더 정확하고 신뢰할 수 있는 정보 검색 시스템을 구축할 수 있다.

이 접근 방식은 [[LangChain]], [[RAG+Groq]], [[LLM Chain Chatbot + RAG]]에서 다룬 기존 RAG 시스템을 확장하여, 더 복잡한 질의에 대응할 수 있는 지능형 시스템으로 발전시킨다. 향후 도구의 다양화와 Agent의 추론 능력 향상을 통해 더욱 발전된 정보 검색 시스템을 구현할 수 있을 것이다. 