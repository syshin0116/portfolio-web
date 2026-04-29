---
title: "misen: 재사용 가능한 AI 워크플로우 블록 라이브러리"
date: 2026-04-04
tags:
  - Python
  - AI
  - Pipeline
  - Workflow
  - Open Source
draft: false
enableToc: true
description: AI 파이프라인의 반복되는 작업을 블록 단위로 정의하고, 조합하고, 어디서든 재사용할 수 있게 하는 Python 라이브러리
summary: "misen(mise en place)은 AI 워크플로우의 반복되는 작업 단위를 블록으로 정의하고, 다양한 방식으로 조합하며, 어떤 플랫폼에서든 재사용할 수 있게 하는 Python 라이브러리다. 핵심은 `Block(dict → dict)` 단일 인터페이스와 연산자 기반 조합."
published: 2026-04-04
modified: 2026-04-04
---
## 왜 만들었나

AI 에이전트 시스템을 여러 프로젝트에서 개발하다 보면, 같은 작업이 반복된다.

```
프로젝트 A:  HWP 파싱 → 청킹(semantic) → 임베딩(KURE-v1) → Qdrant 저장
프로젝트 B:  PDF 파싱 → 청킹(semantic) → 임베딩(KURE-v1) → Qdrant 저장
프로젝트 C:  문서 파싱 → 요구사항 추출 → 분석
```

청킹, 임베딩, 벡터 저장은 거의 같은 로직인데 프로젝트마다 따로 구현된다. 한쪽에서 개선해도 다른 쪽에 반영되지 않는다.

여기에 세 가지 문제가 더 있다:

1. **플랫폼 종속** - LangGraph에서 만든 파이프라인은 LangGraph에서만 돌아간다. n8n, MCP, FastAPI에서 쓰려면 다시 짜야 한다.
2. **고정과 유동의 혼합이 어렵다** - "반드시 이 순서대로"(파싱→청킹→임베딩)와 "LLM이 알아서 선택"(문서 유형에 따라 분석 방법 결정)을 하나의 파이프라인에서 자연스럽게 섞는 방법이 없다.
3. **재사용 단위가 불명확** - Tool(원자적 함수)과 Skill(프롬프트 확장)을 조합해서 더 큰 단위를 만들고, 그걸 다시 다른 곳의 재료로 쓰는 체계가 없다.

## 핵심 아이디어

> **한 번 정의한 작업 블록을, 다양한 방식으로 조합하고, 어떤 플랫폼에서든 재사용한다.**

### Block = `dict → dict`

모든 것의 기본 단위. Unix pipe가 `text → text`로 수십 년간 확장된 것처럼, misen은 `dict → dict`로 통일한다.

```python
from misen import tool

@tool
def parse(input: dict) -> dict:
    return {"text": open(input["file"]).read(), "metadata": {...}}

@tool
def chunk(input: dict) -> dict:
    return {"chunks": split_text(input["text"])}
```

Tool이든, Skill이든, Pipeline이든 전부 Block이다. 모든 Block은 같은 인터페이스를 가지므로:

- 어떤 Block이든 조합 가능
- 조합 결과도 Block → 다시 다른 조합의 재료가 됨 (닫힘 성질)

### 연산자로 조합

Block을 연산자로 조합한다. 연산자의 결과도 Block이므로, 중첩이 자유롭다.

```python
from misen import sequential, parallel

# 순차 실행
ingest = sequential(parse, chunk, embed, save)

# 병렬 실행
analysis = parallel(extract_metadata, generate_summary)

# 중첩
pipeline = sequential(
    ingest,
    parallel(extract_metadata, generate_summary),
)

# 파이프 문법도 지원
pipeline = parse | chunk | embed | save
```

| 연산자 | 설명 | 상태 |
|---|---|---|
| `sequential(A, B, C)` | A → B → C 순차 실행 | Phase 1 구현 완료 |
| `parallel(A, B)` | 동시 실행, 결과 merge | Phase 1 구현 완료 |
| `guided(prompt, [A,B,C])` | LLM이 선택지 중 고름 | Phase 2 예정 |
| `free(prompt, tools=[...])` | LLM에게 완전 위임 | Phase 2 예정 |
| `branch(condition, A, B)` | 조건 분기 | Phase 2 예정 |
| `loop(A, until=condition)` | 반복 | Phase 2 예정 |

### 플랫폼 독립

코어는 플랫폼을 모른다. 어댑터가 변환을 담당한다.

```
misen Block (dict → dict)
    ├── LangGraph 어댑터 → LangGraph 노드로 동작
    ├── MCP 어댑터 → MCP tool로 노출
    ├── FastAPI 어댑터 → REST API endpoint
    └── n8n 어댑터 → HTTP 호출 가능
```

## 아키텍처

```
misen/
├── core/                    ← Pure Python, 외부 의존성 없음
│   ├── block.py             # Block ABC, @tool 데코레이터
│   ├── operators.py         # sequential, parallel
│   └── runner.py            # 실행 엔진 (async)
├── tools/                   ← 기본 제공 블록
│   ├── text_splitter.py
│   └── transformer.py
└── adapters/                ← 플랫폼 연동 (Phase 4)
```

### Rust vs Python

| 영역 | 언어 | 이유 |
|---|---|---|
| core (block, operators, runner) | **Python** | 오케스트레이션 로직, CPU-bound 아님. 영구 Python. |
| adapters | **Python** | 플랫폼 연동, I/O 위주 |
| text_splitter, token_counter | Python → **Rust** | 대용량 배치 시 10x 성능. PyO3+maturin으로 배포. |
| parsehwp | **Rust** | 바이너리 포맷 파싱, 메모리 안전성 |

원칙: **코어는 영원히 Python.** Rust는 CPU-bound 데이터 처리 도구에만 적용하며, 없으면 Python fallback으로 동작한다.

```python
# Rust 연동 패턴
try:
    from parsehwp import parse      # Rust 버전
except ImportError:
    from ._fallback import parse    # Python fallback
```

## 사용법

### 설치

```bash
pip install misen             # core만
pip install misen[langgraph]  # + LangGraph 어댑터 (Phase 4)
```

### 블록 정의

```python
from misen import tool

# 함수를 블록으로
@tool
def parse_document(input: dict) -> dict:
    text = read_file(input["file_path"])
    return {"text": text, "metadata": extract_metadata(text)}

# async도 가능
@tool
async def embed(input: dict) -> dict:
    vectors = await embedding_api(input["chunks"])
    return {"vectors": vectors}
```

### 블록 조합

```python
from misen import sequential, parallel

# 순차 파이프라인
ingest = sequential(parse_document, chunk, embed, save_to_db)

# 병렬 분석
analysis = parallel(extract_keywords, generate_summary)

# 파이프 문법
ingest = parse_document | chunk | embed | save_to_db

# 중첩 - 파이프라인도 블록이므로 재사용 가능
qa_pipeline = sequential(
    ingest,           # 이미 정의된 파이프라인
    search,
    generate_answer,
)
```

### 실행

```python
# async
result = await pipeline.run({"file_path": "document.hwp"})

# sync (편의 메서드)
result = pipeline.run_sync({"file_path": "document.hwp"})

# runner 모듈
from misen import run, run_sync
result = await run(pipeline, {"file_path": "document.hwp"})
```

### 기본 제공 도구

```python
from misen.tools import TextSplitter, Transformer

# 텍스트 청킹
splitter = TextSplitter(chunk_size=1000, overlap=200)

# 변환기
upper = Transformer(str.upper, input_key="text")
counter = Transformer(len, input_key="chunks", output_key="chunk_count")

# 조합
pipeline = splitter | counter
result = pipeline.run_sync({"text": long_text})
# → {"chunks": [...], "chunk_count": 5}
```

## 설계 결정

### Sequential의 누적 dict 패턴

Sequential은 각 블록의 output을 input에 merge하며 체인한다. 모든 하위 블록이 upstream 결과에 접근할 수 있다.

```python
# parse가 {"text": "..."} 출력
# chunk가 input["text"]를 읽어 {"chunks": [...]} 출력
# embed가 input["chunks"]를 읽어 {"vectors": [...]} 출력
pipeline = sequential(parse, chunk, embed)
```

공유 State(LangGraph 방식) 대신 독립 입출력을 선택한 이유: Block이 특정 키에 종속되면 재사용성이 떨어진다.

### Parallel의 충돌 전략

두 블록이 같은 키를 출력하면?

```python
# "last" (기본) - 나중 블록이 이김
parallel(block_a, block_b)

# "first" - 먼저 블록이 이김
parallel(block_a, block_b, conflict="first")

# "error" - 에러 발생
parallel(block_a, block_b, conflict="error")
```

### Config vs Input

- **Config** = 생성자 인자 (정적 설정): `TextSplitter(chunk_size=1000)`
- **Input** = `run()` 인자 (런타임 데이터): `{"text": "..."}`

## 테스트

```bash
# 프로젝트 클론 후
git clone https://github.com/syshin0116/misen.git
cd misen

# 가상환경 + 설치
uv venv .venv && source .venv/bin/activate
uv pip install -e ".[dev]"

# 테스트 실행
pytest tests/ -v
```

현재 46개 테스트 전부 통과:

- Block ABC, FunctionBlock, @tool 데코레이터
- Sequential 체이닝 + 누적 dict
- Parallel 동시 실행 + 충돌 전략 3가지
- 연산자 문법 (`|`, `&`) + 자동 flatten
- 연산자 중첩 (Sequential 안에 Parallel 등)
- TextSplitter, Transformer 통합 파이프라인

## 로드맵

| Phase | 내용 | 상태 |
|---|---|---|
| 1 | Block 프로토콜 + sequential/parallel + 기본 Tool | **완료** |
| 2 | guided/free 연산자, branch/loop/map, Registry | 예정 |
| 3 | YAML 파이프라인 정의, 입출력 매핑 | 예정 |
| 4 | LangGraph/MCP/FastAPI 어댑터 | 예정 |
| 5 | Rust Tool 통합, CLI, 로깅/추적 | 미래 |

## 영감

| 출처 | 영향 |
|---|---|
| **Unix pipe** | `dict → dict` 단일 인터페이스, 조합의 철학 |
| **mise en place** | 재료를 미리 준비하고 배치하는 원칙 |
| **LangGraph subgraph** | 그래프를 노드로 중첩하는 패턴 |
| **DSPy** | 모듈의 선언적 정의와 조합 |
| **Claude Agent Skill** | progressive disclosure, lazy 로딩 |

---

*GitHub: [syshin0116/misen](https://github.com/syshin0116/misen)*
