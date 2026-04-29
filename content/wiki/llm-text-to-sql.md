---
title: "LLM Text-to-SQL 실전 패턴"
type: pattern
tags:
  - text-to-sql
  - llm
  - ai
  - agent
  - postgresql
  - prompt-engineering
  - evaluation
  - security
sources:
  - content/AI/2026-04-19-LLM-Text-to-SQL-실전-가이드.md
summary: "LLM 기반 Text-to-SQL 시스템을 프로덕션에서 안정적으로 운영하려면 프롬프트 튜닝보다 DB 스키마 품질이 결정적 요소다. 동적 스키마 조회, COMMENT 기반 zero-shot, AST 검증 기반 보안 레이어, 에이전트 위임 방식 self-correction을 조합하면 OLTP 수준 질의에서 높은 정확도를 달성할 수 있다."
created: 2026-04-25
updated: 2026-04-26
author: wiki-curator
draft: false
---

## Key Claims

- DB의 `COMMENT ON TABLE/COLUMN`이 few-shot 예시보다 Text-to-SQL 정확도에 더 큰 영향을 미친다. 특히 "이 컬럼은 어떤 질문에 쓰인다"와 "비슷한 컬럼과 어떻게 다른지"를 명시할 때 효과가 크다.[^1]
- 스키마를 프롬프트에 하드코딩하면 DB 마이그레이션 때마다 수동 업데이트가 필요하고, 스키마 drift가 런타임 에러로 이어진다. LLM이 `pg_catalog`에서 런타임에 직접 조회하게 만들면 방지할 수 있다.[^1]
- 복잡한 JOIN 패턴은 View로 미리 만들어두면 few-shot 예시보다 유지보수와 정확도 모두 낫다.[^1]
- few-shot은 COMMENT 보강과 View 생성으로 해결이 안 될 때의 최후 수단이다. 유지보수 비용, 과적합 위험, 토큰 낭비가 단점이다.[^1]
- 보안은 단일 레이어로 부족하다: LLM refusal → AST 기반 SQL Validator → READ ONLY 트랜잭션 → Row-Level Security → 출력 cap. 실행 비용 방어(`statement_timeout`)도 별도로 필요하다.[^1]
- Self-correction은 구문 오류나 불허 함수 같은 기계적 에러에는 효과적이지만, 도메인 의미 해석 오류(잘못된 컬럼 선택)에는 한계가 있다. 후자는 스키마 품질로 선제 대응해야 한다.[^1]
- 52문항 5모델 eval 결과: gpt-5.4 98%, gemini-3.1-pro 93%, 모든 모델이 zero-shot에서 1-shot 성공률 80% 이상을 기록했다.[^1]

## Examples / Code

**동적 스키마 조회 흐름 (from source)**

```
사용자 자연어 질문
      │
LLM Agent
      │  ① list_tables()        ← COMMENT 있는 테이블만 반환
      │  ② describe_tables()    ← 컬럼, 타입, FK, ENUM, COMMENT 반환
      │  ③ SQL 생성
      ▼
SQL Validator (pglast)          ← AST 파싱, allowlist, LIMIT cap
      │
PostgreSQL (READ ONLY + RLS + 출력 cap)
```

**COMMENT 작성 패턴 (from source)**

```sql
COMMENT ON COLUMN opportunities.start_date IS
  '사업 시작일(예정). "시작한 날짜", "착수일" 질문에 사용.
   created_at(레코드 생성 시점)과 혼동 주의.';
```

**AST 기반 SQL Validator 핵심 로직 (from source)**

```python
from pglast import parse_sql
from pglast.ast import SelectStmt

class SqlValidator:
    def validate(self, sql: str) -> ValidationResult:
        stmts = parse_sql(sql)
        if len(stmts) != 1:
            return REJECT("Multiple statements")
        if not isinstance(stmts[0].stmt, SelectStmt):
            return REJECT("Only SELECT/WITH allowed")
        # 테이블 allowlist, 함수 allowlist, 스키마 제한, LIMIT cap
        return ACCEPT(sanitized_sql)
```

**Self-correction 위임 패턴 (from source)**

```python
@tool
async def query_business_db(sql: str) -> str:
    result = validator.validate(sql)
    if not result.valid:
        return json.dumps({"error": result.error, "sql": sql})
    # 실행 후 결과 또는 에러 JSON 반환
```

**우선순위 (from source)**

```
COMMENT 보강 → View 생성 → few-shot 추가
```

## Connections

- [[블로그-검색-실험]] - 같은 AI 시스템 품질 평가 문제를 검색 방법론 측면에서 다룬다

## Footnotes

[^1]: content/AI/2026-04-19-LLM-Text-to-SQL-실전-가이드.md
