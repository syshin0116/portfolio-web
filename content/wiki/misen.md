---
title: "misen"
type: tool
tags:
  - python
  - ai
  - llm
  - pipeline
  - workflow
  - open-source
  - library
  - agent
  - operator
sources:
  - content/Projects/misen/2026-04-04-misen-overview.md
summary: "misen(mise en place)은 AI 워크플로우의 반복 작업을 Block(dict→dict) 단일 인터페이스로 정의하고 연산자로 조합해 어떤 플랫폼에서든 재사용할 수 있게 하는 Python 라이브러리다. 조합의 결과도 Block이므로 중첩이 자유롭고(닫힘 성질), 플랫폼 어댑터가 LangGraph, MCP, FastAPI 변환을 담당한다."
created: 2026-04-25
updated: 2026-04-26
author: wiki-curator
draft: false
---

## Key Claims

- 모든 Block은 `dict → dict` 인터페이스를 구현한다. Tool이든 Skill이든 Pipeline이든 동일하므로 어떤 Block이든 조합 가능하고, 조합 결과도 다시 Block으로 재사용된다(닫힘 성질).[^1]
- Sequential 연산자는 각 블록의 output을 input에 누적 merge하며 체인한다. 공유 State 대신 독립 입출력을 선택해 각 Block이 특정 키에 종속되지 않도록 했다.[^1]
- Parallel 연산자는 동일 키 충돌 전략을 `"last"(기본)`, `"first"`, `"error"` 세 가지로 설정 가능하다.[^1]
- core는 영원히 Pure Python으로 유지한다. Rust는 CPU-bound 데이터 처리(텍스트 청킹, 토큰 카운팅, HWP 파싱 등)에만 적용하며 Python fallback을 함께 제공한다.[^1]
- Phase 2에서 `guided(prompt, [A,B,C])`(LLM이 선택지 중 고름), `free(prompt, tools=[...])`(LLM에 완전 위임) 연산자가 추가될 예정이다.[^1]
- Config는 생성자 인자(정적 설정), Input은 `run()` 인자(런타임 데이터)로 명확히 분리한다.[^1]

## Examples / Code

**@tool 데코레이터와 Block 정의 (from source)**

```python
from misen import tool

@tool
def parse(input: dict) -> dict:
    return {"text": open(input["file"]).read(), "metadata": {...}}

@tool
def chunk(input: dict) -> dict:
    return {"chunks": split_text(input["text"])}
```

**연산자 조합 (from source)**

```python
from misen import sequential, parallel

# 순차 파이프라인 — 파이프 문법도 동일
ingest = parse | chunk | embed | save

# 병렬 실행
analysis = parallel(extract_metadata, generate_summary)

# 중첩 — 파이프라인도 Block이므로 재사용 가능
qa_pipeline = sequential(
    ingest,
    search,
    generate_answer,
)
```

**Rust 연동 fallback 패턴 (from source)**

```python
try:
    from parsehwp import parse      # Rust 버전
except ImportError:
    from ._fallback import parse    # Python fallback
```

**아키텍처 레이아웃 (from source)**

```
misen/
├── core/          # Pure Python, 외부 의존성 없음
│   ├── block.py
│   ├── operators.py
│   └── runner.py
├── tools/         # 기본 제공 블록
└── adapters/      # 플랫폼 연동 (Phase 4)
```

**연산자 로드맵 (from source)**

| 연산자 | 설명 | 상태 |
|---|---|---|
| `sequential(A, B, C)` | A → B → C 순차 실행 | Phase 1 완료 |
| `parallel(A, B)` | 동시 실행, 결과 merge | Phase 1 완료 |
| `guided(prompt, [A,B,C])` | LLM이 선택지 중 고름 | Phase 2 예정 |
| `free(prompt, tools=[...])` | LLM에게 완전 위임 | Phase 2 예정 |
| `branch(condition, A, B)` | 조건 분기 | Phase 2 예정 |
| `loop(A, until=condition)` | 반복 | Phase 2 예정 |

## Connections

## Footnotes

[^1]: content/Projects/misen/2026-04-04-misen-overview.md
