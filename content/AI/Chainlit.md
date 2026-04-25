---
title: Chainlit
date: 2024-08-13
tags:
- ai
- ui
- langchain
- chatbot
- development
draft: false
enableToc: true
description: 빠르게 대화형 AI 애플리케이션을 개발할 수 있는 Chainlit 라이브러리 사용법
summary: "Chainlit은 빠르게 프로덕션 준비가 된 대화형 AI 애플리케이션을 개발할 수 있는 오픈소스 파이썬 패키지이다. LangChain과의 통합을 통해 문서에서 정보를 추출하고 질문에 답변하는 챗봇을 쉽게 만들 수 있다. 파일 업로드, 벡터 스토어 기반 검색, 대화 기록 관리 등의 기능을 제공하며, 직관적인 UI로 사용자 경험을 향상시킨다."
published: 2024-08-13
modified: 2024-08-13
---
## 개요

Chainlit은 오픈소스 파이썬 패키지로, 빠르게 프로덕션 준비가 된 대화형 AI 애플리케이션을 개발하는 데 도움을 준다. 특히 LangChain과 같은 라이브러리와 통합하여 RAG(Retrieval-Augmented Generation) 기반 챗봇을 쉽게 구현할 수 있다.

## 시스템 설정 및 초기화

### 필요 라이브러리 설치

Chainlit과 관련 라이브러리를 설치하는 방법은 다음과 같다:

```bash
pip install chainlit langchain openai chroma
```

### 기본 코드 구조

Chainlit 기반 챗봇의 주요 구성 요소는 다음과 같다:

- **문서 로더**: PDF와 텍스트 파일에서 데이터를 로드
- **텍스트 분할기**: 긴 텍스트를 일정한 크기로 나눠 처리
- **임베딩 및 벡터 스토어**: 텍스트 데이터를 벡터화하고 검색 가능한 형태로 저장
- **대화형 검색 체인**: 사용자 입력에 따라 관련 정보를 검색하고 응답을 생성

### 초기화 코드 예시

```python
import chainlit as cl
from langchain.document_loaders import PyPDFLoader, TextLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.embeddings import OpenAIEmbeddings
from langchain.vectorstores import Chroma
from langchain.memory import ConversationBufferMemory, ChatMessageHistory
from langchain.chains import ConversationalRetrievalChain
from langchain.chat_models import ChatOpenAI

# 텍스트 분할 설정
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=100
)

# OpenAI 임베딩 초기화
embeddings = OpenAIEmbeddings()

# 컬렉션 추적을 위한 세트
collections = set()

# 환영 메시지
welcome_message = "안녕하세요! 문서에 대해 질문하려면 PDF 또는 텍스트 파일을 업로드해주세요."
```

## 문서 처리 및 챗봇 실행

### 파일 처리 함수

```python
def process_file(file: cl.AskFileResponse):
    if file.type == "text/plain":
        Loader = TextLoader
    elif file.type == "application/pdf":
        Loader = PyPDFLoader

    loader = Loader(file.path)
    documents = loader.load()
    docs = text_splitter.split_documents(documents)
    return docs
```

이 함수는 사용자가 업로드한 PDF 또는 텍스트 파일을 로드하여 텍스트로 변환하고 특정 크기로 나눈 문서 목록을 반환한다.

### 벡터 스토어 초기화

```python
def get_docsearch(file: cl.AskFileResponse):
    docs = process_file(file)
    cl.user_session.set("docs", docs)
    collection_name = file.id

    if collection_name in collections:
        docsearch = Chroma(
            collection_name=collection_name, embedding_function=embeddings
        )
    else:
        docsearch = Chroma.from_documents(
            docs, embeddings, collection_name=collection_name
        )
        collections.add(collection_name)

    return docsearch
```

이 함수는 문서를 처리하고 벡터 스토어에 저장하여 사용자가 질문할 때 검색할 수 있도록 설정한다.

## 대화 세션 관리

### 챗봇 세션 시작

```python
@cl.on_chat_start
async def start():
    files = None
    while files is None:
        files = await cl.AskFileMessage(
            content=welcome_message,
            accept=["text/plain", "application/pdf"],
            max_size_mb=20,
            timeout=180,
        ).send()

    file = files[0]

    msg = cl.Message(content=f"Processing `{file.name}`...")
    await msg.send()

    docsearch = await cl.make_async(get_docsearch)(file)

    message_history = ChatMessageHistory()

    memory = ConversationBufferMemory(
        memory_key="chat_history",
        output_key="answer",
        chat_memory=message_history,
        return_messages=True,
    )
    chain = ConversationalRetrievalChain.from_llm(
        ChatOpenAI(model_name="gpt-4o-mini", temperature=0, streaming=True),
        chain_type="stuff",
        retriever=docsearch.as_retriever(),
        memory=memory,
        return_source_documents=True,
    )

    msg.content = f"`{file.name}` 처리가 완료되었습니다. 이제 질문하실 수 있습니다!"
    await msg.update()

    cl.user_session.set("chain", chain)
```

이 함수는 사용자가 파일을 업로드하면 해당 파일을 처리하고 대화형 검색 체인을 초기화한다.

### 사용자 메시지 처리

```python
@cl.on_message
async def main(message: cl.Message):
    chain = cl.user_session.get("chain")  # type: ConversationalRetrievalChain
    cb = cl.AsyncLangchainCallbackHandler()

    async with cl.Step(name="ConversatinalRetrievalChain", type="retriever") as step:
        step.input = message.content
        res = await chain.ainvoke(message.content, callbacks=[cb])
        for source in res["source_documents"]:
            await step.stream_token(str(source))

    answer = res["answer"]
    source_documents = res["source_documents"]  # type: List[Document]

    text_elements = []  # type: List[cl.Text]

    if source_documents:
        for source_idx, source_doc in enumerate(source_documents):
            source_name = f"source_{source_idx}"
            text_elements.append(
                cl.Text(
                    content=source_doc.page_content, name=source_name, display="side"
                )
            )
        source_names = [text_el.name for text_el in text_elements]

        if source_names:
            answer += f"\nSources: {', '.join(source_names)}"
        else:
            answer += "\nNo sources found"

    await cl.Message(content=answer, elements=text_elements).send()
```

이 함수는 사용자 입력을 기반으로 적절한 응답을 생성하고 관련 소스 문서를 함께 제공한다.

## Step 클래스 활용

Chainlit의 `Step` 클래스는 챗봇 응답 과정을 단계별로 보여주기 위한 컨텍스트 관리자다.

### Step 클래스의 주요 매개변수

- **name**: 단계의 이름
- **type**: 단계의 유형(retriever, llm 등)
- **elements**: 단계에 첨부할 요소의 리스트
- **root**: 단계의 계층 구조를 설정(True면 최상위 단계)
- **language**: 출력의 언어를 지정

### 기본 사용 예시

```python
@cl.on_message
async def main():
    async with cl.Step(name="Test") as step:
        step.input = "hello"
        step.output = "world"
```

### 스트림 출력 예시

```python
@cl.on_message
async def main(msg: cl.Message):
    async with cl.Step(name="gpt4", type="llm", root=True) as step:
        step.input = msg.content

        stream = await client.chat.completions.create(
            messages=[{"role": "user", "content": msg.content}],
            stream=True,
            model="gpt-4",
            temperature=0,
        )

        async for part in stream:
            delta = part.choices[0].delta
            if delta.content:
                await step.stream_token(delta.content)
```

### 단계 중첩 예시

```python
@cl.on_chat_start
async def main():
    async with cl.Step(name="Parent step") as parent_step:
        parent_step.input = "Parent step input"

        async with cl.Step(name="Child step") as child_step:
            child_step.input = "Child step input"
            child_step.output = "Child step output"

        parent_step.output = "Parent step output"
```

## Chainlit UI 요소

Chainlit은 다양한 UI 요소를 제공하여 사용자 경험을 향상시킨다:

### 메시지 요소

- **Text**: 텍스트 컨텐츠를 표시
- **Image**: 이미지 표시
- **Avatar**: 사용자 아바타 설정
- **TaskList**: 작업 목록 표시

### 인터랙티브 요소

- **Select**: 드롭다운 메뉴
- **Slider**: 슬라이더 컨트롤
- **FileSelector**: 파일 선택 도구
- **Pandas Dataframe**: 데이터프레임 표시

## 결론

Chainlit은 대화형 AI 애플리케이션을 빠르게 개발하기 위한 강력한 도구다. LangChain과의 통합을 통해 문서 기반 질의응답 시스템을 구축하는 과정을 간소화하며, 직관적인 UI 요소와 비동기 프로그래밍 지원을 통해 사용자 경험을 향상시킨다.

관련 문서로는 [[LangChain]], [[LLM Chain Chatbot + RAG]], [[Agent 사용 RAG+Tavily]]를 참조하자. 