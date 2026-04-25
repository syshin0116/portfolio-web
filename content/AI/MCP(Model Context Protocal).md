---
title: MCP(Model Context Protocol)
date: 2025-03-31
tags:
- ai
- anthropic
- mcp
- claude
- langchain
- langgraph
- tool-use
- smithery
draft: false
enableToc: true
description: Anthropic에서 개발한 MCP(Model Context Protocol)의 개념, 구조 및 활용에 대한 설명
summary: |
  MCP(Model Context Protocol)는 Anthropic에서 개발한 개방형 프로토콜로, AI 모델과 외부 데이터/도구를 표준화된 방식으로 연결한다.
  USB-C와 같이 AI 애플리케이션과 다양한 데이터 소스 간의 통합을 단순화하며, 클라이언트-서버 구조를 통해 안전하고 확장 가능한 AI 시스템 구축을 지원한다.
  Smithery를 통해 3,200개 이상의 MCP 서버에 접근할 수 있으며, Cursor와 Claude에서 쉽게 설정하여 사용할 수 있다.
published: 2025-03-31
modified: 2025-03-31
---
## 개요

### MCP란?

![](https://i.imgur.com/q4T1fhr.png)


MCP(Model Context Protocol)는 AI 모델과 외부 데이터 소스 및 도구를 연결하는 개방형 프로토콜이다. Anthropic에서 개발했으며, LLM 애플리케이션 개발 시 맞춤형 통합 솔루션 대신 표준화된 방식으로 데이터와 도구에 접근할 수 있게 한다.

쉽게 말해, MCP는 AI 모델에게 필요한 컨텍스트(문맥)를 가져오기 위한 표준 프로토콜로, USB-C를 AI 애플리케이션에 적용한 것과 같은 방식으로 이해할 수 있다.

![](https://i.imgur.com/LooAPju.png)

### MCP의 인기 상승 요인


![](https://i.imgur.com/lPhU3Vg.png)


MCP는 2024년 11월에 처음 발표되었을 때는 큰 반향을 불러일으키지 못했지만, 2025년 초부터 AI 커뮤니티에서 급격한 인기를 얻게 되었다. 이러한 인기 상승에는 여러 요인이 있다:

1. **핵심 채택 장벽 - 호스트 부족 문제 해결**: MCP의 초기 채택이 저조했던 주된 이유는 MCP를 실제로 사용할 수 있는 호스트 애플리케이션이 부족했기 때문이다. 아이디어는 훌륭했지만, Claude Desktop만으로는 개발자 생태계 전체에 영향을 미치기 어려웠다. Cursor, Windsurf, Cline 등 인기 있는 개발자 도구들이 MCP를 지원하기 시작하면서 이 문제가 해결되었고, 많은 소프트웨어 엔지니어들이 일상 작업에서 MCP의 가치를 직접 경험할 수 있게 되었다.

2. **네트워크 효과의 임계점 돌파**: 호스트 애플리케이션이 늘어나면서 MCP 서버 개발에 대한 수요도 급증했다. 2025년 2월까지 1,000개 이상의 커뮤니티 기반 MCP 서버가 개발되었고, 현재는 Smithery를 통해 3,200개 이상의 서버에 접근할 수 있다. 이는 전형적인 네트워크 효과를 만들어냈다 - 더 많은 호스트가 MCP를 지원할수록 더 많은 서버가 개발되고, 더 많은 서버가 있을수록 MCP 호스트의 가치가 높아지는 선순환이 형성되었다.

3. **산업 표준으로의 인정**: OpenAI가 자사의 ChatGPT 데스크톱 앱을 포함한 제품에 MCP 지원을 추가하기로 발표한 것은 MCP가 산업 표준으로 자리잡았음을 의미한다. 초기에는 단순히 Anthropic의 프로토콜로 여겨졌던 것이 이제는 AI 생태계 전반에 걸친 통합 표준으로 자리매김하게 되었다.

이러한 요인들이 결합되어 MCP는 단기간에 빠르게 성장할 수 있었으며, AI 모델과 외부 시스템 간의 통합 문제를 효과적으로 해결하는 사실상의 표준(de facto standard)으로 자리잡게 되었다.

### 기본 개념
- 표준화된 연결: AI 모델과 다양한 데이터 소스 및 도구 간의 통합된 연결 방식 제공
- 개방형 프로토콜: 여러 언어와 플랫폼에서 구현 가능한 개방형 구조
- 확장성: 필요에 따라 다양한 도구와 데이터 소스를 쉽게 추가 가능

![](https://i.imgur.com/GnETyjY.png)


---

## MCP의 아키텍처

### MCP의 전체 구조 요약

MCP는 클라이언트-서버 아키텍처를 기반으로 하며, 크게 세 가지 핵심 역할로 구성된다:

| 구성요소 | 설명 | 예시 |
|---------|------|------|
| 호스트(Host) | 전체 프로세스를 관리하고 연결을 조율하는 컨테이너 | Claude Desktop, Cursor |
| 클라이언트(Client) | MCP 서버에 연결하여 데이터를 요청하거나 명령을 내리는 역할 | Claude Agent, Cursor 내부 MCP 모듈 |
| 서버(Server) | 툴/리소스/프롬프트를 제공하는 외부 시스템 | DB MCP 서버, Git MCP 서버, 로그 MCP 서버 등 |

![](https://i.imgur.com/23LhWf8.png)

### 호스트(Host)의 역할

호스트는 MCP 아키텍처의 중앙 통제실이라고 할 수 있다. 모든 클라이언트는 호스트 안에서 실행된다.

#### 호스트가 하는 일
- 클라이언트(Client) 생성 및 관리
- 연결 권한 및 보안 정책 적용
- 사용자 동의 흐름(UI 제공)
- 다양한 서버의 응답을 취합 및 정제
- LLM(예: Claude, GPT)과 통합

#### 예시
- Claude Desktop 앱
- Cursor

### 클라이언트(Client)의 역할

클라이언트는 MCP 서버와 직접 대화하는 역할을 한다. 호스트가 만든 클라이언트가 1:1로 특정 서버와 연결되어 작동한다.

#### 클라이언트가 하는 일
- 서버와 연결을 초기화
- 서버의 capabilities(툴, 리소스 등) 요청
- 명령 전송, 응답 수신
- 사용자의 명령을 정리해서 서버에 전달

#### 대표 예시

| MCP 클라이언트 | 설명 |
|--------------|------|
| Claude Code | Claude 앱 안에서 코딩 툴 서버와 연결 |
| Cursor Editor | 편집기에서 MCP 서버로 코드/파일 요청 |
| Windsurf (Codium) | 코드 분석, 추천 등 MCP 기능 포함 |

### 서버(Server)의 역할

서버는 AI가 사용할 수 있는 기능을 툴(Tools), 리소스(Resources), 프롬프트(Prompts)로 노출한다.

#### 서버가 제공하는 기능

| 구성요소 | 설명 | 예시 |
|---------|------|------|
| Tools | 실행 가능한 기능 (API 호출, 계산 등) | run_backtest, place_order |
| Resources | AI가 참고할 수 있는 데이터 | price_data.csv, trade_history.json |
| Prompts | 사용자 정의 명령 템플릿 | "기술적 분석 전략 생성해줘" |

MCP 서버는 로컬(내 컴퓨터) 또는 원격(웹 서버) 어디든 존재 가능하다.
예: GitHub MCP 서버, Supabase Vector DB MCP 서버

### 클라이언트 ↔ 서버 간 메시지 흐름 (JSON-RPC)

MCP는 JSON-RPC 2.0이라는 통신 프로토콜을 기반으로 동작한다. 이 프로토콜은 메시지를 아래와 같은 세 가지로 구분한다:

| 유형 | 설명 |
|------|------|
| Request | 요청 메시지 (응답 필요) |
| Response | 요청에 대한 응답 |
| Notification | 알림 (응답 불필요) |

#### 메시지 흐름 예시 (백테스트 툴 실행)

1. Client → Server:
```json
{
  "jsonrpc": "2.0",
  "method": "tools/run_backtest",
  "params": {
    "strategy": "mean_reversion",
    "period": "30d"
  },
  "id": 1
}
```

2. Server → Client:
```json
{
  "jsonrpc": "2.0",
  "result": {
    "sharpe_ratio": 1.8,
    "pnl": 12.5
  },
  "id": 1
}
```

```json
{ 
  "jsonrpc": "2.0", 
  "method": "log", 
  "params": { 
    "message": "Backtest completed" 
  } 
}
```

#### 통신 흐름 예시

1. 사용자가 Claude Desktop(호스트)에서 "내 파일 시스템에서 최신 보고서를 찾아줘"라고 요청
2. Claude Desktop은 파일 시스템 MCP 클라이언트를 활성화
3. 클라이언트는 파일 시스템 MCP 서버와 연결 초기화
4. 서버는 사용 가능한 도구 목록(파일 검색, 읽기 등)을 반환
5. 클라이언트는 파일 검색 도구를 호출하여 최신 보고서 파일 검색
6. 서버는 파일 시스템에서 검색 작업을 실행하고 결과 반환
7. 클라이언트는 결과를 호스트에 전달
8. 호스트는 이 정보를 LLM에 전달하여 적절한 응답 생성

### 통신 프로토콜
- JSON-RPC 2.0 메시지 형식 사용
- 상태 유지형 연결 지원
- 서버 및 클라이언트 간 기능 협상 제공

### MCP 통신 전송 방식

MCP는 여러 가지 전송 방식(Transport)을 지원하여 다양한 환경에서 유연하게 작동할 수 있다. 주로 사용되는 두 가지 전송 방식은 stdio와 SSE이다.

#### STDIO (Standard Input/Output)
- 정의: stdio는 표준 입력(stdin)과 표준 출력(stdout)을 사용하여 로컬 프로세스 간 통신하는 방식이다.
- 작동 방식:
  - 클라이언트가 자식 프로세스로 MCP 서버를 시작
  - 클라이언트는 stdin으로 메시지를 보내고 stdout에서 응답을 읽음
  - JSON-RPC 메시지를 줄 단위로 교환
  
| 장점 | 단점 |
|------|------|
| 로컬 환경에서 매우 간단하고 빠른 설정 | 로컬 시스템에서만 작동 가능 |
| 보안 측면에서 외부 네트워크 노출이 없음 | 원격 서버와 연결 불가 |
| 낮은 지연 시간과 오버헤드 | 확장성이 제한적 |
  
- 활용 사례:
  - 로컬 파일 시스템 접근
  - 로컬 명령어 실행
  - 개인용 도구 통합

```python
# stdio 서버 실행 예시
if __name__ == "__main__":
    mcp.run(transport="stdio")

# stdio 클라이언트 연결 예시
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

server_params = StdioServerParameters(
    command="python",
    args=["/path/to/server.py"],
)

async with stdio_client(server_params) as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
```

#### SSE (Server-Sent Events)
- 정의: SSE는 서버에서 클라이언트로 단방향 실시간 데이터 스트림을 제공하는 HTTP 기반 통신 기술이다.
- 작동 방식:
  - 클라이언트가 HTTP 연결을 통해 서버에 연결
  - 서버는 `text/event-stream` 콘텐츠 타입으로 응답
  - 클라이언트는 별도의 HTTP 요청으로 메시지 전송
  - 서버는 스트림을 통해 이벤트 형태로 응답 전송
  
| 장점 | 단점 |
|------|------|
| 기존 웹 인프라와 호환성 우수 | stdio보다 더 많은 오버헤드 |
| 방화벽 친화적 (표준 HTTP 사용) | 웹 서버 설정 필요 |
| 원격 서버와 통신 가능 | 양방향 통신을 위해 추가 HTTP 요청 필요 |
| 자동 재연결 메커니즘 내장 | |
  
- 활용 사례:
  - 웹 기반 MCP 서버 호스팅
  - 원격 서비스 통합
  - 다중 클라이언트 지원

```python
# SSE 서버 설정 예시 (FastAPI 사용)
from fastapi import FastAPI
from mcp.server.sse import serve_sse

app = FastAPI()
mcp = FastMCP("MyServer")

# SSE 엔드포인트 등록
serve_sse(app, mcp, path="/sse")

# 서버 실행
import uvicorn
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

# SSE 클라이언트 연결 예시
from mcp.client.sse import sse_client

async with sse_client("http://localhost:8000/sse") as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
```

#### 전송 방식 선택 가이드
- 로컬 도구와 리소스: stdio 사용 (보안 및 성능 최적화)
- 웹 서비스 및 공유 도구: SSE 사용 (접근성 및 확장성)
- 기업 환경: 보안 정책에 따라 선택 (내부 도구는 stdio, 공유 도구는 SSE)
- 개발 및 테스트: stdio가 더 단순하고 빠른 설정 제공

---

## MCP의 주요 기능

MCP는 서버와 클라이언트 간에 다양한 기능을 제공한다. 이러한 기능들은 AI 모델이 외부 시스템과 상호작용하는 데 필요한 인터페이스를 제공한다.

### 서버가 제공하는 기능

MCP 서버는 세 가지 핵심 기능을 제공한다:

| 기능 유형 | 설명 | 예시 |
|---------|------|------|
| 리소스(Resources) | AI 모델이 참조할 수 있는 컨텍스트 데이터 및 콘텐츠 | 파일 내용, 데이터베이스 결과, 웹페이지 내용 |
| 프롬프트(Prompts) | 재사용 가능한 프롬프트 템플릿 및 워크플로우 | 정형화된 분석 요청, 표준화된 응답 형식 |
| 도구(Tools) | AI 모델이 실행할 수 있는 함수 및 작업 | 파일 생성, API 호출, 데이터 처리 |

### 클라이언트가 제공하는 기능
- 샘플링(Sampling): 서버 주도의 에이전트 동작 및 재귀적 LLM 상호작용 지원
- 컨텍스트 관리: AI 모델에 전달할 컨텍스트 데이터 관리 및 최적화

### 추가 유틸리티 기능
- 구성(Configuration): 서버 및 클라이언트 설정 관리
- 진행 상황 추적(Progress tracking): 장시간 작업의 상태 모니터링
- 취소(Cancellation): 실행 중인 작업 중단 기능
- 오류 보고(Error reporting): 표준화된 오류 메시지 및 처리
- 로깅(Logging): 디버깅 및 감사를 위한 로그 기록

![](https://i.imgur.com/NtOVng9.png)

---

## 구현 및 SDK

MCP는 다양한 프로그래밍 언어로 구현된 SDK(Software Development Kit)를 제공하여 개발자가 쉽게 MCP 서버와 클라이언트를 구축할 수 있도록 지원한다.

### 공식 SDK 목록
- Python SDK: [python-sdk](https://github.com/modelcontextprotocol/python-sdk)
- TypeScript SDK: [typescript-sdk](https://github.com/modelcontextprotocol/typescript-sdk)
- Java/Kotlin SDK: [java-sdk](https://github.com/modelcontextprotocol/java-sdk)
- C# SDK: [csharp-sdk](https://github.com/modelcontextprotocol/csharp-sdk)
- Swift SDK: [swift-sdk](https://github.com/modelcontextprotocol/swift-sdk)

### 간단한 MCP 서버 구현 예시 (Python)
다음은 간단한 수학 연산을 제공하는 MCP 서버의 구현 예시이다:

```python
# math_server.py
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Math")

@mcp.tool()
def add(a: int, b: int) -> int:
    """두 숫자 더하기"""
    return a + b

@mcp.tool()
def multiply(a: int, b: int) -> int:
    """두 숫자 곱하기"""
    return a * b

if __name__ == "__main__":
    mcp.run(transport="stdio")
```

이 서버는 `add`와 `multiply` 두 가지 도구를 제공하며, stdio 전송 방식을 사용하여 실행된다.

### MCP 클라이언트 구현 예시 (Python)
다음은 위에서 만든 수학 서버에 연결하는 클라이언트 예시이다:

```python
# 표준 입출력 연결 파라미터 생성
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# 서버 연결 정보 설정
server_params = StdioServerParameters(
    command="python",
    args=["/path/to/math_server.py"],
)

# 서버에 연결하고 세션 초기화
async with stdio_client(server_params) as (read, write):
    async with ClientSession(read, write) as session:
        # 연결 초기화
        await session.initialize()
        
        # 사용 가능한 도구 목록 가져오기
        tools = await session.list_tools()
        
        # 도구 호출 예시
        result = await session.invoke_tool("add", {"a": 5, "b": 3})
        print(f"5 + 3 = {result}")  # 출력: 5 + 3 = 8
```

### 타입스크립트 서버 예시
다음은 TypeScript로 작성된 간단한 MCP 서버 예시이다:

```typescript
// weather_server.ts
import { FastMCP } from "@mcp/server";

const mcp = new FastMCP("Weather");

interface WeatherParams {
  city: string;
}

interface WeatherResult {
  temperature: number;
  condition: string;
}

// 날씨 조회 도구 등록
mcp.tool<WeatherParams, WeatherResult>({
  name: "getWeather",
  description: "Get current weather for a city",
  parameters: {
    city: {
      type: "string",
      description: "City name",
    },
  },
  handler: async ({ city }) => {
    // 실제로는 날씨 API를 호출하겠지만, 예시에서는 가상 데이터 반환
    return {
      temperature: 22,
      condition: "Sunny",
    };
  },
});

// 서버 실행
mcp.run({ transport: "stdio" });
```

이러한 SDK를 활용하면 개발자는 쉽게 자신만의 MCP 서버와 클라이언트를 구축하여 AI 모델과 외부 시스템을 연결할 수 있다.

---

## LangChain과 LangGraph 통합

MCP는 AI 애플리케이션 개발에 널리 사용되는 LangChain 및 LangGraph와 원활하게 통합되어 더욱 강력한 AI 솔루션을 구축할 수 있다.

### LangChain MCP Adapters 소개
- 정의: LangChain MCP Adapters는 Anthropic의 MCP 도구를 LangChain 및 LangGraph와 호환되도록 하는 경량 래퍼이다.
- GitHub 저장소: [langchain-mcp-adapters](https://github.com/langchain-ai/langchain-mcp-adapters)

![](https://i.imgur.com/3LMvUyw.png)

### 주요 통합 기능

| 기능 | 설명 |
|------|------|
| 도구 변환 | MCP 도구를 LangChain 도구로 변환하여 쉽게 사용 |
| 멀티 서버 | 여러 MCP 서버에 동시 연결 및 도구 로드 지원 |
| 에이전트 호환성 | LangGraph 에이전트에서 MCP 도구 직접 사용 가능 |
| 비동기 지원 | 비동기 작업 흐름 지원 |

### 활용 예시 (Python)
다음은 LangChain과 MCP를 통합하는 코드 예시이다:

```python
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt import create_react_agent
from langchain_openai import ChatOpenAI

# LLM 모델 초기화
model = ChatOpenAI(model="gpt-4o")

# 여러 MCP 서버에 연결하는 예시
async with MultiServerMCPClient(
    {
        "math": {  # 수학 연산 서버
            "command": "python",
            "args": ["/path/to/math_server.py"],
            "transport": "stdio",
        },
        "weather": {  # 날씨 정보 서버
            "url": "http://localhost:8000/sse",
            "transport": "sse",
        }
    }
) as client:
    # 모든 서버의 도구를 LangChain 도구로 변환
    tools = client.get_tools()
    
    # ReAct 에이전트 생성
    agent = create_react_agent(model, tools)
    
    # 에이전트에 질문 전달
    response = await agent.ainvoke({"messages": "뉴욕의 날씨는 어때?"})
    
    print(response)
```

### LangGraph 통합 활용 사례
LangGraph는 에이전트 워크플로우를 구축하는 데 사용되는 프레임워크로, MCP와 통합하면 다음과 같은 작업이 가능하다:

1. 멀티 스텝 에이전트: 여러 MCP 서버의 도구를 활용하여 복잡한 작업 수행
2. 도구 기반 추론: ReAct와 같은 도구 기반 추론 프레임워크에 MCP 도구 활용
3. 복잡한 워크플로우: 조건부 분기, 루프 등 복잡한 작업 흐름 구현

```python
# LangGraph와 MCP 통합 예시
from langgraph.graph import StateGraph
from langchain_mcp_adapters.tools import load_mcp_tools
import operator

# 상태 그래프 정의
builder = StateGraph()

# 노드 추가 (각 노드는 MCP 도구를 사용할 수 있음)
builder.add_node("analyze_data", analyze_data_with_mcp_tools)
builder.add_node("generate_report", generate_report_with_mcp_tools)
builder.add_node("send_notification", send_notification_with_mcp_tools)

# 엣지 연결
builder.add_edge("analyze_data", "generate_report")
builder.add_edge("generate_report", "send_notification")

# 그래프 컴파일 및 실행
graph = builder.compile()
result = graph.invoke({"query": "주간 매출 보고서 생성"})
```

이러한 통합을 통해 개발자는 MCP의 유연성과 LangChain/LangGraph의 강력한 에이전트 구축 기능을 결합하여 더 지능적인 AI 애플리케이션을 만들 수 있다.

---

## 활용 사례

MCP는 다양한 분야에서 활용될 수 있으며, 현재 여러 서버 구현이 제공되고 있다. 이 섹션에서는 실제 MCP를 활용한 다양한 사례를 살펴본다.

### 공식 및 커뮤니티 서버 예시

| 서버 유형 | 제공 기능 | 활용 사례 |
|---------|----------|----------|
| 파일시스템 | 안전한 파일 읽기/쓰기/검색 | 로컬 파일 분석, 문서 처리 |
| GitHub | 저장소 관리, 파일 작업 | 코드 분석, PR 리뷰, 이슈 관리 |
| Google Drive | 파일 접근 및 검색 | 문서 요약, 데이터 추출 |
| PostgreSQL | 데이터베이스 조회 | 데이터 분석, 리포트 생성 |
| Slack | 채널 관리 및 메시징 | 자동화된 알림, 팀 커뮤니케이션 |
| 메모리 | 지식 그래프 기반 메모리 | 대화 기록 유지, 컨텍스트 관리 |
| Puppeteer | 브라우저 자동화 | 웹 스크래핑, UI 테스트 |
| Brave Search | 웹 검색 API | 최신 정보 검색, 사실 확인 |

### 활용 시나리오별 예시

#### 1. 데이터 분석 워크플로우
MCP를 활용하여 데이터 분석가가 자연어로 복잡한 분석을 수행하는 시나리오:

1. 사용자가 "지난 분기 매출 데이터를 분석하고 트렌드를 보여줘"라고 요청
2. AI 시스템이 PostgreSQL MCP 서버를 통해 데이터베이스에서 매출 데이터 조회
3. 파이썬 데이터 분석 MCP 서버를 사용하여 추세 분석 수행
4. 시각화 MCP 서버를 통해 결과를 그래프로 생성
5. 파일시스템 MCP 서버를 사용하여 결과 보고서 저장

#### 2. 소프트웨어 개발 지원
개발자를 위한 AI 코딩 어시스턴트 시나리오:

1. 개발자가 "이 버그 수정 방법 알려줘"라고 요청
2. GitHub MCP 서버를 통해 코드베이스 접근 및 분석
3. 메모리 MCP 서버를 사용하여 과거 유사한 버그 수정 기록 참조
4. 테스트 실행 MCP 서버로 버그 재현 및 진단
5. Git MCP 서버를 통해 수정 사항 커밋 및 PR 생성 지원

#### 3. 고객 지원 자동화
기업 지원 시스템의 AI 에이전트 시나리오:

1. 고객이 "내 주문 현황 알려줘"라고 요청
2. CRM MCP 서버를 통해 고객 정보 및 주문 내역 조회
3. 이메일 MCP 서버를 사용하여 고객과의 과거 커뮤니케이션 확인
4. 물류 시스템 MCP 서버로 배송 상태 확인
5. Slack MCP 서버를 통해 필요시 인간 상담원에게 알림 전송

이러한 다양한 활용 사례는 MCP의 확장성과 유연성을 보여주며, 개발자는 필요에 따라 자신만의 MCP 서버를 구현하여 AI 시스템의 기능을 확장할 수 있다.

---

## Smithery 소개

Smithery는 MCP 생태계를 위한 중앙 허브 역할을 하는 플랫폼으로, 다양한 MCP 서버들을 검색하고 활용할 수 있는 환경을 제공한다. 쉽게 말해 MCP 서버의 "앱 스토어"라고 생각할 수 있다.

![](https://i.imgur.com/2KFvXNB.png)

### Smithery의 주요 기능

| 기능 | 설명 |
|------|------|
| 서버 디렉토리 | 3,200개 이상의 MCP 서버 제공 및 검색 기능 |
| 카테고리 분류 | 웹 검색, 메모리 관리, 브라우저 자동화 등 기능별 분류 |
| 쉬운 설치 | Claude Desktop 및 다른 MCP 호환 클라이언트에 간편한 통합 |
| 개발자 도구 | MCP 서버 개발 및 배포를 위한 도구 제공 |

### 주요 서버 카테고리 및 인기 서버

#### 1. 웹 검색 서버
| 서버 이름 | 주요 기능 | 특징 |
|----------|----------|-------|
| Brave Search | 웹 및 로컬 검색 | Brave의 프라이버시 중심 검색 엔진 활용 |
| Exa Search | 지능형 웹 검색 | 임베딩과 전통적 검색을 결합한 정확한 결과 |
| Perplexity Search | 전문 웹 검색 | Perplexity의 Sonar Pro 검색 기술 활용 |

#### 2. 메모리 관리 서버
| 서버 이름 | 주요 기능 | 특징 |
|----------|----------|-------|
| Knowledge Graph Memory | 지식 그래프 기반 메모리 | 관계형 정보 저장 및 검색 |
| Memory Box | 시맨틱 메모리 | 의미 기반 정보 저장 및 검색 |
| DuckDB Knowledge Graph | 효율적 메모리 시스템 | 빠른 쿼리 성능의 메모리 저장소 |

#### 3. 브라우저 자동화 서버
| 서버 이름 | 주요 기능 | 특징 |
|----------|----------|-------|
| Browserbase | 클라우드 브라우저 자동화 | 확장 가능한 브라우저 제어 |
| Hyperbrowser | 웹 스크래핑 | 구조화된 데이터 추출 기능 |
| Playwright | 브라우저 제어 | 다양한 브라우저 지원 및 자동화 |

#### 4. 기타 유용한 서버
- 금융 데이터: Crypto Price & Market Analysis, Alpha Vantage Stock Server
- 날씨/위치: Weather 서버, Time Server, Flightradar24 Server
- 생산성: Notion, Calendar, Todo MCP 서버

### Smithery 사용 방법 (단계별 가이드)

1. 접속 및 탐색
   - [Smithery 웹사이트](https://smithery.ai/) 방문
   - 검색창을 통해 원하는 기능 검색 또는 카테고리 탐색

2. 서버 선택 및 상세 정보 확인
   - 원하는 서버 클릭하여 상세 정보 확인
   - 제공 기능, 필요 권한, 설치 방법 검토

3. 설치 지침 확인
   - 서버별 설치 명령어 확인 (대부분 npm 또는 pip 명령어)
   - 필요한 API 키나 구성 정보 확인

4. 클라이언트 연결
   - Claude Desktop이나 Cursor 등 MCP 호환 클라이언트에 서버 연결
   - 필요한 인증 및 권한 설정

5. 서버 활용
   - 연결된 서버의 기능을 AI 애플리케이션에서 직접 활용
   - 필요시 여러 서버를 조합하여 복잡한 워크플로우 구성

---

## Cursor와 Claude에서의 MCP 설정

MCP를 활용하려면 호스트 애플리케이션에서 서버 설정이 필요하다. 이 섹션에서는 인기 있는 두 가지 MCP 호스트인 Cursor와 Claude Desktop에서 MCP를 설정하는 방법을 안내한다.

### Cursor에서 MCP 설정하기

Cursor는 AI 기반 코드 에디터로, MCP를 통해 다양한 도구와 연결할 수 있다.

![](https://i.imgur.com/X0r8WyP.png)

#### 1. Cursor 설치 및 업데이트
- [Cursor 공식 웹사이트](https://cursor.sh/)에서 최신 버전 다운로드
- MCP 지원을 위해 v0.8.0 이상 버전이 필요하다
- 기존 설치된 경우 최신 버전으로 업데이트

#### 2. MCP 서버 설치 (예: 파일 검색 서버)
```bash
# npm을 통한 MCP 서버 설치 예시
npm install -g @anthropic-ai/mcp-server-file-search

# 또는 Python 기반 서버 설치 예시
pip install mcp-server-python-database
```

#### 3. Cursor 내 MCP 설정 방법
1. 설정 메뉴 접근
   - Cursor 실행
   - Settings > AI > MCP Servers 메뉴 접근 (또는 `Cmd+,` 단축키)

2. 서버 추가
   - Add Server 버튼 클릭
   - 다음 정보 입력:
     - Name: 서버 이름 (예: "File Search")
     - Transport: stdio 또는 sse 선택
     - Command: 서버 실행 명령어 (예: "mcp-file-search")
     - Args: 필요한 인자값

3. 서버 활성화
   - 추가된 서버 옆의 토글 버튼으로 활성화
   - 활성화된 서버는 Cursor의 AI 기능에서 자동으로 사용 가능

#### 4. Cursor에서 MCP 서버 사용
- AI 패널에서 직접 명령 (예: "이 프로젝트에서 API 관련 파일을 찾아줘")
- 코드 편집 시 자동 추천 및 보완 기능 활용

### Claude Desktop에서 MCP 설정하기

Claude Desktop은 Anthropic의 데스크톱 애플리케이션으로, MCP를 통해 다양한 기능을 확장할 수 있다.

#### 1. Claude Desktop 설치
- [Claude Desktop](https://claude.ai/desktop) 다운로드 및 설치
- 최신 버전으로 업데이트 확인

#### 2. MCP 서버 연결
1. 설정 메뉴 접근
   - Claude Desktop 실행
   - Settings > Tools > MCP Servers 접근

2. 서버 연결
   - Connect Server 버튼 클릭
   - 연결 방식 선택:
     - Smithery에서 제공하는 서버 URL 입력
     - 로컬 설치된 서버 연결 정보 입력
   - 연결 테스트 후 Save 버튼 클릭

3. 권한 설정
   - 각 서버별 필요한 권한 설정
   - 파일 시스템 접근, API 호출 등 필요한 권한만 선택적 활성화
   - 보안 정책에 따라 제한적 권한 부여 가능

#### 4. Claude에서 MCP 서버 활용
- 대화창에서 자연어로 서버 기능 요청
- 예시 명령:
  ```
  "웹 검색 도구를 사용해서 최신 AI 트렌드를 찾아줘"
  "내 문서 폴더에서 지난달 작성한 보고서를 검색해줘"
  "이 엑셀 파일의 데이터를 분석하고 그래프로 보여줘"
  ```

### 보안 고려사항
MCP 서버를 설정할 때 다음과 같은 보안 사항을 고려해야 한다:

- 신뢰할 수 있는 소스만 사용: 검증된 소스의 MCP 서버만 설치
- 최소 권한 원칙: 필요한 최소한의 권한만 부여
- 정기적 업데이트: 서버를 정기적으로 업데이트하여 보안 취약점 패치
- 중요 데이터 보호: 민감한 데이터에 접근하는 서버는 추가 인증 설정
- 로깅 활성화: 문제 발생 시 진단을 위한 로그 기록 유지

---

## 결론

MCP는 AI 시스템과 외부 데이터 소스 및 도구 간의 상호작용을 표준화함으로써 AI 애플리케이션 개발을 크게 단순화한다. 오픈 프로토콜로서 다양한 언어와 플랫폼에서 구현될 수 있으며, 보안 및 개인 정보 보호 원칙을 중심으로 설계되어 안전한 AI 시스템 구축을 지원한다.

### MCP의 주요 장점
- 표준화된 통합: AI 모델이 외부 데이터 및 도구와 일관된 방식으로 통합
- 개방형 생태계: 다양한 개발자와 기업이 참여하는 혁신적인 생태계 조성
- 확장성: 필요에 따라 새로운 서버와 기능을 쉽게 추가 가능
- 보안성: 권한 기반의 접근 제어로 안전한 AI 시스템 구축
- 유연성: 다양한 언어와 플랫폼에서 구현 가능한 유연한 아키텍처

### 향후 발전 방향
MCP는 지속적으로 발전하고 있으며, 다음과 같은 방향으로 확장될 것으로 예상된다:

1. 더 많은 도메인별 서버: 특화된 산업 및 분야를 위한 MCP 서버 증가
2. 표준화된 프롬프트 공유: 효과적인 프롬프트 템플릿 공유 및 재사용
3. 엔터프라이즈 통합: 기업 시스템과의 보안 통합 강화
4. 에이전트 기반 워크플로우: 복잡한 멀티스텝 에이전트 워크플로우 지원
5. 멀티모달 지원: 텍스트 외에 이미지, 오디오 등 다양한 데이터 타입 지원

MCP에 대해 알기 전에 [[LangChain]], [[LangGraph]], [[Agent 사용 RAG+Tavily]] 문서를 먼저 살펴보면 AI 애플리케이션 개발에 대한 종합적인 이해를 얻을 수 있다. 

또한, MCP에 이어서 구글에서 발표한 [Agent2Agent Protocal](https://developers.googleblog.com/en/a2a-a-new-era-of-agent-interoperability/)도 주목할 만한 발전이다. A2A는 여러 AI 에이전트 간의 통신을 위한 프로토콜로, 더 복잡한 협업 시스템을 구축하는 데 활용될 수 있다. MCP와 A2A를 모두 활용한 대규모 멀티에이전트 시스템 구축에 대한 자세한 내용은 [[멀티에이전트 아키텍처와 대규모 구현 전략]] 문서를 참고하자. 


## 참고자료

- [Model Context Protocol 공식 문서](https://modelcontextprotocol.io/introduction)
- [Model Context Protocol GitHub](https://github.com/modelcontextprotocol)
- [Anthropic MCP 문서](https://docs.anthropic.com/en/docs/build-with-claude/mcp)
- [Agent2Agent Protocol (A2A)](https://developers.googleblog.com/en/a2a-a-new-era-of-agent-interoperability/)
- [MCP 아키텍처 완전 정리](https://datasciencebeehive.tistory.com/266)
- [langchain-mcp-adapters](https://github.com/langchain-ai/langchain-mcp-adapters)