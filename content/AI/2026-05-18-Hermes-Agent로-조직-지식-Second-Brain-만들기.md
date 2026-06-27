---
title: "Hermes Agent로 조직 지식 Second Brain 만들기"
date: 2026-05-18
tags:
  - Hermes-Agent
  - AI-Agent
  - knowledge-base
  - LLM-Wiki
  - second-brain
  - PKM
  - ADR
  - organization-knowledge
  - search
  - access-control
draft: false
enableToc: true
description: Slack, 회의록, 고객 문서, PR, Linear/Jira, AI 코딩 대화에서 생기는 의사결정을 Hermes Agent로 수집하고 프로젝트·팀·조직 단위 지식으로 통합하는 운영 모델을 정리한다.
summary: "조직 지식은 회의록 하나에 있지 않고 Slack, 고객 문서, PR, Linear/Jira, 코드, AI 대화 사이에 흩어진다. Hermes Agent를 수집·정리·PR 생성 레이어로 두고, 프로젝트→팀→조직으로 지식을 승격하며, LLM Wiki·ADR·Second Brain·권한 관리·검색 메타데이터를 결합하는 운영 모델을 제안한다."
published: 2026-05-18
modified: 2026-05-28
---

## 들어가며

AI 에이전트를 팀에서 쓰기 시작하면 금방 다음 질문에 부딪힌다.

> Hermes Agent가 Slack에서 작업을 받고 PR을 만들 수 있다면, 그 과정에서 생긴 의사결정과 프로젝트 지식은 어디에 남겨야 할까?

단순히 GitHub Issue와 PR에 남기면 될 것 같지만, 실제 조직의 의사결정은 그렇게 깔끔하지 않다. 고객이 보낸 문서, 회의록, Slack thread, Linear/Jira ticket, GitHub PR, 코드 리뷰, AI와 코딩하며 나눈 대화가 모두 조금씩 맥락을 갖고 있다. 한 도구만 source of truth로 삼으면 나머지 맥락이 사라진다.

그래서 이 글의 주제는 Hermes Agent 자체의 기능 소개가 아니라, Hermes를 **조직 지식 운영 레이어**로 쓸 때 필요한 설계다.

핵심 질문은 네 가지다.

1. 일상 대화와 작업 도구에서 지식 후보를 어떻게 뽑을 것인가?
2. 프로젝트 → 팀 → 조직 단위로 어떻게 통합할 것인가?
3. 통합된 내용을 검색하기 좋은 형태로 어떻게 남길 것인가?
4. 고객 문서와 내부 논의가 섞일 때 권한을 어떻게 관리할 것인가?

먼저 전체 흐름을 그림으로 보면 이렇다.

![[assets/hermes-org-knowledge-pipeline.svg]]

> 핵심은 raw signal을 바로 조직 지식으로 저장하지 않는 것이다. Hermes는 후보를 만들고, 사람은 승격 여부를 결정하며, ADR과 LLM Wiki가 서로 다른 시간 모델을 맡는다.

---

## 지식은 회의록이 아니라 작업 표면 전체에서 생긴다

회의록은 중요하지만 충분하지 않다. 실제 결정은 이런 곳에서 발생한다.

| 표면 | 발생하는 지식 |
|---|---|
| Slack / 메신저 | 빠른 합의, 질문, 암묵적 결정, 고객 응답 초안 |
| 회의록 | 공식 합의, 참석자, 논의 흐름 |
| 고객 문서 | 요구사항, 제약, 계약상 표현, 우선순위 |
| Linear / Jira / GitHub Issue | 작업 단위, acceptance criteria, 우선순위 변경 |
| GitHub PR | 구현 선택, 리뷰 근거, CI 결과, 코드 변경 |
| 코드 | 최종 실행 가능한 사실 |
| AI coding session | 탐색한 대안, 실패한 접근, 임시 판단, 자동화 로그 |
| Wiki / Docs | 정제된 현재 지식 |
| ADR | 되돌리기 어려운 결정의 이유 |

따라서 장기 지식 모델은 특정 도구가 아니라 다음 엔티티를 중심으로 잡는 편이 낫다.

```text
Project
Team
Organization
Decision
Requirement
Task
Artifact
Source
Person / Role
Customer
Code Change
```

GitHub PR, Linear ticket, Slack thread는 이 엔티티에 연결되는 provider일 뿐이다.

```yaml
task:
  provider: linear
  external_id: ENG-123
  url: https://linear.app/...

decision:
  id: DEC-2026-05-18-001
  project: syshin0116.dev
  sources:
    - slack:...
    - pr:...
    - customer_doc:...
```

이렇게 해야 GitHub에서 Linear로 옮기거나 Notion에서 Confluence로 바뀌어도 지식 모델이 무너지지 않는다.

---

## Raw → Event → Decision → Knowledge → Synthesis

모든 대화를 저장하려고 하면 실패한다. 저장 대상의 층을 나눠야 한다.

### 1. Raw layer

원본 그대로의 자료다.

- Slack thread
- 회의록
- 고객 문서
- PR/issue/ticket
- AI session transcript
- 코드 diff

이 층은 보존과 추적이 목적이다. 아직 지식은 아니다.

### 2. Event layer

원본에서 뽑아낸 의미 있는 사건이다.

예를 들면:

- 고객이 요구사항을 변경했다.
- 특정 아키텍처 방향이 논의되었다.
- 장애 원인이 밝혀졌다.
- 임시 workaround가 생겼다.
- AI가 구현 중 중요한 대안을 버렸다.

### 3. Decision layer

되돌리기 어렵거나 팀 합의가 필요한 선택이다.

```markdown
# Decision: 프로젝트별 지식과 조직 위키를 하이브리드로 운영한다

## Context
각 프로젝트마다 코드와 고객 맥락이 다르고, 중앙 위키 하나에 모든 세부사항을 복붙하면 빠르게 stale해진다.

## Options
1. 중앙 위키 하나에 모두 모은다.
2. 프로젝트별로만 관리한다.
3. 프로젝트별 source of truth + 조직 단위 compiled view로 운영한다.

## Decision
3번을 선택한다.

## Consequences
프로젝트 문서는 코드와 가까이 유지하고, 조직 위키는 요약·링크·공통 패턴 중심으로 운영한다.
```

이 층은 ADR처럼 append-only로 두는 편이 좋다.

### 4. Knowledge layer

현재 기준으로 재사용 가능한 지식이다.

- project context
- runbook
- architecture overview
- customer context
- glossary
- playbook
- AI workflow guide

이 층은 LLM Wiki처럼 계속 갱신되는 mutable layer가 어울린다.

### 5. Synthesis layer

프로젝트 여러 개를 가로지르는 조직 관점의 요약이다.

- 프로젝트별 상태 요약
- 고객별 주요 결정
- 반복되는 workflow
- 보안/권한 정책
- 공통 실패 사례
- 팀별 AI 사용 패턴

이 층은 모든 세부 내용을 복사하는 곳이 아니라, 링크와 요약의 허브다.

---

## 프로젝트 → 팀 → 조직으로 승격하기

내가 추천하는 기본 구조는 **프로젝트별 원천 지식 + 조직 단위 compiled view**다.

| Scope | 무엇을 남기나 | 저장 위치 | 자동화 기본값 |
|---|---|---|---|
| 개인 | 작업 중 메모, AI 대화 요약, 임시 판단 | 개인 vault / Hermes memory / session log | 저장은 느슨하게, 공유 전 정제 |
| 프로젝트 | 요구사항, ADR, runbook, 코드 경로와 연결된 운영 맥락 | repo `docs/`, project wiki, Linear/Jira project | PR/티켓 종료 시 후보 추출 |
| 팀 | 여러 프로젝트에서 반복되는 workflow, 표준, reusable playbook | team wiki / shared vault | 주간 digest + human triage |
| 조직 | cross-project policy, 보안·권한 기준, 고객별 공통 맥락 | org knowledge hub | 승인된 요약과 링크만 통합 |

프로젝트 문서는 코드와 가까워야 덜 썩는다. 반대로 조직 위키는 모든 세부사항을 복붙하지 말고 **요약, 링크, 정책, 공통 패턴**만 가져가야 한다.

```text
project repo
  docs/
    context.md
    decisions/
    requirements/
    runbooks/
    ai-worklogs/

org knowledge hub
  projects/
    project-a.md
    project-b.md
  patterns/
  policies/
  customers/
  decision-index.md
```

조직 위키는 source of truth가 아니라 **compiled index**에 가깝다.

---

## 일상 대화에서 어떻게 트리거할까?

완전 자동 저장은 위험하고, 완전 수동 기록은 안 하게 된다. 중간 단계가 필요하다.

### 1. 명시적 트리거

초기에는 사람이 직접 호출하는 방식이 가장 정확하다.

```text
@Hermes 이거 decision으로 남겨줘
@Hermes 이 스레드 요구사항으로 정리해줘
@Hermes 고객 문서 기준으로 open question 뽑아줘
@Hermes 이 PR에서 reusable pattern만 wiki 후보로 뽑아줘
```

Hermes는 원본 링크와 함께 초안을 만든다.

```text
Slack thread → decision draft
Customer doc → requirement draft
PR discussion → ADR 후보
AI session → worklog summary
```

### 2. 후보 제안

대화에서 이런 표현이 나오면 agent가 바로 저장하지 않고 후보로 제안한다.

```text
이 방향으로 가자
결정하자
고객이 요청함
요구사항이 바뀜
다음부터는 이렇게 하자
원인은 이거였음
이건 기억해야 함
```

응답은 이런 식이면 충분하다.

```text
이 스레드에서 기록 후보가 있어 보여요.

1. 고객 요구사항 변경
2. 프로젝트별 지식 저장소 필요성
3. 중앙 위키는 요약/링크 허브로 둔다는 결정

저장 위치를 선택해주세요.
- project: syshin0116.dev
- team wiki
- org knowledge hub
- 저장하지 않음
```

### 3. 주기적 수확

실시간으로 놓치는 맥락은 주기적으로 회수한다.

- 매일: 오늘의 Slack/AI session에서 decision 후보 추출
- 매주: merged PR, closed ticket, 회의록에서 프로젝트별 digest 생성
- 스프린트 종료: 요구사항 변경, 결정, 미해결 질문 정리
- 월간: 조직 단위 pattern과 policy 업데이트

이 작업은 Hermes cron이나 webhook에 잘 맞는다.

---

## Hermes의 메모리 레이어와 조직 scope 매핑

위에서 정리한 raw → event → decision → knowledge → synthesis 5층은 추상 모델이다. Hermes에서 이것을 실제로 굴리려면 어떤 파일에 무엇이 들어가는지의 매핑이 필요하다. Hermes는 system prompt에 주입되는 메모리를 네 개의 파일로 나눠 둔다.

| 파일 | 역할 | 어디까지 따라가나 | 글자 제한 |
|---|---|---|---|
| `SOUL.md` | agent identity, 어조, 커뮤니케이션 스타일 | 모든 profile | 느슨 |
| `MEMORY.md` | 환경 정보, 규칙, 학습한 내용 | profile 단위 | 약 2,200자 |
| `USER.md` | 사용자 선호, 페어링된 커뮤니케이션 패턴 | profile 단위 | 약 1,375자 |
| `AGENTS.md` | 프로젝트별 컨텍스트(아키텍처, 코딩 규칙, tool 선호) | 프로젝트 디렉터리 | 느슨 |

원칙은 단순하다. **어디든 따라가야 하는 정체성은 SOUL.md, 프로젝트별 지식은 AGENTS.md**다. MEMORY와 USER는 그 사이에 끼는 사용자와 환경 레이어다. 위 4파일을 앞서 정의한 scope에 매핑하면 다음과 같이 정리된다.

| 조직 scope | 주로 들어가는 Hermes 파일 | 비고 |
|---|---|---|
| 개인 | `USER.md` + 개인 vault | 사용자 선호와 일회성 메모 |
| 프로젝트 | `AGENTS.md` + repo `docs/` | 코드와 가까이, 코드 리뷰와 함께 갱신 |
| 팀 | 공유 `AGENTS.md` 템플릿 + team wiki | 여러 repo가 따르는 기본값 |
| 조직 | `SOUL.md`의 에이전트 정체성 + org knowledge hub | 글자 제한 안에 들어가는 핵심 원칙만 |

운영상 가장 중요한 제약 두 가지를 같이 기억해야 한다. 첫째, MEMORY와 USER는 **세션 시작 시 한 번 캡처되는 고정 스냅샷**으로 system prompt에 주입된다. 세션 중간에 메모를 추가해도 그 변화는 다음 세션에서야 반영된다. 이 제약 덕분에 prefix cache가 보존되지만, "방금 알려준 걸 왜 다음 답에 못 쓰지?"의 원인이기도 하다. 둘째, **글자 제한이 작다**(MEMORY 약 2.2K, USER 약 1.4K). 조직 단위 지식을 여기에 모두 넣으려고 하면 안 된다. 메모리는 인덱스나 포인터 역할만 하고, 본문은 wiki나 외부 store에 둬야 한다.

agent가 메모리를 갱신할 때 쓰는 도구도 명시적이다.

```python
memory.add("이 서버는 Debian 12, PostgreSQL 16")
memory.replace("Docker group", "Docker: no sudo needed, group active")
memory.remove("outdated-rule")
```

이 호출이 로그에 보이면 "지금 무엇이 장기 기억으로 승격됐는가"가 그대로 드러난다. raw에서 decision으로 가는 승격을 사람이 명시 트리거로 다루듯, 메모리 승격도 같은 원리로 다룬다.

---

## 검색하기 좋은 지식으로 남기는 법

통합된 지식은 “문서가 어딘가에 있다”만으로 부족하다. 나중에 사람과 agent가 찾기 쉬우려면 문서 자체가 검색 인덱스처럼 작성되어야 한다.

최소 frontmatter는 이런 형태가 좋다.

```yaml
---
title: "프로젝트별 지식과 조직 위키를 하이브리드로 운영한다"
type: decision              # decision | requirement | pattern | runbook | project-map | customer-context
scope: project              # personal | project | team | org
project: syshin0116.dev
team: content-platform
status: accepted            # proposed | accepted | superseded | deprecated
visibility: internal        # public | internal | confidential | restricted
tags: [ai-agent, knowledge-management, hermes]
owners: [syshin0116]
sources:
  - slack:...
  - pr:...
  - linear:...
related:
  - adr-2026-05-18-001
  - llm-wiki
updated: 2026-05-18
review_after: 2026-08-18
---
```

검색 UX는 네 겹으로 나눈다.

| 검색 방식 | 잘 찾는 것 | 필요한 설계 |
|---|---|---|
| 전체 텍스트 / BM25 | 정확한 용어, 에러 메시지, API 이름 | 제목·별칭·키워드를 문서 안에 명시 |
| 벡터 검색 | 표현이 다른 유사 질문 | 좋은 summary, chunk 경계, embedding |
| 메타데이터 필터 | 프로젝트/팀/권한/상태별 제한 | `project`, `team`, `visibility`, `status` 필드 |
| 그래프 / wikilink | 결정-요구사항-코드-고객 문서 연결 | `related`, backlinks, ADR 링크 |

그래서 좋은 위키 페이지는 글처럼만 쓰면 안 된다. 첫 문단에는 정의와 결론을 쓰고, `aliases`, `summary`, `tags`, `sources`, `related`를 채워야 한다. Dataquest의 hybrid search 글이 말하듯 metadata는 JSON blob이 아니라 atomic field로 나눠야 필터링이 된다. Azure AI Search의 document-level access control도 같은 원리다. ingestion 때 문서의 ACL/그룹 정보를 같이 넣어야 query 때 결과를 security trimming할 수 있다.

### Hermes의 기본 인덱스: Session DB + FTS5

위 네 겹은 위키 본문에 대한 검색이다. Hermes는 그보다 한 단계 앞에서 모든 CLI/메시징 세션을 SQLite와 FTS5에 자동 보존한다. agent는 `session_search` 도구로 과거 세션을 전체 텍스트 검색해 "전에 이 문제를 어떻게 풀었는지"를 끌어올 수 있다. 즉 위키로 승격되지 않은 raw 대화도 사라지지 않고 검색 가능한 상태로 남는다. 다만 이건 개인 또는 profile 단위 보존이지 **조직 검색의 대상은 아니다**. raw 세션은 source ACL을 보존한 채 그대로 두고, 위키 승격 단계에서만 검색·권한 인덱스에 들어간다는 분리가 필요하다.

---

## 권한 관리는 검색보다 먼저 설계해야 한다

조직 지식베이스에서 가장 위험한 실패는 “검색이 안 됨”보다 **보면 안 되는 문서가 검색됨**이다. 특히 고객 문서, 계약 조건, 보안 이슈, 인사 관련 결정, 비공개 레포명은 요약본에 섞여 나오기 쉽다.

기본 원칙은 다섯 가지다.

1. **source ACL을 보존한다**: Slack private channel, 고객 폴더, repo 권한, Notion page 권한을 ingest 시점에 metadata로 복사한다.
2. **권한 없는 문서는 retrieval 전에 제외한다**: LLM에게 보여준 뒤 “말하지 마”가 아니라, 검색 결과에서 애초에 빼야 한다.
3. **요약본은 원본보다 더 공개적이면 안 된다**: confidential 고객 문서를 요약한 wiki page도 최소 confidential이다.
4. **공개 블로그와 내부 위키를 분리한다**: 공개 `content/`와 내부 `.wiki-cache/`, inbox, ledger를 분리해야 한다.
5. **승격에는 review gate를 둔다**: private source에서 public artifact로 나가는 순간은 자동화하지 말고 사람이 승인한다.

| 데이터 종류 | 권한 기본값 | 공개 가능성 |
|---|---|---|
| 공개 문서, 공개 GitHub 이슈 | public | 바로 인용 가능 |
| 사내 회의록, 내부 PR | internal | 요약만 내부 공유 |
| 고객 문서, 계약·가격·보안 논의 | confidential | 고객명/수치 제거 후 별도 승인 |
| 개인 메모, DM, 인사 관련 대화 | restricted | 원칙적으로 조직 위키 승격 금지 |

검색 아키텍처보다 권한 아키텍처가 앞선다. agent pipeline도 다음 순서가 되어야 한다.

```text
collect
  → classify sensitivity
  → redact
  → draft
  → review
  → publish
```

검색/권한 구조는 다음처럼 분리해서 보는 편이 안전하다.

![[assets/hermes-knowledge-search-permission.svg]]

> 좋은 검색은 BM25, 벡터, 메타데이터, 그래프를 조합해서 만든다. 안전한 검색은 그 전에 source ACL을 보존하고 query-time filtering을 강제해서 만든다.

---

## Second Brain은 도움이 될까?

도움이 된다. 다만 개인용 Second Brain을 조직에 그대로 복사하면 부족하다.

Tiago Forte의 PARA는 정보를 `Projects`, `Areas`, `Resources`, `Archives`로 나누고, 주제보다 **actionability** 중심으로 정리하라고 말한다. 조직 지식에도 이 원칙은 유효하다.

- `Projects`: 진행 중인 제품/고객/기능 단위 지식
- `Areas`: 보안, 데이터, 플랫폼, 채용처럼 계속 유지되는 책임 영역
- `Resources`: 기술 조사, 경쟁사 분석, reusable pattern
- `Archives`: 종료 프로젝트, superseded ADR, 과거 고객 맥락

하지만 조직형 Second Brain에는 추가 필드가 필요하다.

| 개인 Second Brain | 조직 Second Brain |
|---|---|
| 내가 다 볼 수 있다 | 사람마다 권한이 다르다 |
| owner가 나 하나다 | page owner와 review cycle이 필요하다 |
| 메모가 곧 지식이 될 수 있다 | raw 대화는 promotion 과정을 거쳐야 한다 |
| 검색 실패는 개인 불편이다 | 검색/권한 실패는 정보 유출이나 잘못된 의사결정이 된다 |

그래서 조직형 Second Brain은 PARA 위에 `permission`, `owner`, `source`, `review_after`, `status`를 더한 형태가 되어야 한다. 개인의 second brain은 capture와 연결을 돕고, 조직의 second brain은 검색·권한·감사 가능성까지 책임져야 한다.

### 내장 메모리 한계를 넘는 External Memory Providers

앞서 본 SOUL/MEMORY/USER/AGENTS는 빠르고 단순하지만 글자 제한이 작아 조직 규모의 second brain을 그 안에 다 담을 수 없다. Hermes는 이 한계를 풀려고 외부 메모리 provider를 플러그 형태로 받는다. 2026년 기준 8종이 연동된다(Honcho, OpenViking, Mem0, Hindsight, Holographic, RetainDB, ByteRover, Supermemory).

```bash
hermes memory setup      # provider 선택
hermes memory status     # 현재 활성 provider 확인
```

선택의 의미는 분명하다. 메모리를 파일 두 개에 가둘지, 별도 메모리 store에 누적할지의 trade-off다. 별도 store를 쓰면 "팀 메모리"를 만드는 첫걸음이 되지만, 그 store의 권한과 audit이 추가로 필요해진다. 도입 순서는 다음이 자연스럽다.

1. 개인은 내장 MEMORY/USER로 시작한다.
2. 프로젝트 지식은 `AGENTS.md`와 repo `docs/`로 코드와 가까이 둔다.
3. 팀이나 조직 단위 누적이 필요해지면 그때 external provider를 도입한다.
4. provider도 source ACL을 보존해야 위 권한 원칙과 충돌하지 않는다.

즉 external memory는 "개인 second brain을 그대로 늘리는 도구"가 아니라 **scope 승격의 운영 옵션**이다. 어떤 provider를 고를지는 권한·감사·검색 요구가 결정한다.

---

## LLM Wiki와 ADR의 역할 분담

Karpathy의 LLM Wiki 패턴은 이 문제를 잘 설명한다. RAG가 매번 원문 chunk를 검색해서 답을 합성한다면, LLM Wiki는 원문을 읽고 지속적으로 갱신되는 Markdown wiki를 만든다.

다만 LLM Wiki만으로는 “왜 그렇게 결정했는가”가 약하다. Wiki는 최신 상태를 설명하는 mutable layer이고, decision history는 append-only ADR이 맡는 편이 낫다.

| 레이어 | 시간 모델 | 답하는 질문 |
|---|---|---|
| Raw / RAG | 원문 snapshot | 원문 어디에 있었나? |
| ADR | append-only | 왜 이 결정을 했나? |
| LLM Wiki | mutable | 지금 우리는 무엇을 알고 있나? |
| Org Index | compiled view | 프로젝트/팀/조직 전체에서 어떤 패턴이 보이나? |

Hermes의 역할은 이 레이어를 연결하는 것이다.

```text
Slack / PR / Linear / customer docs
  → Hermes capture
  → knowledge inbox
  → human triage
  → ADR or wiki draft
  → PR review
  → project/team/org index update
```

---

## 구요한님의 CMDS / CommandSpace에서 참고할 점

구요한님의 [`cmds-vault`](https://github.com/prodbartist/cmds-vault)는 이 주제에 직접적인 참고 사례다. CMDS는 Obsidian 기반 PKM 시스템이고, `Connect → Merge → Develop → Share`라는 지식 생애주기를 명확히 둔다. starter vault에는 `WELCOME.md`, `CMDS.md`, `CLAUDE.md`, `AGENTS.md`, `🏛 CMDS Guide`, `🏛 CMDS Head Quarter` 같은 시스템 파일이 있고, Claude/Codex 같은 agent가 어떤 순서로 무엇을 읽어야 하는지도 precedence로 정해둔다.

내가 참고하고 싶은 포인트는 네 가지다.

1. **프로세스 이름이 있다**: capture를 그냥 “정리”라고 부르지 않고 Connect, Merge, Develop, Share로 나눈다. 조직 지식도 `Capture → Triage → Synthesize → Publish`처럼 명령어화하는 게 좋다.
2. **시스템 파일과 사용자 노트를 구분한다**: CMDS는 system file author와 user note author를 분리한다. 조직 위키에서도 platform policy와 프로젝트별 지식을 분리해야 한다.
3. **Core Context는 복붙하지 않고 pointer로 둔다**: `cmds-llm-wiki`는 `Core Context.md`가 `BRAIN.md`, Head Quarter, CMDS Guide를 가리키게 하여 중복과 drift를 줄인다. 팀 위키도 프로젝트별 context를 중앙에 복붙하지 말고 pointer/index로 연결하는 편이 낫다.
4. **LLM Wiki를 vault 안에 두되 졸업 경로를 둔다**: `cmds-llm-wiki`는 `10. Raw Sources/`를 원천으로 두고, `LLMWiki/index.md`, `log.md`, `Wiki/`, `Queries/`를 만든다. 소스가 커지면 standalone wiki로 옮기는 graduation path도 있다.

특히 `Connect → Merge → Develop → Share`는 Hermes 운영과 잘 맞는다.

| CMDS | Hermes 조직 지식 운영으로 바꾸면 |
|---|---|
| Connect | Slack, 회의록, 고객 문서, PR에서 raw signal 수집 |
| Merge | 중복 제거, 프로젝트/팀/조직 scope 분류, 관련 문서 연결 |
| Develop | ADR, requirement, runbook, wiki page로 정제 |
| Share | 블로그, 팀 digest, 고객 보고서, PR/Linear update로 배포 |

Second Brain은 철학을 주고, CMDS는 프로세스 언어를 주고, LLM Wiki는 agent가 유지할 수 있는 Markdown 구현 방식을 준다. Hermes는 이 셋을 Slack, GitHub, Linear, 로컬 레포, cron 같은 실제 작업 표면과 연결하는 orchestration layer가 된다.

---

## Hermes로 운영한다면

실제 운영은 이렇게 시작하는 편이 좋다.

### Phase 1. 명시적 트리거만 도입

```text
@Hermes 이거 decision으로 남겨줘
@Hermes 이 스레드 요구사항으로 정리해줘
@Hermes 이 PR에서 wiki 후보 뽑아줘
```

저장은 바로 main에 하지 않고 PR이나 review queue로 보낸다.

### Phase 2. 프로젝트별 문서 구조 표준화

```text
docs/
  project-context.md
  decisions/
  requirements/
  runbooks/
  ai-worklogs/
  glossary.md
```

### Phase 3. 중앙 knowledge inbox 만들기

```text
knowledge-inbox/
  2026-05-18/
    project-a-slack-thread.md
    project-b-pr-123.md
    customer-c-requirement-change.md
```

각 항목은 `discard`, `task-log`, `ADR`, `wiki-update`, `follow-up issue`로 triage한다.

### Phase 4. 주간 digest와 승격 PR

Hermes cron이 매주 후보를 모으고, 사람이 승인하면 project wiki 또는 org wiki에 PR을 연다.

```text
weekly harvest
  → candidate decisions
  → candidate requirements
  → stale docs
  → unresolved questions
  → wiki/ADR PR
```

---

## 결론

조직 지식 운영에서 중요한 것은 “어떤 도구에 적을 것인가”보다 “어떤 층으로 승격할 것인가”다.

- Slack thread는 raw source다.
- PR은 execution log다.
- Linear/Jira/GitHub issue는 task surface다.
- ADR은 decision history다.
- LLM Wiki는 current knowledge다.
- 조직 위키는 compiled view다.
- 권한 metadata는 모든 layer를 관통해야 한다.

Hermes Agent는 이 구조에서 모든 지식을 혼자 판단하는 두뇌가 아니라, 여러 표면에서 신호를 모으고, 초안을 만들고, PR을 열고, 검증을 돌리고, 사람이 승인할 지점을 만드는 **지식 운영 오케스트레이터**에 가깝다.

개인 Second Brain이 “내가 나중에 다시 생각하기 위한 장치”라면, 조직형 Second Brain은 “팀이 같은 결정을 반복하지 않고, 권한을 지키면서, 현재 지식과 결정의 이유를 함께 검색하기 위한 장치”다.

그 차이를 받아들이면, AI Agent는 단순한 자동화 도구를 넘어 조직 기억을 유지하는 편집자이자 사서가 될 수 있다.

---

## 참고 자료

- [Hermes Agent Documentation](https://hermes-agent.nousresearch.com/docs/)
- [Karpathy - LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
- [구요한 / Yohan Koo - CMDS Vault](https://github.com/prodbartist/cmds-vault)
- [cmds-vault - cmds-llm-wiki skill](https://github.com/prodbartist/cmds-vault/blob/main/90.%20Settings/91.%20Skills/cmds-llm-wiki/SKILL.md)
- [Forte Labs - PARA Method](https://fortelabs.com/blog/para/)
- [Azure AI Search - Document-Level Access Control](https://learn.microsoft.com/en-us/azure/search/search-document-level-access-overview)
- [Dataquest - Metadata Filtering and Hybrid Search](https://www.dataquest.io/blog/metadata-filtering-and-hybrid-search-for-vector-databases/)
- [Microsoft - Maintain an architecture decision record](https://learn.microsoft.com/en-us/azure/well-architected/architect-role/architecture-decision-record)
- [Architectural Decision Records](https://adr.github.io/)
- [Hermes Agent 실무자 레퍼런스 종합 정리 (Blake Crosley)](https://blakecrosley.com/ko/guides/hermes)
