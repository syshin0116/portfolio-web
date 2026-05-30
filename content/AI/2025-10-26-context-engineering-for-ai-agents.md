---
title: 'Context Engineering for AI Agents: With LangChain and Manus'
date: 2025-10-26
tags:
- AI
- Agent
- LLM
- Context-Engineering
- Manus
- LangChain
draft: false
enableToc: true
description: LangChain과 Manus 웨비나에서 배운 AI 에이전트의 컨텍스트 엔지니어링 핵심 전략. 컨텍스트 오프로딩, 축소(압축
  vs 요약), 격리(통신 vs 메모리 공유), 계층형 액션 공간 등 실전 검증된 기법과 '덜 구축하고 더 이해하라'는 철학을 다룬다.
summary: "LangChain과 Manus가 공동 진행한 웨비나에서 AI 에이전트 개발의 핵심 과제인 컨텍스트 엔지니어링에 대해 깊이 있는 인사이트를 얻었다. 에이전트는 도구를 자유롭게 호출하며 작업을 수행하지만, 매 호출마다 컨텍스트가 무한정 증가하여 성능이 저하되는 역설적 문제에 직면한다. 이 글에서는 Manus가 실제 프로덕션 환경에서 검증한 5가지 핵심 기법(오프로딩, 축소, 검색, 격리, 캐싱)과 계층형 액션 공간 같은 혁신적 해결책을 다룬다. 특히 '덜 구축하고 더 이해하라'는 철학이 인상적이었다."
published: 2025-10-26
modified: 2025-10-26
---
## 컨텍스트 엔지니어링이 필요한 이유

[[LLM Chain Chatbot + RAG]] 같은 단순한 RAG 시스템과 달리, AI 에이전트는 본질적으로 **컨텍스트 폭증** 문제를 안고 있다.

### 문제의 본질

에이전트가 작동하는 방식은 간단해 보인다:

```
사용자 질의 → LLM 추론 → 도구 호출 → 결과 반환 → 컨텍스트 추가 → 다음 추론
```

하지만 이 루프가 반복되면서 컨텍스트는 기하급수적으로 증가한다. Manus의 경우 일반적인 작업에 **약 50회의 도구 호출**이 필요하고, Anthropic은 프로덕션 에이전트가 **수백 턴**에 걸친 대화를 처리한다고 밝혔다.

![](https://i.imgur.com/neKAIu1.png)


> [!danger] 컨텍스트 로트 (Context Rot)
>
> Chrome 보고서에 따르면 컨텍스트가 증가할수록 에이전트 성능이 저하된다. 대부분의 모델은 하드 제한(예: 100만 토큰)보다 훨씬 일찍 **200K 토큰 전후**에서 성능 저하가 시작된다. 반복, 느린 추론, 품질 저하 등의 현상이 나타나는데, 이를 **Context Rot**이라고 부른다.

컨텍스트 엔지니어링은 바로 이 역설을 해결하기 위한 기술이다.

> 다음 단계를 위해 필요한 정확한 정보로 컨텍스트 윈도우를 채우는 섬세한 기술이자 과학

---

## 왜 파인튜닝이 아닌 컨텍스트 엔지니어링인가?

Manus의 Peak가 강조한 부분이 특히 공감됐다. 그는 10년 이상 NLP 분야에서 일하며 직접 언어 모델을 훈련시켰던 경험이 있는데, 그럼에도 불구하고 컨텍스트 엔지니어링을 선택한 이유가 명확했다.

![](https://i.imgur.com/2Iubp55.png)


### 첫 번째 함정: 모델 반복이 제품 반복을 제약한다

과거 그가 일했던 스타트업에서는 단일 훈련 및 평가 주기에 **1-2주**가 소요됐다. 이는 제품 혁신 속도를 완전히 제약했고, PMF를 찾기도 전에 벤치마크 개선에만 매달렸다.

```diff
- 모델 파인튜닝: 1-2주 훈련 주기 → 제품 개선 속도 제약
+ 컨텍스트 엔지니어링: 즉시 반영 → 빠른 제품 개선
```

### 두 번째 함정: AI 생태계는 하루아침에 바뀐다

MCP(Model Context Protocol) 출시가 대표적인 예다. Manus의 설계는 MCP 이후 완전히 바뀌었다:

- **이전**: 작고 정적인 액션 공간
- **이후**: 무한히 확장 가능한 형태

이런 오픈 도메인 문제를 파인튜닝으로 최적화하는 것은 거의 불가능하다.

> [!quote] Peak의 조언
>
> "일반화를 보장하는 후처리 훈련에 막대한 노력을 쏟는다면, 결국 스스로 LM 기업이 되려는 것과 마찬가지다. 이는 LLM 기업이 이미 구축한 계층을 다시 구축하는 중복된 노력이다."

컨텍스트 엔지니어링은 **애플리케이션과 모델 사이의 가장 명확하고 실용적인 경계선**이다.

---

## 컨텍스트 엔지니어링의 5가지 핵심 기법

LangChain의 Lance가 먼저 5가지 핵심 기법을 소개했다. 여러 프로덕션 에이전트(Manus, Claude Code, Open Deep Research 등)에서 공통적으로 사용하는 패턴들이다.

### 1. 컨텍스트 오프로딩 (Context Offloading)

모든 컨텍스트가 에이전트의 메시지 히스토리에 있을 필요는 없다. [[PostgreSQL 18 + pgvector를 활용한 블로그 벡터 검색 시스템 구축|벡터 데이터베이스를 활용한 검색 시스템]]처럼, 외부 저장소를 활용하는 것이 핵심이다.

```python
# 도구 출력을 파일 시스템에 저장
def search_web(query: str) -> str:
    result = web_search_api(query)  # 토큰이 많은 결과

    # 파일로 저장
    file_path = f"/tmp/search_results/{query_hash}.txt"
    save_to_file(file_path, result)

    # 에이전트에는 최소 정보만 반환
    return f"검색 결과가 {file_path}에 저장되었습니다. 필요시 파일을 읽어주세요."
```

**적용 사례**: Manus, LangChain Deep Agents, Open Deep Research, Claude Code

---

### 2. 컨텍스트 축소 (Context Reduction)

Manus에서 가장 혁신적인 부분이 바로 **압축(Compaction)**과 **요약(Summarization)**을 구분한 점이다.

![](https://i.imgur.com/P8J6mUy.png)

![](https://i.imgur.com/HFmwP0V.png)

#### 압축 (Compaction): 가역적 축소



```python
# 전체 형식
tool_call = {
    "function": "file_write",
    "arguments": {
        "path": "/home/ubuntu/foo.txt",
        "content": "Lorem ipsum dolor sit amet..."  # 매우 긴 내용
    }
}

# 압축 형식 (파일 시스템에서 재구성 가능)
compact_tool_call = {
    "function": "file_write",
    "arguments": {
        "path": "/home/ubuntu/foo.txt"
        # content 제거 - 필요시 파일을 다시 읽으면 됨
    }
}
```

핵심은 **가역성**이다. 에이전트는 연쇄적으로 예측을 수행하기 때문에, 어떤 과거 행동이 나중에 중요해질지 예측할 수 없다.

#### 요약 (Summarization): 비가역적 축소

압축만으로는 한계가 있다. 결국 요약이 필요한 시점이 오는데, Manus는 매우 신중하게 접근한다:

```python
# ❌ 자유 형식 요약 (정보 손실 위험)
summary = "위 작업들을 요약하면..."

# ✅ 구조화된 스키마 (안정적)
summary = {
    "modified_files": ["foo.txt", "bar.py"],
    "user_goal": "사용자 인증 기능 구현",
    "current_status": "로그인 API 완료, 회원가입 진행 중",
    "next_steps": ["비밀번호 암호화", "JWT 토큰 발급"]
}
```

> [!tip] 요약 프롬프트 설계 팁
>
> 자유 형식 요약 대신 **구조화된 스키마**를 사용하라. 여러 필드가 있는 양식을 정의하고 AI가 이를 채우도록 하면 출력이 안정적이며 반복 작업을 할 수 있다.

![](https://i.imgur.com/FMtMGtN.png)
![](https://i.imgur.com/lSZfq4O.png)


#### 전략: 압축 먼저, 요약은 나중에

> [!quote] Context Isolation
>
> "Do not communicate by sharing memory;
> 
> Instead, share memory by communicating."
> 
> [Share Memory By Communicating](https://go.dev/blog/codelab-share)

Manus의 컨텍스트 축소 전략:

1. **Pre-rot Threshold 설정** (128K-200K 토큰)
2. 임계값 도달 → **압축** 시도
3. 가장 오래된 도구 호출 50% 압축 (최신은 유지)
4. 여러 번 압축 후에도 효과 미미 → **요약**
5. 요약 시에도 마지막 몇 개는 전체 유지 (모델이 스타일 유지)

---

### 3. 컨텍스트 검색 (Context Retrieval)

두 가지 접근 방식이 있다:

1. **인덱싱 & 시맨틱 검색** (Cursor)
   - 벡터 인덱스 구축
   - 의미 기반 검색

2. **파일 시스템 & 간단한 검색** (Claude Code)
   - `glob`, `grep` 활용
   - 빠른 셋업

Manus는 샌드박스 환경 특성상 **grep/glob** 방식을 채택했다. 매번 새로운 세션이 시작되기 때문에 인덱스를 구축할 시간이 없기 때문이다.

---

### 4. 컨텍스트 격리 (Context Isolation)

다중 에이전트 시스템에서 가장 어려운 문제가 **정보 동기화**다. Cognition 블로그에서도 이를 경고했는데, 이는 고전적인 멀티프로세스/멀티스레드 조정 문제와 유사하다.

![](https://i.imgur.com/3rDhbRN.png)
![](https://i.imgur.com/sG4y0T3.png)


#### Go 언어의 지혜를 AI 에이전트에 적용

> [!quote] Go Concurrency Pattern
>
> "Do not communicate by sharing memory; instead, share memory by communicating."

이를 컨텍스트 엔지니어링에 번역하면:

- **Sharing Memory** → **Sharing Context**
- **Communicating** → **Message Passing**

#### 패턴 1: 통신을 통한 격리 (By Communicating)

```
Main Agent → "코드베이스에서 인증 로직 찾아줘" → Sub Agent
           ← "auth.py:42-87에서 발견" ←
```

- 하위 에이전트는 **독립된 컨텍스트**
- 짧고 명확한 지시에 적합
- Claude Code의 `task` tool이 이 패턴

#### 패턴 2: 메모리 공유를 통한 격리 (By Sharing Context)

```
Main Agent Context (전체 기록) → Fork → Sub Agent
                                       (동일 컨텍스트 + 다른 시스템 프롬프트)
```

- 복잡한 작업에 적합 (예: 심층 연구)
- 단점: KV 캐시 재사용 불가, 비용 증가

> [!warning] 컨텍스트 공유의 비용
>
> 각 하위 에이전트가 더 큰 입력을 미리 채워야 하므로 입력 토큰 비용이 증가한다. 또한 시스템 프롬프트와 액션 공간이 다르면 KV 캐시를 재사용할 수 없어 전체 비용을 지불해야 한다.

---

### 5. 컨텍스트 캐싱 (Caching Context)

Anthropic의 입력 캐싱(Input Caching) 같은 제공업체 기능을 활용한다. Manus는 KV 캐시 효율을 매우 중요하게 생각하는데, 이것이 오픈소스 모델 대신 frontier 모델을 사용하는 이유 중 하나다.

> 분산 KV 캐시는 오픈소스 솔루션으로 구현하기 매우 어렵다. 선두 LM 제공업체는 이에 대한 견고한 인프라를 가지고 있어, Manus 규모에서는 오히려 더 저렴할 때도 있다.

---

## Manus의 혁신: 계층형 액션 공간

Peak가 공개한 가장 흥미로운 내용이 바로 **계층형 액션 공간**이다. 도구 자체도 컨텍스트를 차지한다는 문제를 해결하기 위한 혁신적인 접근이다.

### 문제: 도구도 컨텍스트를 잡아먹는다

MCP를 통합하면서 발견한 문제:
- 컨텍스트에 **너무 많은 도구** 정의
- 모델이 혼란스러워짐
- 잘못된 도구나 존재하지 않는 도구 호출

일반적인 해법은 **동적 RAG on tool descriptions**인데, 두 가지 문제가 있다:
1. 도구 정의가 컨텍스트 앞부분 → **KV 캐시 초기화**
2. 제거된 도구가 히스토리에 남아 → **잘못된 호출 유도**

![](https://i.imgur.com/cqE9Cvf.jpeg)

![](https://i.imgur.com/93DQZ44.png)


### 해결책: 3계층 액션 공간

Manus는 세 가지 추상화 수준을 제공한다:

#### Level 1: 함수 호출 (Function Calling)

![](https://i.imgur.com/X3aeOSS.png)


```typescript
// 고정된 원자적 함수만 (10-20개)
const ATOMIC_FUNCTIONS = [
  'file_read',
  'file_write',
  'shell_execute',
  'browser_navigate',
  'search_web'
]
```

- 스키마 안전 (constraint decoding)
- 경계 명확
- 조합 가능
- 나머지는 모두 Level 2로 오프로드

#### Level 2: 샌드박스 유틸리티 (Sandbox Utilities)

![](https://i.imgur.com/ACpkjmJ.png)


Manus는 완전한 **VM 샌드박스** 내에서 실행된다:

```bash
# MCP를 CLI로 호출
$ manus-mcp-cli list-tools

# 다이어그램 렌더링
$ manus-render-diagram --input workflow.mmd --output diagram.png

# 음성 인식
$ manus-speech-to-text --audio recording.mp3
```

**장점**:
- 함수 호출 공간 건드리지 않음
- `--help`로 사용법 확인 가능
- 큰 출력은 파일로 저장 → `grep`, `cat`으로 처리
- MCP 도구를 함수 공간에 직접 주입 안함

> [!info] MCP 통합 전략
>
> MCP 도구를 함수 호출 공간에 직접 주입하지 않고, 샌드박스 내에서 CLI를 통해 호출한다. 이렇게 하면 모델의 함수 호출 공간을 건드리지 않고도 MCP의 모든 기능을 사용할 수 있다.

#### Level 3: 패키지 & API (Packages and APIs)

![](https://i.imgur.com/KK2pWe9.png)


```python
# 주식 분석 예시
def analyze_stock(symbol: str, period: str = "1y"):
    # 1년치 데이터 가져오기 (수천 개 데이터 포인트)
    data = finance_api.get_historical(symbol, period)

    # Python 런타임 메모리에서 계산
    analysis = {
        'mean': data.mean(),
        'volatility': data.std(),
        'trend': calculate_trend(data)
    }

    # 요약만 반환 (전체 데이터 X)
    return analysis
```

**적합한 시나리오**:
- 대량 데이터 처리
- 연쇄적 API 호출 (도시명 → ID → 날씨)
- Python 런타임 메모리 활용

**단점**: 스키마 안전성 보장 안됨 (코드에 대한 constraint decoding 어려움)

### 모델 관점에서의 단순함

![](https://i.imgur.com/fp2onh1.png)


놀라운 점은, 모델 관점에서는 이 세 가지 계층이 모두 **표준 함수 호출**을 통해 접근된다는 것:

![](https://i.imgur.com/yV63U8I.png)


```python
# 모델이 보는 인터페이스는 동일
shell(command="manus-mcp-cli list")  # Level 2
file_write(path="script.py", content="...")  # Level 1
shell(command="python script.py")  # Level 3 실행
```

- 캐시 친화적
- 직교성 (orthogonal)
- 모델이 이미 훈련된 방식

![](https://i.imgur.com/RfghUNU.png)


---

## 프롬프트 엔지니어링 vs 컨텍스트 엔지니어링: 패러다임의 전환

이 웨비나를 보면서 가장 크게 깨달은 점은, **프롬프트 엔지니어링과 컨텍스트 엔지니어링은 완전히 다른 차원의 문제**라는 것이다.

### 한 순간 vs 전체 여정

프롬프트 엔지니어링과 컨텍스트 엔지니어링의 핵심 차이를 한 문장으로 정리하면:

> [!info] 차이점의 본질
>
> - **프롬프트 엔지니어링**: 한 순간에 무엇을 말할 것인가
> - **컨텍스트 엔지니어링**: 전체 대화 여정에서 무엇을 기억하고 잊을 것인가

```diff
# 프롬프트 엔지니어링 (단일 호출)
- "당신은 전문 Python 개발자입니다. 다음 코드를 리팩토링해주세요..."
- Few-shot examples 추가
- Chain-of-thought 프롬프트

# 컨텍스트 엔지니어링 (다중 턴 관리)
+ 50번째 도구 호출 후에도 1번째 호출 기억할지?
+ 이전 검색 결과를 컨텍스트에 유지할지, 파일로 오프로드할지?
+ 100K 토큰 넘으면 압축할지, 요약할지?
+ 하위 에이전트에게 전체 컨텍스트 공유할지, 새로 시작할지?
```

### 왜 에이전트에서는 컨텍스트 엔지니어링이 필수인가

[[LLM Chain Chatbot + RAG|일반적인 챗봇]]은 단일 질의-응답 사이클이 주를 이룬다. 하지만 에이전트는 근본적으로 다르다:

```
챗봇: 사용자 질문 → 검색 → 답변 (끝)
              ↓
        컨텍스트 길이: ~10K 토큰

에이전트: 목표 설정 → 탐색 → 실행 → 검증 → 수정 → ...
              ↓      ↓      ↓      ↓      ↓
        컨텍스트 길이: 10K → 30K → 80K → 150K → 220K (위험!)
```

Anthropic의 연구에 따르면, **에이전트에 컨텍스트 엔지니어링을 적용하면 최대 54% 성능 향상**이 나타났다. 부가적인 최적화라기보다 에이전트가 제대로 작동하기 위한 전제 조건에 가깝다.

### 프롬프트 엔지니어링은 컨텍스트 엔지니어링의 부분집합

흥미로운 점은, 프롬프트 엔지니어링이 사라지는 것이 아니라는 것이다:

**컨텍스트 엔지니어링 = 프롬프트 엔지니어링 + 시간에 걸친 메모리 관리**

> [!tip] 내가 내린 결론
>
> 프롬프트 엔지니어링은 "지금 이 순간 어떻게 말할까"에 집중한다면, 컨텍스트 엔지니어링은 "긴 여정 동안 무엇을 기억하고 무엇을 잊을까"를 다룬다. 에이전트 시대에는 후자가 더 중요하다.

### 예시: 동일 프롬프트, 다른 컨텍스트 전략

같은 프롬프트라도 컨텍스트 전략에 따라 결과가 완전히 달라진다:

**시나리오**: "프로젝트의 모든 테스트 케이스를 실행하고 실패한 것을 고쳐라"

| 전략 | 50번째 도구 호출 시점 컨텍스트 | 결과 |
|------|---------------------------|------|
| **전략 없음** | 모든 도구 호출 + 결과 (200K+) | Context Rot 발생, 성능 저하 |
| **오프로드** | 테스트 결과 파일 경로만 유지 (80K) | 안정적, 필요시 재검색 |
| **압축+요약** | 최근 20개 + 요약 (50K) | 효율적, 일부 정보 손실 |
| **격리** | 하위 에이전트에 위임 → 메인은 요약만 (30K) | 깔끔, 병렬 처리 가능 |

이게 바로 프롬프트 엔지니어링과 컨텍스트 엔지니어링의 차이다. 프롬프트는 동일하지만, 컨텍스트 전략이 성패를 좌우한다.

---

## 계층형 도구 관리: MCP 시대의 혁신

Peak가 공개한 계층형 액션 공간이 내게 가장 혁신적으로 다가온 이유는, **도구 자체가 컨텍스트 문제의 원인이 될 수 있다**는 통찰 때문이다.

### 전통적인 도구 관리의 한계

MCP 이전에는 에이전트의 도구가 고정되어 있었다:

```python
# 전통적 방식: 모든 도구를 함수 호출 공간에 정의
TOOLS = [
    "file_read", "file_write", "search_web",
    "analyze_image", "transcribe_audio",
    "query_database", "send_email",
    "render_chart", "create_diagram",
    # ... 50개 이상
]
```

**문제점**:
1. **컨텍스트 오염**: 50개 도구 정의가 수천 토큰 차지
2. **모델 혼란**: 비슷한 도구 사이에서 선택 어려움
3. **스키마 복잡도**: 각 도구마다 인자, 반환값 정의
4. **확장성 제로**: 새 도구 추가할 때마다 전체 재정의

### MCP가 가져온 새로운 도전

MCP(Model Context Protocol)는 도구를 무한히 확장 가능하게 만들었다:

```bash
# 사용자가 원하는 MCP 서버를 자유롭게 추가
$ mcp install github-tools    # 30개 도구 추가
$ mcp install slack-tools      # 25개 도구 추가
$ mcp install aws-tools        # 100개 도구 추가
```

**역설**: 도구가 많아질수록 오히려 에이전트가 제 역할을 못 하는 경우가 생긴다.

> [!danger] 도구 공간 간섭 (Tool-space Interference)
>
> 도구 정의가 많아질수록:
> - 모델이 올바른 도구를 선택하기 어려워짐
> - 존재하지 않는 도구를 환각(hallucinate)
> - 잘못된 인자로 호출
> - KV 캐시 효율성 급감

### 일반적 해결책의 함정: 동적 RAG

가장 흔한 해결책은 **도구 설명에 RAG 적용**이다:

```python
# 사용자 질의에 맞는 도구만 동적으로 주입
query = "GitHub 이슈 생성"
relevant_tools = vector_search(query, all_tools)  # 5개만 선택
→ 함수 호출 공간에 5개만 제공
```

Peak가 지적한 **두 가지 치명적 문제**:

#### 문제 1: KV 캐시 무효화

```
Turn 1: [file_read, file_write, search_web]
        ↓ KV 캐시 생성

Turn 2: [github_create_issue, github_list_pr, slack_send]
        ↓ 도구 정의 변경 → 전체 KV 캐시 초기화!

Turn 3: [file_read, aws_s3_upload, ...]
        ↓ 또 초기화...
```

도구 정의는 컨텍스트 **앞부분**에 위치하므로, 변경될 때마다 전체 캐시가 무효화된다. 이는 엄청난 비용과 지연을 초래한다.

#### 문제 2: 히스토리 혼란

```
Turn 10: github_create_issue() 호출 성공
Turn 15: 도구 RAG가 GitHub 도구들 제거
         → 하지만 Turn 10 히스토리는 남아있음
Turn 20: 모델이 github_create_issue() 다시 호출 시도
         → 에러! "도구를 찾을 수 없음"
```

모델은 히스토리에서 성공한 도구 호출을 보고 다시 사용하려 하지만, 현재는 제거된 상태다.

### Manus의 해법: 3계층 추상화

Manus는 도구를 **3가지 추상화 수준**으로 분리했다. 이게 정말 영리한 이유는:

```
┌─────────────────────────────────────────────────┐
│  Level 1: 함수 호출 (Function Calling)          │  ← 고정, 캐시 친화적
│  ────────────────────────────────────           │
│  10-20개 원자적 함수만                          │
│  • file_read, file_write                        │
│  • shell_execute                                │
│  • browser_navigate                             │
└─────────────────────────────────────────────────┘
              ↓ offload
┌─────────────────────────────────────────────────┐
│  Level 2: 샌드박스 CLI (Sandbox Utilities)      │  ← MCP 여기 통합!
│  ────────────────────────────────────           │
│  shell_execute("manus-mcp-cli github ...")      │
│  • 함수 공간 건드리지 않음                      │
│  • --help로 사용법 조회 가능                    │
│  • 출력 → 파일 → grep/cat으로 처리              │
└─────────────────────────────────────────────────┘
              ↓ offload
┌─────────────────────────────────────────────────┐
│  Level 3: 패키지 & API (Packages/APIs)          │
│  ────────────────────────────────────           │
│  shell_execute("python analyze_stock.py AAPL")  │
│  • 대량 데이터 처리                             │
│  • 런타임 메모리 활용                           │
└─────────────────────────────────────────────────┘
```

### 왜 이게 혁신적인가?

#### 1. 함수 호출 공간 보호

**핵심**: Level 1만 모델의 함수 공간을 차지한다.

```typescript
// 모델이 보는 함수 정의 (10-20개만, 절대 변하지 않음)
{
  "name": "shell_execute",
  "description": "Execute a shell command in the sandbox",
  "parameters": {
    "command": "string"
  }
}
```

MCP 도구 100개를 추가해도, 모델이 보는 함수는 여전히 10-20개다!

```bash
# Level 2로 오프로드
$ shell_execute("manus-mcp-cli github create-issue --title 'Bug' --body '...'")
```

**결과**:
- ✅ KV 캐시 완벽 유지
- ✅ 도구 설명 토큰 10배 감소
- ✅ 모델 혼란 최소화

#### 2. 도구-as-문서 패턴

Level 2의 진짜 아름다움은 **자가 문서화**다:

```bash
# 모델이 모르면 직접 조회
$ shell_execute("manus-mcp-cli --help")

Available commands:
  github    - GitHub operations
  slack     - Slack messaging
  aws       - AWS resource management

$ shell_execute("manus-mcp-cli github --help")

GitHub operations:
  create-issue    Create a new issue
  list-pr         List pull requests
  ...
```

모델은 필요할 때 **런타임에 도구 사용법을 배운다**. 모든 것을 미리 컨텍스트에 넣을 필요가 없다!

> [!tip] 에이전트-as-도구 패턴
>
> Level 2는 사실상 "도구"가 아니라 "샌드박스 내 작은 에이전트"로 작동한다. `--help`를 보고, 파일을 읽고, 결과를 파일로 저장하는 자율적 유틸리티다. 이것이 MCP를 함수 호출 공간에 직접 주입하지 않고도 활용하는 핵심 전략이다.

#### 3. 도구 간섭 문제 해결

**전통 방식**:
```python
# 100개 도구가 한 공간에
tools = [github_create_issue, jira_create_issue, linear_create_issue, ...]
→ 모델: "이슈를 만들라고? 어느 도구...?"
```

**Manus 방식**:
```bash
# Level 1: 단순 명령
$ shell_execute("manus-mcp-cli github create-issue ...")

# CLI가 알아서 처리
# 모델은 선택 부담 없음
```

모델은 "이슈 생성"이라는 **의도**만 표현하면 되고, CLI 계층이 구체적 실행을 담당한다.

### 실전 예시: 주식 분석 에이전트

계층형 구조의 힘을 보여주는 예시:

```python
# 사용자: "애플 주식 작년 실적 분석해줘"

# Turn 1 (Level 1): 스크립트 작성
file_write(
    path="analyze_stock.py",
    content="""
import yfinance as yf
data = yf.download("AAPL", period="1y")  # 수천 행
analysis = {
    'mean': data['Close'].mean(),
    'volatility': data['Close'].std(),
    'return': (data['Close'][-1] / data['Close'][0] - 1) * 100
}
print(analysis)
"""
)

# Turn 2 (Level 3): 실행
result = shell_execute("python analyze_stock.py")
# 출력: {'mean': 178.32, 'volatility': 8.42, 'return': 12.4}

# 컨텍스트에 추가된 것: 단 3줄 요약!
# (수천 행 데이터는 Python 런타임 메모리에서만 처리)
```

**만약 Level 3 없이 Level 1만 있었다면**:
```python
# ❌ 이렇게 해야 했을 것
data = api_call_yahoo_finance("AAPL", "1y")
# → 수천 행이 컨텍스트에 추가됨
# → 250번의 도구 호출로 하나씩 계산
# → 200K 토큰 폭증
```

### 왜 이 접근이 내게 와닿았나

[[PostgreSQL 18 + pgvector를 활용한 블로그 벡터 검색 시스템 구축|내 프로젝트]]에서도 비슷한 문제를 겪었다. 처음에는 모든 기능을 LangChain 도구로 만들었는데, 도구가 20개를 넘어가자 모델이 혼란스러워했다.

Manus의 접근을 보고 깨달은 것:
- **모든 것을 도구로 만들 필요 없다**
- 복잡한 작업은 스크립트로 오프로드
- 모델에게는 단순한 인터페이스만

> [!quote] 내 인사이트
>
> 도구 관리도 컨텍스트 엔지니어링의 일부다. 도구 정의 자체가 귀중한 컨텍스트를 소모한다. Manus는 이를 계층화로 해결했고, 이는 MCP 시대에 필수적인 패턴이 될 것이다.

---

## 5가지 차원의 상호연결성

![](https://i.imgur.com/ZNtAvtO.png)



이 5가지 기법은 독립적이지 않다:

```
Offload + Retrieve → Reduction 가능
Reliable Retrieve → Isolation 가능
Isolation → Reduction 빈도 감소

↓

모두 Cache 최적화 하에서 작동
```

컨텍스트 엔지니어링은 서로 상충될 수 있는 여러 목표 사이의 **완벽한 균형**을 요구한다. 더 많은 격리와 축소는 캐시 효율성과 출력 품질에 영향을 미친다.

---

## 가장 중요한 교훈: 과잉 엔지니어링을 피하라

![](https://i.imgur.com/RfghUNU.png)

Peak의 마지막 조언이 가장 인상 깊었다:

> [!quote] Build less, understand more
>
> "Manus 출시 이후 지난 6-7개월 동안 가장 큰 발전은 더 정교한 컨텍스트 관리 계층이나 영리한 검색 해킹에서 온 것이 아니다. 아키텍처를 단순화하고 불필요한 트릭을 제거하며 모델을 조금 더 신뢰하는 것에서 비롯되었다."

```diff
- 정교한 컨텍스트 관리 계층
- 영리한 검색 해킹
+ 아키텍처 단순화
+ 불필요한 트릭 제거
+ 모델을 더 신뢰
```

**결과**: 더 빠르고, 더 안정적이며, 더 똑똑한 시스템

### 지속적인 아키텍처 진화

Manus는 3월 출시 이후 10월까지 **5번 리팩토링**했다. 모델은 단순히 개선될 뿐만 아니라 행동도 변화하기 때문이다.

**미래 대비 전략**:

1. **약한 모델 ↔ 강한 모델 전환 테스트**
   ```
   아키텍처 고정 → 모델만 바꿔가며 테스트
   ```

2. **이득 관찰**
   - 약한 모델 → 강한 모델에서 큰 이득
   - ⇒ 미래 대비 아키텍처
   - (내일의 약한 모델 = 오늘의 강한 모델)

3. **1-2개월마다 재검토**

---

## 실전 인사이트: Q&A에서 배운 것들

웨비나 Q&A 세션에서 나온 실용적인 팁들을 정리했다.

### 데이터 저장 형식

> [!tip] 라인 기반 형식 우선
>
> 일반 텍스트나 마크다운보다 **라인 기반 형식**(line-based formats)을 우선시하라. 모델이 `grep`을 사용하거나 특정 범위의 라인에서 읽을 수 있도록 허용하기 때문이다.

마크다운 문제: 어떤 모델은 마크다운을 너무 자주 사용하면 글머리 기호를 남발하는 경향이 있다.

### 다중 에이전트 설계 원칙

Manus의 에이전트 구조:

```
거대한 General Executor Agent  (메인)
    ├── Planner Agent
    ├── Knowledge Management Agent
    └── Data API Registration Agent
```

**역할 기반 분할을 지양**하라:
```diff
- Designer Agent / Programming Agent / Manager Agent
+ 소수의 기능 중심 에이전트
```

> 역할 분할은 인간 회사의 작동 방식에서 비롯된 것이며, 인간 컨텍스트의 한계 때문이다. AI는 다르게 접근해야 한다.

### 에이전트 간 통신

Manus Wide Research (내부명: Agentic Map-Reduce):

1. **샌드박스 공유**: 파일 시스템을 공유하여 경로만 전달
2. **출력 스키마 정의**: 메인 에이전트가 하위 에이전트의 출력 스키마 정의
3. **제약 디코딩**: `submit_result` 도구로 스키마 준수 보장

결과: 스프레드시트 같은 구조화된 데이터

### 평가 전략

Manus의 3가지 평가 방식:

1. **사용자 피드백** ⭐ (골드 스탠다드)
   - 모든 세션에 1-5점 별점
   - 평균 사용자 평점 최우선

2. **내부 자동화 테스트**
   - 명확한 답변 있는 자체 데이터셋
   - **실행 중심 벤치마크** (기존 벤치마크는 reasoning 중심)
   - 샌드박스로 환경 초기화 가능

3. **인간 평가** (인턴 활용)
   - 웹사이트 디자인, 데이터 시각화
   - "시각적 매력도" 같은 주관적 요소

> [!warning] 공공 벤치마크의 함정
>
> Gaia 같은 공공 학술 벤치마크에서 높은 점수를 받은 모델을 사용자들은 좋아하지 않았다. 정적 벤치마크 성능에는 신경 쓰지 말라.

---

## 내가 적용할 것들

이 웨비나를 듣고  [[2025-10-06-AppHub-개인-프로젝트-플랫폼-기획|현재 진행 중인 프로젝트]] 와 향후 프로젝트들에 적용할 수 있는 아이디어들을 정리했다:

- [ ] **컨텍스트 압축 우선, 요약은 최후 수단**
  - 가역적 압축 구현 (파일 경로만 남기기)
  - 요약 시 구조화된 스키마 사용

- [ ] **도구 수 30개 이하 유지**
  - 원자적 함수만 직접 노출
  - 나머지는 셸 명령이나 스크립트로

- [ ] **다중 에이전트 신중하게 사용**
  - 역할 분할 대신 기능 중심
  - "도구로서의 에이전트" 패턴 활용

- [ ] **1-2개월마다 아키텍처 단순화 검토**
  - 약한 모델 ↔ 강한 모델 전환 테스트
  - 불필요한 레이어 제거

- [ ] **사용자 피드백을 골드 스탠다드로**
  - 벤치마크 성능보다 실제 사용자 만족도

---

## 마치며

컨텍스트 엔지니어링의 핵심은 **단순함**이다.

```
목표: 모델의 작업을 더 단순하게 만들기
수단: 덜 구축하고, 더 이해하기
결과: 더 빠르고, 안정적이며, 똑똑한 시스템
```

Peak의 말처럼, "모든 것이 하루아침에 바뀔 수 있는" AI 분야에서는 모델에 너무 많은 것을 하드코딩하기보다 컨텍스트 엔지니어링으로 유연성을 확보하는 것이 중요하다.

앞으로 에이전트 시스템을 설계할 때 잊지 않으려는 원칙은, 파인튜닝에 매달리기보다 컨텍스트 엔지니어링으로 유연성을 확보하고, 복잡한 계층을 쌓기보다 아키텍처를 단순하게 유지하자는 것이다. 기능을 늘리는 것보다 핵심 기능이 잘 작동하는지, 벤치마크 점수보다 실제 사용자가 만족하는지를 먼저 보려고 한다.

> [!quote]
>
> "Build less, understand more."

---

## 참고자료

- [Manus 블로그: Context Engineering for AI Agents](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)
- [LangChain × Manus Webinar (YouTube)](https://youtu.be/6_BcCthVvb8?si=XYBVPnXM9IZH8dRd)
- [Go Concurrency Patterns](https://go.dev/blog/codelab-share)
