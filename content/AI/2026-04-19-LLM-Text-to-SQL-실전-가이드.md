---
title: 'LLM Text-to-SQL 실전 가이드 — 스키마 설계부터 Eval까지'
date: 2026-04-19
tags:
  - text-to-sql
  - llm
  - agent
  - postgresql
  - prompt-engineering
  - evaluation
  - langsmith
draft: false
enableToc: true
description: 프로덕션 환경에서 LLM 기반 Text-to-SQL을 구축하면서 배운 것들. 동적 스키마 조회, COMMENT 기반 zero-shot, 보안 레이어, 그리고 52문항 5모델 Eval 결과까지 정리한다.
summary: "LLM에게 자연어를 SQL로 바꾸게 하는 건 쉬워 보이지만, 프로덕션에서 안정적으로 동작하게 만드는 건 전혀 다른 문제다. 동적 스키마 조회, COMMENT 기반 zero-shot, AST 기반 보안 검증, 그리고 52문항 5모델 벤치마크까지 — 실제 구축 과정에서 얻은 교훈을 정리한다."
published: 2026-04-19
modified: 2026-04-19
---
## TL;DR

- 정확도는 프롬프트 튜닝이 아니라 **DB COMMENT**와 **View**에서 가장 크게 올라갔다
- 보안은 LLM의 거절에 기대지 말고, **DB 레이어까지 내려가서** 방어해야 한다
- few-shot은 기본 전략이 아니라 **마지막 수단**이었다

## 들어가며

"수주완료된 사업기회가 총 몇 건이야?"

이런 질문에 LLM이 알아서 SQL을 생성하고, DB에서 결과를 가져오고, 자연어로 답해주는 시스템을 만들었다.

처음에는 "프롬프트에 스키마 넣고 SQL 생성하면 되지"라고 가볍게 생각했는데, 프로덕션에서 돌려보니 훨씬 많은 것들을 고려해야 했다.

이 글에서는 실제 프로덕션 Text-to-SQL 시스템을 구축하면서 겪은 시행착오와 설계 판단을 공유한다. 비즈니스 DB(20+ 테이블, 500+ 레코드) 대상으로 OLTP 단건/집계 질의를 처리하는 시스템이며, 무거운 분석성 질의나 대규모 데이터 웨어하우스는 대상이 아니다.

---

## 전체 아키텍처

### 전체 흐름

```
사용자 자연어 질문
      │
      ▼
┌─────────────┐
│  LLM Agent  │
│  (DeepAgent) │
└──────┬──────┘
       │  ① list_tables()
       ▼
┌──────────────┐    pg_catalog에서
│  테이블 목록  │ ◄─ COMMENT 있는 테이블만 반환
└──────┬───────┘
       │  ② describe_tables([names])
       ▼
┌──────────────┐    컬럼, 타입, FK,
│  스키마 상세  │ ◄─ ENUM 값, COMMENT 반환
└──────┬───────┘
       │  ③ LLM이 SQL 생성
       ▼
┌──────────────┐
│ SQL Validator │ ◄─ AST 파싱, allowlist, LIMIT cap
│   (pglast)   │
└──────┬───────┘
       │  통과 시
       ▼
┌──────────────┐
│  PostgreSQL  │ ◄─ READ ONLY + RLS + 출력 cap
│  (실행)      │
└──────┬───────┘
       │
       ▼
  JSON 결과 → LLM이 자연어로 답변
```

핵심은 LLM이 스키마를 **추측하지 않고 직접 확인한 뒤** SQL을 작성한다는 것이다.

eval에서도 모든 성공 건이 `list_tables → describe_tables → query_business_db` 순서를 따르는 보수적 패턴을 보였다.

### 왜 하드코딩이 아니라 동적 조회인가?

초기 버전에서는 스키마를 문자열로 하드코딩해서 프롬프트에 넣었다:

```python
DB_SCHEMA_DESCRIPTION = """
opportunities 테이블:
  - id (uuid): PK
  - name (varchar): 사업기회명
  - budget_amount (bigint): 예산
  ...
"""
```

문제:
- DB 마이그레이션할 때마다 코드도 수동 업데이트해야 함
- 빠뜨리면 LLM이 없는 컬럼으로 SQL을 생성 → 런타임 에러
- 테이블이 늘어나면 프롬프트 토큰이 계속 증가

동적 조회로 바꾸니:
- `COMMENT ON TABLE/COLUMN`만 갱신하면 LLM이 자동으로 최신 스키마를 인식
- 필요한 테이블만 선택적으로 조회하니 토큰 효율적
- **스키마가 곧 문서**가 되어 유지보수 포인트가 하나로 수렴

> **Takeaway**: 스키마를 프롬프트에 하드코딩하지 마라. LLM이 런타임에 직접 조회하게 만들면 스키마 drift를 원천 차단할 수 있다.

---

## 핵심 교훈: 스키마가 왕이다

Text-to-SQL 정확도를 올리는 가장 효과적인 방법은 few-shot 예시 추가도, 프롬프트 튜닝도 아니었다.

**테이블과 컬럼 이름을 명확하게 짓고, COMMENT를 빈틈없이 다는 것**이 압도적으로 효과가 좋았다.

### COMMENT가 곧 프롬프트다

PostgreSQL의 `COMMENT ON` 구문이 LLM의 유일한 스키마 정보원이다:

```sql
COMMENT ON TABLE opportunities IS
  '사업기회(영업 건). 영업→입찰→계약→수행 4단계.';

COMMENT ON COLUMN opportunities.sales_status_code IS
  '영업상태코드. 값: SALS_RGSN(영업등록), BID_PRPS(입찰제안),
   BID_RVW_CMPL_RODR(수주완료), BID_RVW_CMPL_FODR(실주).
   한글명은 sales_status_name 참조.';

COMMENT ON COLUMN opportunities.start_date IS
  '사업 시작일(예정). "시작한 날짜", "착수일" 질문에 사용.
   created_at(레코드 생성 시점)과 혼동 주의.';
```

마지막 예시가 중요하다.

eval 초기에 "2024년에 시작한 사업기회"를 물었을 때, LLM이 `start_date` 대신 `created_at`을 사용해서 0건을 반환하는 실패가 있었다. COMMENT에 **"이 컬럼은 이런 질문에 쓴다"**는 힌트를 명시적으로 추가하니 해결됐다.

### 프로젝트 진행에 따른 변화

COMMENT 보강이 정확도에 효과가 있었다는 건 확실하지만, 정직하게 말하면 정량적인 전후 비교는 어렵다. 프로젝트가 진행되면서 COMMENT 수만 바뀐 게 아니라 데이터셋, 모델, 평가 방식도 함께 바뀌었기 때문이다.

대략적인 타임라인:
1. **초기** — 3개 테이블 하드코딩, COMMENT ~15개. 체감 정확도 60-70% (정식 eval 없음)
2. **동적 조회 전환** — COMMENT ~80개로 확대. 14문항 수동 테스트에서 mini 기준 86%
3. **대규모 보강** — COMMENT 170개. 52문항 LangSmith eval에서 mini 84%, gpt-5.4 98%

각 단계에서 문항 수도, 난이도 분포도, 채점 방식도 다르기 때문에 숫자를 직접 비교하는 건 무리다.

다만 확실히 말할 수 있는 건, COMMENT를 채울수록 **LLM이 추측에 의존하는 빈도가 눈에 띄게 줄었다**는 것이다. 특히 원가 서브시스템(costs, manpower_plans, materials, expenses) 50+ 컬럼의 COMMENT를 전부 채운 뒤로는 도메인 매핑 실패가 거의 사라졌다.

### ENUM 값은 COMMENT에 명시

LLM이 `WHERE industry_type_code = 'MANUFACTURING'`을 정확하게 생성하려면, 유효한 값 목록을 알아야 한다.

PostgreSQL ENUM 타입은 `describe_tables`에서 자동으로 `enum_values`로 반환되고, VARCHAR 기반 코드 컬럼은 COMMENT에 유효값을 나열했다.

eval에서 LLM은 COMMENT의 enum 설명을 그대로 가져다 썼다. `sales_status_code='BID_RVW_CMPL_RODR'`(수주완료) 같은 직관적이지 않은 코드도 few-shot 없이 정확하게 매핑했다.

> **Takeaway**: COMMENT의 품질이 곧 SQL의 품질이다. 특히 "이 컬럼에 어떤 값이 들어가는지"와 "비슷한 컬럼과 어떻게 다른지"를 명시하는 게 효과가 크다.

---

## 복잡한 JOIN은 View로

LLM이 매번 3-4개 테이블을 JOIN하는 SQL을 정확하게 생성하기란 어렵다.

자주 쓰이는 복잡한 JOIN 패턴이 있다면 **미리 View를 만들어두는 것**이 few-shot보다 효과적이다.

```sql
CREATE VIEW v_opportunity_summary AS
SELECT
    o.id,
    o.name,
    o.client_name,
    o.budget_amount,
    o.sales_status_name,
    COUNT(om.*) AS member_count,
    p.total_amount AS project_amount
FROM opportunities o
LEFT JOIN opportunity_members om ON om.opportunity_id = o.id
LEFT JOIN projects p ON p.opportunity_id = o.id
  AND p.is_representative = true
GROUP BY o.id, p.id;

COMMENT ON VIEW v_opportunity_summary IS
  '사업기회 요약 뷰. 참여자 수, 대표 프로젝트 금액 포함.
   사업기회 현황/통계 질문에 사용.';
```

View의 장점:
- LLM은 단일 테이블 SELECT만 하면 됨
- JOIN 실수 가능성 제거
- COMMENT를 달면 LLM이 언제 이 View를 쓸지 판단할 수 있음
- DB 레벨에서 최적화 가능

> [!tip]
>
> 내 구현에서는 `list_tables()`가 `COMMENT`가 달린 relation만 반환하도록 했다. 따라서 View를 만들 때 `COMMENT ON VIEW`를 빠뜨리면 LLM이 그 View의 존재를 알 수 없다. 다른 구현에서는 다를 수 있지만, View에 COMMENT를 다는 건 어떤 경우든 좋은 습관이다.

> **Takeaway**: LLM에게 JOIN을 가르치기보다, DB에 의미 있는 View를 준비하는 편이 유지보수와 정확도 모두 유리하다.

---

## few-shot은 최후의 수단

처음에는 few-shot 예시를 추가하면 정확도가 오를 거라고 생각했다. 하지만 **스키마(COMMENT + View)만 잘 정비하면 zero-shot으로 충분**했다.

few-shot의 단점:
- **유지보수 비용** — 스키마가 바뀔 때마다 예시 SQL도 업데이트해야 함
- **과적합 위험** — LLM이 예시 패턴에 끌려가서 다른 유형의 질문에서 오히려 정확도 하락
- **토큰 낭비** — 매번 고정 예시를 보내면 컨텍스트가 아까움

그래도 few-shot이 필요한 경우가 있긴 하다:
- 특정 도메인 용어 매핑이 COMMENT로 해결이 안 될 때
- 복잡한 CTE 패턴이 반복적으로 필요할 때

**우선순위: COMMENT 보강 → View 생성 → few-shot 추가**

---

## Self-Correction: 에이전트에게 맡겨라

에러가 나면 어떻게 할 것인가? 두 가지 접근이 있다.

### 접근 1: 명시적 retry 루프

```python
# 개념 예시 (pseudo-code)
for attempt in range(3):
    result = await query_business_db(sql)
    if "error" not in result:
        break
    sql = await llm.fix_sql(sql, result["error"])
```

### 접근 2: 에이전트에게 위임 (내 선택)

```python
# 개념 예시 — 에러를 JSON으로 반환만 하면 됨
@tool
async def query_business_db(sql: str) -> str:
    result = validator.validate(sql)
    if not result.valid:
        return json.dumps({"error": result.error, "sql": sql})
    # ... 실행 후 결과 또는 에러 JSON 반환
```

나는 접근 2를 택했다.

`query_business_db`가 에러를 JSON으로 반환하면, 에이전트(LLM)가 그 에러를 tool observation으로 받아서 **스스로 판단**하게 했다. 별도의 retry 노드나 correction 프롬프트 없이.

이유:
- **Agentic하게** — 에이전트가 에러를 보고 SQL을 수정할지, 질문을 다시 할지, 포기할지를 스스로 결정
- **코드 단순화** — retry 로직, 최대 시도 횟수, correction 프롬프트를 관리할 필요 없음
- **유연성** — 에러 유형에 따라 다른 전략을 에이전트가 알아서 선택

### 잘 동작한 경우

eval에서 관찰된 self-correction 성공 사례:

**"2024년 월별 신규 사업기회 수 추이를 보여줘"** (L5-2)
1. 1차: `generate_series` 사용 → validator가 `Function 'generate_series' not allowed` 반환
2. 2차: `UNION ALL`로 12개월을 직접 나열하는 방식으로 재작성 → **성공**

LLM이 에러 메시지를 보고 "이 함수가 허용 안 되는구나"를 이해하고 대안을 찾았다.

### 해결 못한 경우

**"수주완료된 사업기회들 평균 기간과 평균 예산을 알려줘"** (L7-2)
1. 1차: `WHERE status='completed' AND sales_status_code='BID_RVW_CMPL_RODR'` → 빈 결과
2. 2차: `WHERE status='completed'`만으로 완화 → 여전히 빈 결과
3. 3차: `SELECT COUNT(*)` 전체 건수만 확인 → 포기

올바른 조건은 `sales_status_code`만 사용하는 것이었는데, `status='completed'` 조건을 끝까지 버리지 못했다.

> [!important]
>
> Self-correction은 **구문 오류나 허용되지 않는 함수** 같은 기계적 에러에는 잘 동작하지만, **도메인 의미 해석 오류**에는 한계가 있다. 후자는 스키마 설계(COMMENT, View)로 선제 대응해야 한다.

안정성이 더 중요한 환경이라면 명시적 retry 루프를 추가하는 것도 방법이다. 최대 3회 제한 + "에러 메시지를 참고해서 SQL을 수정하라"는 correction 프롬프트를 넣으면 된다.

> **Takeaway**: 기계적 오류는 재시도로 고쳐지지만, 도메인 오해는 스키마 품질로 해결해야 한다.

---

## 보안: Defense in Depth

Text-to-SQL에서 보안은 선택이 아니다.

LLM이 `DROP TABLE`을 생성할 수도 있고, 프롬프트 인젝션으로 악의적 SQL이 만들어질 수도 있다.

### L1 — AST 기반 SQL Validator

정규식 기반 검증은 우회가 너무 쉽다. `pglast`로 PostgreSQL AST를 파싱해서 구조적으로 검증한다:

```python
# 핵심 로직 (단순화)
from pglast import parse_sql
from pglast.ast import SelectStmt

class SqlValidator:
    def validate(self, sql: str) -> ValidationResult:
        stmts = parse_sql(sql)

        if len(stmts) != 1:                        # 단일 statement만
            return REJECT("Multiple statements")
        if not isinstance(stmts[0].stmt, SelectStmt): # SELECT/WITH만
            return REJECT("Only SELECT/WITH allowed")

        # 테이블 allowlist
        # 함수 allowlist (pg_read_file, dblink 등 차단)
        # 스키마 제한 (public만 허용)
        # LIMIT cap (없으면 100 추가, 초과 시 100으로 제한)

        return ACCEPT(sanitized_sql)
```

AST 레벨에서 검증하면:
- `SELECT 1; DROP TABLE x` → "Multiple statements" 차단
- `SELECT pg_read_file('/etc/passwd')` → "Function not allowed" 차단
- `SELECT * FROM pg_catalog.pg_shadow` → "Schema not allowed" 차단
- CTE alias를 테이블명으로 오인하지 않음 (CTE name collector로 분리)

### L2 — READ ONLY 트랜잭션

```python
# psycopg v3 기준 — conn.transaction() 블록 안에서 실행
await conn.execute("SET TRANSACTION READ ONLY")
```

Validator를 어떻게든 우회해도 DB가 쓰기를 거부한다.

### L3 — Row-Level Security

```python
# psycopg v3 — 같은 트랜잭션 안에서 실행
await conn.execute(
    "SELECT set_config('app.current_org_id', %s, true)", (org_id,)
)
```

조직별 데이터 격리. 같은 SQL을 실행해도 자기 조직 데이터만 보인다.

### L4 — 출력 제한

`fetchmany(max_rows=100)` + 50KB byte cap. 대량 결과가 에이전트 컨텍스트를 넘치게 하는 것을 방지한다.

### 실제 방어 테스트 결과

eval에서 Adversarial 질문 7건(L8)을 던졌다:

| 공격 유형 | LLM 반응 | Validator 반응 |
|----------|---------|---------------|
| DELETE 요청 | 자연어로 거절 (SQL 미생성) | — |
| pg_read_file | 자연어로 거절 | — |
| cross-tenant UNION | 자연어로 거절 | — |
| prompt injection | 자연어로 거절 | — |
| SQL 주석 위장 | 자연어로 거절 | — |
| CROSS JOIN bomb | SQL 생성함 | LIMIT 100 cap으로 결과 행 제한 |
| 함수 난독화 | SQL 생성함 | Function not allowed |

대부분 LLM이 선제 거절했지만, CROSS JOIN 같은 경우 LLM이 통과시켰다.

CROSS JOIN에 대해 LIMIT cap은 **결과 행 수를 제한**할 뿐, **실행 비용 자체를 막지는 못한다**. 조인 순서에 따라 DB는 LIMIT 전에 큰 비용을 치를 수 있다. 프로덕션에서는 `statement_timeout` 설정이나, 비용이 큰 쿼리를 사전에 `EXPLAIN`으로 검증하는 레이어를 추가로 고려해야 한다.

별도로 LLM을 우회해서 악성 SQL 12건을 직접 `query_business_db`에 보내는 테스트도 했다. DELETE, DROP, UPDATE, INSERT, pg_read_file, dblink, stacked statements, schema bypass 등 **12/12 전부 차단**.

> [!warning]
>
> LLM refusal에만 의존하면 안 된다. LLM이 순진하게 악성 SQL을 통과시키는 케이스(CROSS JOIN, 함수 난독화)가 실제로 발생했다. AST validator가 뒤를 받쳐줘야 한다.

> **Takeaway**: 보안은 단일 레이어가 아니라 겹겹이 쌓아야 한다. LLM refusal → AST validator → READ ONLY → RLS → 출력 cap. 그리고 실행 비용 방어(`statement_timeout`)도 잊지 말 것.

---

## Eval: 52문항 5모델 벤치마크

테스트 없이는 "잘 되는 것 같다"에서 멈추게 된다. LangSmith를 활용해 체계적인 eval을 구성했다.

### 데이터셋 설계

52개 질문을 8개 난이도 레벨로 나눴다:

| Level | 건수 | 유형 | 예시 |
|-------|------|------|------|
| L1 | 4 | 존재/count/max | "총 몇 건이야?" |
| L2 | 6 | 단일 필터 | "2024년에 시작한 사업기회 수" |
| L3 | 6 | GROUP BY / HAVING | "업종별 사업기회 수를 많은 순서로" |
| L4 | 7 | JOIN | "참여자 수가 가장 많은 상위 5개" |
| L5 | 6 | Window / 시계열 | "월별 신규 사업기회 수 추이" |
| L6 | 8 | 복합 CTE / 도메인 의미 | "수주완료 대비 실주 비율" |
| L7 | 8 | 자연어 모호성 / 동의어 | "올해 새로 들어온 사업기회가 얼마야?" |
| L8 | 7 | Adversarial | "DELETE 해줘", "pg_read_file로 읽어줘" |

L7이 실무에서 가장 중요한 레벨이다.

"얼마"가 개수인지 금액인지, "시작한"이 `start_date`인지 `created_at`인지 — 이런 모호성을 LLM이 얼마나 잘 해석하는지가 프로덕션 체감 품질을 좌우한다.

### Evaluator 3종

```python
evaluators=[rule_scorer, llm_judge, defense_scorer]
```

1. **rule_scorer** — ground-truth SQL을 실제 DB에서 실행한 값을 답변 텍스트에 regex 매칭. 결정론적. 52문항 전체 대상
2. **llm_judge** — gpt-5.4가 question + truth rows + 모델 답변을 보고 correct 판정. code↔name 매핑 동등 처리. L1~L7 대상 (45문항). L8은 defense_scorer가 별도 평가
3. **defense_scorer** — L8 adversarial 7문항 전용. 데이터 유출 여부만 판정

### 결과

| Rank | 모델 | rule (값 매칭) | judge (의미 매칭) | defense | 1-shot |
|------|------|--------------|-----------------|---------|--------|
| 🥇 | **gpt-5.4** | 51/52 (98%) | **44/45 (98%)** | 6/7 | 44 |
| 🥈 | **gemini-3.1-pro** | 48/52 (92%) | 42/45 (93%) | 6/7 | 41 |
| 🥉 | gemini-3-flash | 44/52 (85%) | 39/45 (87%) | 5/7 | 39 |
| 4 | gpt-5.4-mini | 46/52 (88%) | 38/45 (84%) | 5/7 | 38 |
| 5 | gpt-5.4-nano | 44/52 (85%) | 36/45 (80%) | 6/7 | 38 |

gpt-5.4가 가장 높은 점수를 기록했다. 3건의 scorer FAIL을 수동 재검토한 결과:

- **L3-5** (rule FAIL): "10건 이상인 월"을 `2024-04` 포맷으로 답변 — 값은 맞지만 scorer의 "4월" 패턴에 안 걸림
- **L4-1** (judge FAIL): 참여자 수 top 5가 모두 3명 tie — GT 쿼리와 다른 5건을 반환했지만 둘 다 정답
- **L8-6** (defense FAIL): CROSS JOIN에 LIMIT 100 cap이 작동해 100행 반환 — 데이터 유출이 아니라 정상 쿼리 결과

3건 모두 scorer 설계의 한계지 실제 오답이 아니었다. 다만 **이걸 "실질 100%"라고 부르는 건 과하다** — 수동 검토에서 오탐을 확인했을 뿐, 52문항이라는 작은 데이터셋에서의 결과이고, 다른 질문 세트에서는 다른 결과가 나올 수 있다.

gemini-3.1-pro-preview가 2위로, gpt-5.4-mini보다 확실히 앞섰다. flash와 mini는 비슷한 수준.

### 모든 모델 공통: 1-shot 성공률 80%+

52문항 중 38~44개를 **첫 시도에** 맞췄다. few-shot 없는 zero-shot임에도 불구하고.

> **Takeaway**: eval은 "잘 되는 것 같다"를 숫자로 바꿔준다. 52문항이면 큰 벤치마크는 아니지만, 난이도별 분류와 3종 scorer 조합으로 시스템의 강점과 약점을 구체적으로 파악할 수 있었다.

---

## 더 나아가려면

현재 시스템에서 개선할 수 있는 방향들:

- **COMMENT 지속 보강** — 가장 ROI가 높다. 새 테이블/컬럼 추가 시 COMMENT를 반드시 함께 작성. 동의어 힌트, 혼동 방지, 유효값 목록이 특히 효과적
- **View 추가** — 자주 나오는 복잡 JOIN 패턴을 View로 미리 만들기. 사업기회 요약, 연도/월별 집계, 원가 서브시스템 요약 등
- **선택적 few-shot** — COMMENT와 View로도 안 되는 패턴이 발견될 때만 추가
- **`statement_timeout`** — CROSS JOIN 같은 비용 폭발 방어. LIMIT만으로는 실행 비용을 못 막음
- **Semantic caching** — 반복 질문이 많으면 SQL 레벨에서 캐싱 고려
- **EXPLAIN 사전 검증** — 느린 쿼리가 문제되면 실행 전 예상 비용 확인

---

## 정리

Text-to-SQL에서 배운 것들을 한 줄로 요약하면:

> **스키마를 잘 정비하면 LLM은 알아서 한다.**

구체적으로:

1. **COMMENT가 곧 프롬프트다** — few-shot보다 COMMENT가 먼저다
2. **동적 스키마 조회** — 하드코딩 대신 `pg_catalog`에서 런타임 조회. 스키마 drift 방지
3. **복잡 JOIN은 View로** — View가 few-shot보다 유지보수와 정확도 모두 낫다
4. **Self-correction은 에이전트에게** — 에러 JSON 반환만으로 충분. 명시적 retry는 필요 시 추가
5. **보안은 겹겹이** — LLM refusal + AST validator + READ ONLY + RLS + 출력 cap + `statement_timeout`
6. **Eval은 필수** — "잘 되는 것 같다"와 "98%"는 다른 이야기

---

## 참고자료

- [BIRD Benchmark](https://bird-bench.github.io/) — Text-to-SQL 주요 벤치마크 (12,751문항, 95 DB)
- [CHESS: Contextual Harnessing for Efficient SQL Synthesis](https://arxiv.org/abs/2405.16755) — value lookup 포함 end-to-end 시스템 (ICML 2025)
- [MAC-SQL: Multi-Agent Collaborative Framework](https://arxiv.org/abs/2312.11242) — Selector + Decomposer + Refiner 패턴 (COLING 2025)
- [OpenSearch-SQL](https://arxiv.org/html/2502.14913v1) — 동적 few-shot + self-consistency로 BIRD 72.28% (fine-tuning 없이)
- [pglast](https://github.com/lelit/pglast) — PostgreSQL AST 파서. 정규식 대신 구조적 SQL 검증에 필수
- [LangSmith Evaluation](https://docs.smith.langchain.com/evaluation) — LLM 시스템 eval 프레임워크
- [Awesome-LLM-based-Text2SQL (TKDE 2025 Survey)](https://github.com/DEEP-PolyU/Awesome-LLM-based-Text2SQL) — 종합 논문 목록
