---
title: LLM Chain Chatbot + RAG
date: 2024-04-11
tags:
- llm
- langchain
- chatbot
- rag
- nlp
- conversational-ai
draft: false
enableToc: true
description: LangChain의 ConversationalRetrievalChain을 활용한 대화형 RAG 시스템 구현 방법과 주요 기능
  설명
summary: "ConversationalRetrievalChain은 LangChain에서 제공하는 대화형 정보 검색 시스템으로, 사용자 질의와 대화 이력을 바탕으로 관련 문서를 검색하고 적절한 응답을 생성한다. 이 시스템은 질문 이해, 정보 검색, 컨텍스트 유지, 응답 생성의 단계를 통합하여 자연스러운 대화형 정보 제공을 가능하게 한다."
published: 2024-04-11
modified: 2024-04-11
---
## 개요

대화형 시스템에서 사용자 질문에 대한 정확하고 신속한 응답은 필수적이다. `ConversationalRetrievalChain`은 이러한 요구를 충족시키기 위해 개발된 핵심 컴포넌트로, 복잡한 자연어 처리 알고리즘과 데이터 검색 기술을 통합하여 사용자 질문에 가장 관련성 높은 정보를 제공한다. 이 체인은 다양한 소스에서 데이터를 동적으로 추출하고 분석하여, 빠르고 정확한 대답을 가능하게 한다.

[[RAG+Groq]]와 [[Agent 사용 RAG+Tavily]]와 같은 다른 RAG 구현 방식과 비교할 때, ConversationalRetrievalChain은 대화 컨텍스트를 유지하는 데 특화되어 있다.

---

## ConversationalRetrievalChain 기본 구조

ConversationalRetrievalChain은 다음과 같은 주요 매개변수를 사용한다:

- **chat_history**: 이전 대화 기록(메시지 리스트)
- **new_question**: 사용자의 새로운 질문

이 체인은 질문에 대한 답변을 반환하며, 내부적으로 여러 하위 체인을 조합하여 최종 결과를 생성한다.

### 기능 및 구조

`ConversationalRetrievalChain`은 다음과 같은 여러 구성 요소로 이루어져 있다:

1. **질문 이해**: 사용자의 질문을 분석하고 이해하는 첫 단계로, NLP 기술을 활용하여 질문의 핵심 키워드와 의도를 파악
2. **정보 검색**: 분석된 키워드와 의도를 바탕으로 데이터베이스나 인터넷과 같은 다양한 정보 소스에서 관련 정보를 검색
3. **정보 가공 및 최적화**: 검색된 정보를 사용자가 이해하기 쉬운 형태로 가공하며, 불필요한 정보를 제거하고 중요한 정보를 강조
4. **응답 생성**: 최종적으로 가공된 정보를 바탕으로 사용자에게 응답을 제공한다. 이 과정에서도 자연어 생성 기술을 활용하여 자연스러운 대화형 응답을 만들어낸다.

---

## 구현 방법

### 환경 설정

ConversationalRetrievalChain을 사용하기 위해서는 먼저 필요한 환경을 설정해야 한다:

1. **필요 라이브러리 설치**:
```bash
pip install langchain langchain_openai
```

2. **API 키 설정**:
```python
import os
os.environ["OPENAI_API_KEY"] = "your-api-key"
```

### 데이터 소스 연결

정보 검색을 위한 데이터 소스와의 연결을 구성한다:

1. **벡터 저장소 설정**:
```python
from langchain.vectorstores import Chroma
from langchain.embeddings import OpenAIEmbeddings

# 문서에서 임베딩 생성
embeddings = OpenAIEmbeddings()
vectorstore = Chroma.from_documents(documents, embeddings)
```

2. **검색기(Retriever) 설정**:
```python
retriever = vectorstore.as_retriever(
    search_type="similarity",
    search_kwargs={"k": 3}
)
```

### 파라미터 설정

다양한 파라미터를 사용자의 요구에 맞게 설정한다:

```python
from langchain.chains import ConversationalRetrievalChain
from langchain.chat_models import ChatOpenAI

llm = ChatOpenAI(temperature=0.7, model="gpt-3.5-turbo")
chain = ConversationalRetrievalChain.from_llm(
    llm=llm,
    retriever=retriever,
    return_source_documents=True,
    verbose=True
)
```

> [!Note]
> `temperature` 값을 조정하여 응답의 창의성과 일관성 사이의 균형을 맞출 수 있다. 높은 값은 더 창의적인 응답을, 낮은 값은 더 일관된 응답을 생성한다.

---

## 고급 사용 예시

더 복잡한 ConversationalRetrievalChain 구현을 위한 코드 예시:

```python
from langchain.chains import (
    StuffDocumentsChain, LLMChain, ConversationalRetrievalChain
)
from langchain_core.prompts import PromptTemplate
from langchain_community.llms import OpenAI

# 문서 결합 체인 설정
combine_docs_chain = StuffDocumentsChain(...)
vectorstore = ...
retriever = vectorstore.as_retriever()

# 독립적인 질문 생성 방법 제어
# 'chat_history'와 'question'을 입력 변수로 사용해야 함
template = (
    "Combine the chat history and follow up question into "
    "a standalone question. Chat History: {chat_history}"
    "Follow up question: {question}"
)
prompt = PromptTemplate.from_template(template)
llm = OpenAI()
question_generator_chain = LLMChain(llm=llm, prompt=prompt)

# 최종 체인 설정
chain = ConversationalRetrievalChain(
    combine_docs_chain=combine_docs_chain,
    retriever=retriever,
    question_generator=question_generator_chain,
)
```

이 예시에서는 사용자 정의 질문 생성기를 통해 대화 이력과 후속 질문을 결합하여 독립적인 질문을 생성한 후, 이를 기반으로 문서를 검색하고 최종 응답을 생성한다.

---

## 활용 사례

ConversationalRetrievalChain은 다음과 같은 다양한 응용 분야에서 활용될 수 있다:

1. **고객 지원 챗봇**: 기업 문서나 FAQ를 기반으로 고객 질문에 정확하게 답변
2. **교육용 튜터 시스템**: 학습 자료를 바탕으로 학생들의 질문에 맞춤형 답변 제공
3. **연구 보조 도구**: 방대한 연구 논문이나 보고서에서 관련 정보를 신속하게 검색하고 답변
4. **내부 지식 관리 시스템**: 기업 내부 문서와 지식을 효율적으로 검색하고 활용

> [!Note]
> 실제 구현 시 도메인 특화 프롬프트 설계와, 검색된 문서의 질을 평가하는 메커니즘을 추가하면 더 효과적인 시스템을 구축할 수 있다.

## 결론

ConversationalRetrievalChain은 LangChain 생태계에서 대화형 정보 검색을 위한 강력한 도구다. 사용자의 질문 이력을 고려하여 맥락에 맞는 정보를 검색하고 응답함으로써, 단순한 질의응답 시스템보다 훨씬 자연스러운 대화 경험을 제공한다.

이 체인은 [[LangChain]]의 다른 컴포넌트들과 결합하여 더 강력한 애플리케이션을 구축할 수 있으며, [[Agent 사용 RAG+Tavily]], [[RAG+Groq]]와 같은 다른 RAG 구현 방식과 함께 사용하면 더욱 다양한 사용 사례를 지원할 수 있다.

더 자세한 정보와 API 문서는 [LangChain 공식 문서](https://api.python.langchain.com/en/latest/chains/langchain.chains.conversational_retrieval.base.ConversationalRetrievalChain.html)를 참조하자. 