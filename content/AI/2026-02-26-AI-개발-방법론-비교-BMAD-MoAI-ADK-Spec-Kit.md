---
title: "AI 개발 방법론 4종 비교: BMAD Method vs MoAI-ADK vs GitHub Spec Kit vs Get Shit Done"
date: 2026-02-26
tags:
  - AI
  - agent
  - workflow
  - BMAD
  - MoAI-ADK
  - spec-kit
  - GSD
  - Agentic-AI
  - Claude-Code
  - development-methodology
  - vibe-coding
  - context-engineering
draft: false
enableToc: true
description: AI 코딩 도구가 넘쳐나는 시대, 실제로 개발 워크플로우를 바꿀 수 있는 방법론 4가지 - BMAD Method, MoAI-ADK, GitHub Spec Kit, Get Shit Done - 를 철학, 워크플로우, 커뮤니티 반응까지 철저하게 비교한다.
summary: "Claude Code, Cursor 같은 AI 코딩 어시스턴트가 대중화되면서, 이를 더 체계적으로 활용하기 위한 방법론들이 등장하고 있다. 이 글에서는 가장 주목받는 네 가지 - BMAD Method, MoAI-ADK, GitHub Spec Kit, Get Shit Done - 를 철학, 워크플로우, 에이전트 시스템, 실사용 경험과 커뮤니티 반응까지 세세하게 비교한다."
published: 2026-02-26
modified: 2026-03-19
---
---

## 왜 지금 이 비교인가

AI 코딩 어시스턴트가 진짜 쓸 만해지면서 새로운 고민이 생겼다. **"어떻게 쓰면 잘 쓰는 건가?"**

단순히 채팅창에 "이 기능 만들어줘"를 입력하는 수준을 넘어서, AI와 협업하는 *방법론*이 필요한 시점이 왔다. 그 수요를 정확히 겨냥한 네 프로젝트가 있다:

| 프로젝트 | 주체 | GitHub Stars | 라이선스 | 핵심 철학 |
|---|---|---|---|---|
| [BMAD Method](https://github.com/bmad-code-org/BMAD-METHOD) | 커뮤니티 | ⭐ 38k | MIT | 협업 AI 에이전트로 애자일 개발 |
| [MoAI-ADK](https://github.com/modu-ai/moai-adk) | modu-ai (한국) | ⭐ 841 | GPL-3.0 | 빠름보다 품질, SPEC-First |
| [GitHub Spec Kit](https://github.com/github/spec-kit) | GitHub 공식 | ⭐ 72k | MIT | Spec-Driven Development |
| [Get Shit Done](https://github.com/gsd-build/get-shit-done) | 개인 (Lex Christopherson) | ⭐ 35k | MIT | 경량 컨텍스트 엔지니어링 |

네 가지 모두 "AI에게 일을 잘 시키는 법"을 다루지만, 접근 방식이 완전히 다르다.

---

## BMAD Method

### 개요

**BMAD**는 *Breakthrough Method for Agile AI-Driven Development*의 약자다. 2024년 초 개인 프로젝트로 시작해 현재 38,000개 이상의 스타를 받은 커뮤니티 주도 프레임워크다. v6.0.3까지 출시되었고, 118명의 컨트리뷰터가 참여하고 있다.

### 핵심 철학

> "AI가 대신 생각하게 만드는 것이 아니라, AI를 전문 협업자로서 구조화된 프로세스를 통해 당신의 최선을 끌어내도록 한다."

BMAD의 핵심 아이디어는 AI에게 **역할(페르소나)** 을 부여하는 것이다. PM, 아키텍트, 개발자, UX 디자이너, QA 등 12개 이상의 전문 에이전트 페르소나가 있고, 이들이 애자일 방식으로 협업한다. "Party Mode"를 켜면 여러 에이전트가 한 세션에서 동시에 대화한다.

### 워크플로우

```
분석(Analysis) → 기획(Planning) → 설계(Solutioning) → 구현(Implementation)
```

각 단계는 YAML 기반 워크플로우 파일로 정의된다. 에이전트 간 핸드오프가 명시적으로 일어나며, 어떤 에이전트가 어떤 작업을 담당하는지 명확하다.

### 생태계

BMAD는 단독 도구가 아니라 **모듈 생태계**다:

- **BMad Method (BMM)** - 34+ 핵심 워크플로우
- **BMad Builder (BMB)** - 커스텀 에이전트 생성
- **Test Architect (TEA)** - 위험 기반 테스트 전략
- **Game Dev Studio (BMGD)** - 게임 개발 특화
- **Creative Intelligence Suite (CIS)** - 디자인 싱킹 도구

```bash
npx bmad-method install
```

Node.js v20+ 기반이며, CI/CD 파이프라인을 위한 비대화형 설치도 지원한다.

### 실사용 경험

**좋은 점:**
- 문서 우선 개발로 AI 환각(hallucination)이 줄어든다. 스펙이 있으면 AI가 행동을 "발명"할 여지가 줄기 때문
- 레거시 시스템 현대화에 강하다. 감사 추적이 가능한 아티팩트(Git에 커밋된 PRD, 아키텍처 문서)를 생성
- 규제 산업(금융, 의료 등)에서의 컴플라이언스 추적에 유용

**어려운 점:**
- 학습 곡선이 가파르다. CLI 커맨드, YAML 설정, 6~7개 에이전트 역할과 핸드오프를 모두 이해해야 한다
- **토큰 비용이 높다.** 각 에이전트에 방대한 컨텍스트를 제공하기 때문에, 초기 버전 기준 월 API 비용이 $847에 달하는 사례도 있었다
- 한 에이전트의 결과물이 틀려도 하위 에이전트가 감지하지 못하는 경우가 있다. "AI 팀이 협력해서 잘못된 인증 기능을 완성하고, 완료로 마킹한" 사례가 보고됨
- YAML 워크플로우가 탐색적 프로젝트에는 너무 경직될 수 있다

---

## MoAI-ADK

### 탄생 배경: 실패에서 시작된 도구

MoAI-ADK를 만든 Goos Kim([goos.kim](https://goos.kim))은 2024년 초 와디즈에서 "모두의 사주"라는 GPT 기반 서비스를 직접 개발하다 3주 만에 API 비용 약 $500를 태우는 경험을 했다. 스파게티 코드, 문서와 코드의 비동기화, 컨텍스트 윈도우 소진 후 작업 맥락 유실-현재 많은 개발자들이 AI 코딩에서 겪는 문제들이 그대로였다.

이 실패 경험을 바탕으로 약 6개월간 TDD, DDD, 스펙 문서 방식 등 다양한 개발 방법론을 AI 에이전트에 직접 적용해보며 탄생한 것이 MoAI-ADK다. 원래는 Python으로 작성된 73,000줄짜리 프레임워크였는데, Go로 완전히 다시 작성해 단일 바이너리로 5ms 안에 시작된다(Python 버전은 ~800ms).

스타 수(841)는 다른 셋에 비해 적지만, **한국어 README가 기본 제공**되고 한국 개발자 커뮤니티에서 활발히 사용되고 있다.

### 핵심 철학

> "바이브 코딩의 목적은 빠른 생산성이 아니라 코드 품질이다."

> "LLM은 거의 다 똑같은 것 같아요. 제일 중요한 건 사용자의 프롬프트가 문제지, 컨텍스트가 문제지, LLM의 성능은 이미 믿고 맡길 정도에 와 있다."

MoAI-ADK를 이해하는 두 가지 열쇠다. 대부분의 AI 코딩 도구들이 "더 빠르게"를 외칠 때, MoAI-ADK는 "더 좋게"를 강조한다. 그리고 모델 선택보다 **컨텍스트의 품질**이 결과를 결정한다는 관점에서 출발한다.

실제로 Goos Kim은 라이브 스트림에서 이렇게 말했다:

> "얘네들 범위를 정해 주지 않으면 막 중구난방이고 그냥 확률적으로 나오는 거니까. '이거 안 돼, 저거 안 돼' 다 막아 놓고 '요렇게만 해야 돼' 라고 하면 딱 그것만 바라보고 진행한다."

세 가지 근간 원칙:
1. **SPEC-First** - EARS(Easy Approach to Requirements Syntax) 형식의 명세서 작성이 구현보다 먼저. 재작업을 90% 줄인다고 주장
2. **TDD/DDD 자동 선택** - 신규 프로젝트는 TDD, 기존 프로젝트(커버리지 10% 미만)는 DDD로 자동 전환
3. **지능형 오케스트레이션** - 20개 전문 에이전트가 작업 복잡도에 따라 병렬/순차 실행

### TDD vs DDD: 언제 어느 쪽을?

MoAI-ADK의 독특한 점 중 하나는 **프로젝트 상황에 따라 개발 방법론을 자동으로 선택**한다는 것이다.

| 상황 | 방식 | 이유 |
|---|---|---|
| 신규 프로젝트 | **TDD** | 실패하는 테스트 코드를 먼저 작성해 맥락을 세션 내에서 유지 |
| 기존 프로젝트 (커버리지 <10%) | **DDD** | 수백 개 파일 대상 테스트 재작성은 비효율적 |

`moai project` 명령 실행 시 코드베이스를 자동 분석해 TDD/DDD를 결정한다. TDD에서는 AI가 테스트를 통과시키려 테스트 코드 자체를 수정하는 "치팅" 문제를 3~4중 지침으로 방지하고, 마지막 Sync 단계에서도 이중 검사한다.

### 에이전트 시스템

20개 에이전트가 세 계층으로 나뉜다:

**Manager 에이전트 (7개)** - 워크플로우 조율
- `manager-spec`: EARS 형식 명세서 생성
- `manager-ddd`: DDD 사이클 실행
- `manager-docs`: Nextra 통합 문서 생성
- `manager-quality`: TRUST 5 품질 검증
- `manager-git`: Git 작업 및 PR 자동화
- `manager-project`: 프로젝트 초기화
- `manager-strategy`: 아키텍처 의사결정

**Expert 에이전트 (9개)** - 도메인 전문성 제공
백엔드, 프론트엔드, 보안, DevOps, 디버깅, 테스팅, 리팩토링, 성능 최적화, UI/UX

**Builder 에이전트 (4개)** - 메타 프로그래밍
새 에이전트, 슬래시 커맨드, 스킬, 플러그인 생성

중앙에는 **Alfred SuperAgent**라는 전략적 오케스트레이터가 있어서 요청을 분석하고, 태스크 타입에 따라 라우팅하며, 최대 10개 에이전트를 병렬로 실행한다.

또한 두 가지 실행 모드가 있다:
- **Solo 모드** (`moai --solo`): 현재 Claude Code 세션 안의 서브 에이전트로 동작
- **Team 모드** (`moai --team`): 독립된 Claude Code 인스턴스를 병렬로 실행해 팀 리더처럼 지휘. 프론트엔드 + 백엔드 동시 개발에 적합하며, 구글 A2A 프로토콜과 유사한 양방향 소통이 가능

### TRUST 5 품질 프레임워크

모든 결과물에 5가지 품질 기준을 적용한다:

| 기준 | 내용 |
|---|---|
| **T**estable | 단위/통합 테스트, 커버리지 ≥85% |
| **R**eadable | 린팅(ruff), 네이밍 컨벤션, 문서화 |
| **U**nified | 코드 포맷팅 일관성 |
| **S**ecured | bandit + AST-grep 보안 스캔 |
| **T**rackable | 버전 컨트롤 통합, SPEC 추적, 진단 로깅 |

### 워크플로우: 3단계 + Sync의 핵심

```bash
moai project      # 프로젝트 분석, TDD/DDD 자동 선택, SPEC 폴더 생성
/moai:1-plan      # manager-spec이 .moai/specs/에 EARS 명세서 생성
/moai:2-run       # LSP 품질 게이트와 함께 구현 실행
/moai:3-sync      # 코드 ↔ 스펙 ↔ MX 주석 3방향 동기화 + Git 자동화
/moai:alfred      # 전체 자동화 (세 단계 병렬 실행)
```

**Sync 단계가 특히 중요하다.** 개발 중 DB 스키마가 UUID에서 시퀀스 번호로 바뀌는 등 코드가 스펙과 달라지면, Sync가 코드를 분석해 스펙 문서와 MX 주석을 모두 업데이트한다. 이 덕분에 6~7개월짜리 장기 프로젝트에서도 코드-문서 동기화가 유지된다. 스펙을 먼저 쓰는 방식과 비교하면, **코드가 진화해도 스펙이 따라간다**는 점이 이 도구의 차별점이다.

`/moai:alfred`와 `moai loop` 명령을 조합하면 미완료 스펙이 완료될 때까지 자동으로 반복 실행되는 야간 무인 개발도 가능하다.

### MX 태그 시스템: 토큰 효율의 비밀

MoAI-ADK는 각 함수와 파일 상단에 에이전트가 읽을 수 있는 맥락 주석(@MX 태그)을 자동으로 삽입한다. 에이전트는 전체 코드를 읽지 않고 MX 태그만 검색해 파일 간 관계와 위치를 파악하므로 토큰 낭비가 크게 줄어든다. 16개 언어를 지원하며, 스킬 시스템과 함께 컨텍스트 점유 최소화의 핵심 기제다.

**스킬 시스템**: 500토큰 이내의 핵심 참조 문서로, 에이전트가 필요할 때만 로드한다. 회사 내부 라이브러리(예: LangChain 특정 버전 사용법)를 커스텀 스킬로 추가할 수 있다. MCP도 스킬로 변환해 토큰 소모를 대폭 줄일 수 있다.

### 비용 최적화: 모델 역할 분담

> "앞으로 회사들의 IT 경쟁력은 토큰 사용량에 비례할 것이다. 스타트업은 토큰을 얼마나 효율화하느냐가 기술력에 비례한다."

MoAI-ADK는 모델을 역할에 따라 분리해 비용을 최적화한다:

| 모델 | 용도 |
|---|---|
| Opus | 스펙 작성, 아키텍처 판단 |
| Sonnet | 일반 코딩 |
| Haiku | 탐색, 배시 작업 등 단순 처리 |
| GLM 4.7 | 팀 모드의 Worker (비용 대비 성능 최적) |

**CG 모드**: Leader가 Claude API로 판단하고, Worker들이 GLM API로 실행하는 하이브리드 구조. Claude Code 구독 플랜의 rate limit 내에서 최대 품질을 뽑아낸다.

### 컨텍스트 관리 전략

컨텍스트 윈도우가 꽉 찼을 때의 대응도 체계적이다. 스펙 문서 3개(프로젝트 문서, 스택 문서, 요구사항 문서)가 체크리스트 역할을 하기 때문에, 세션이 끊겨도 새 세션에서 이 세 파일을 읽으면 바로 이어서 진행할 수 있다. Auto Compact에 의존하기보다 수동 compact 또는 export 후 서브 에이전트가 맥락을 추출해 재개하는 방식을 권장한다.

### 기술적 특징 요약

- **단일 바이너리**, 의존성 없음 (Go 34,220줄, 32 패키지)
- **18개 프로그래밍 언어** 지원
- **16개 Claude Code 훅 이벤트** 통합
- **Git 기반 메모리**: 세션 간 컨텍스트 보존
- **E2E 테스트**: Playwright 연동으로 UX 레벨 검증

---

## GitHub Spec Kit

### 개요

**Spec Kit**은 GitHub이 2025년 9월 공식 출시한 오픈소스 개발 툴킷이다. 72,000개 이상의 스타를 받으며 네 가지 중 가장 큰 커뮤니티를 보유하고 있다. 2026년 2월 기준 v0.1.4이며, GitHub Copilot, Claude Code, Cursor, Windsurf, Gemini CLI 등 17개 이상의 AI 코딩 에이전트와 통합된다.

```bash
uv tool install specify-cli --from git+https://github.com/github/spec-kit.git
```

### 핵심 철학

> "명세서가 '실행 가능'해져서 구현을 직접 생성할 수 있어야 한다. 단순히 개발을 안내하는 수준이 아니라."

Spec Kit은 전통적인 개발 워크플로우를 **뒤집는다**. 명세서를 일회용 스캐폴딩이 아닌 핵심 아티팩트로 취급해, "무엇을(what)"을 먼저 명확히 정의하고 "어떻게(how)"는 나중에 결정한다는 원칙이다.

네 가지 설계 원칙:
1. **인텐트 주도(Intent-driven)**: 스펙이 '무엇을'과 '왜'를 먼저 정의
2. **풍부한 명세서 생성**: 가드레일과 조직 원칙으로 제약된 스펙
3. **단계별 정제**: 단발성 프롬프트가 아닌 멀티스텝 정제
4. **고급 AI 활용**: 스펙 해석을 위해 모델의 고급 능력에 의존

### 6단계 워크플로우

```
/speckit.constitution  → 1단계: 프로젝트 거버넌스 원칙 수립
/speckit.specify       → 2단계: 요구사항 및 유저 스토리 정의
/speckit.clarify       → 3단계: 모호한 부분 명확화
/speckit.plan          → 4단계: 기술 아키텍처 계획 수립
/speckit.tasks         → 5단계: 실행 가능한 태스크 목록 생성
/speckit.implement     → 6단계: 구현 실행
```

**Constitution**이 특히 독특하다. 프로젝트 전반의 거버넌스 원칙을 미리 정의해두는 개념으로, 이후 모든 스펙과 구현이 이 헌법을 기준으로 평가된다. 기업의 클라우드 제공자 선택, 컴플라이언스 요구사항, 디자인 시스템 등을 여기에 담는다.

### 실사용 경험

Spec Kit은 GitHub이 직접 만든 만큼 높은 기대를 받았지만, 실사용 후기는 엇갈린다.

**Scott Logic의 리뷰 (Colin Eberhardt)** - KartLog 앱의 회로 관리 기능을 Spec Kit으로 재구현하는 실험:
- 피처 하나에 33~56분 소요 (기존 방식의 10배)
- 주기당 2,000줄 이상의 마크다운 생성 (실제 코드보다 문서가 더 많음)
- 단순한 버그(폼 데이터 미입력)가 여전히 발생 - 상세한 스펙이 있음에도
- **결론**: "흥미로운 개념이지만, 순수한 형태로는 비실용적. 애자일의 핵심 장점인 빠른 코드 생성을 낭비하는 재발명된 워터폴"

**긍정적인 측면:**
- 팀 협업 시 명시적인 검토 포인트를 만들어줌 - 코드 변경이 쌓이기 전에 스펙 단계에서 거부/수정 가능
- 기술 스택에 무관하게 동작 (Python, JS, Go, Rust 등 어디서나)
- 그린필드 + 브라운필드 모두 지원
- Constitution 기반 일관성이 장기 프로젝트에서 빛남

---

## Get Shit Done (GSD)

### 개요

**GSD**는 코스타리카에 거주하는 하우스 뮤직 프로듀서 Lex Christopherson(GitHub: `glittercowboy`)이 2025년 12월에 공개한 프레임워크다. 본인이 직접 코드를 작성하지 않는 "pro vibe coder"로서, Claude Code만으로 프로젝트를 빌드하다가 기존 엔터프라이즈급 도구들의 오버헤드에 좌절하며 만들었다.

공개 57일 만에 **10만 다운로드**, 3개월 만에 **35,000 스타**를 달성했다. v1.26.0까지 출시되었고 활발히 개발 중이다.

```bash
npx get-shit-done-cc@latest
```

### 핵심 철학

> "No enterprise roleplay bullshit. Just an incredibly effective system for building cool stuff consistently using Claude Code."

GSD의 포지셔닝은 명확하다: **Vibe Coding과 엔터프라이즈 스펙 도구 사이의 중간 지점**이다. Vibe Coding(아이디어를 대충 설명하고 AI 결과를 그대로 수용)은 규모가 커지면 반드시 실패하고, BMAD나 Spec Kit 같은 도구들은 스프린트 세레모니, 스토리 포인트 같은 엔터프라이즈 오버헤드를 요구한다. GSD는 **복잡성을 시스템 내부에 숨기고 사용자에게는 단순한 슬래시 커맨드만 노출**한다.

세 가지 핵심 원칙:
1. **메타 프롬프팅(Meta-Prompting)**: AI에게 *무엇을* 하라가 아니라 *어떻게 생각하라*고 지시. 역할, 제약, 추론 방식, 출력 형식을 사전에 설정
2. **컨텍스트 엔지니어링(Context Engineering)**: AI 모델에 제공되는 정보를 의도적으로 설계하고 유지. 시스템 프롬프트, 컨텍스트 파일, 세션 간 메모리 핸드오프를 체계적으로 관리
3. **스펙 기반 개발(Spec-Driven Development)**: 구현 전에 상세한 명세를 작성. 기능 개요, 기술 요구사항, 데이터 모델, 엣지 케이스, 수락 기준을 포함

### 컨텍스트 로트(Context Rot): GSD가 해결하는 핵심 문제

AI의 컨텍스트 윈도우가 채워지면서 발생하는 **품질 저하 현상**이 GSD가 가장 집중하는 문제다:

| 컨텍스트 활용률 | 품질 |
|---|---|
| 0-30% | 최고 품질, 꼼꼼한 작업 |
| 30-50% | 양호하지만 서두르기 시작 |
| 50-70% | 코너 컷팅, 요구사항 누락 |
| 70%+ | 환각(hallucination), 요구사항 망각 |

GSD의 해결 전략:
- **에이전트 격리**: 리서처, 플래너, 실행기, 검증기는 각각 **fresh한 200K 토큰 컨텍스트 윈도우**를 받음. 이전 대화의 "쓰레기"를 가져가지 않음
- **메인 세션 경량화**: 오케스트레이터(메인 세션)는 직접 작업하지 않고 서브 에이전트를 조율만 하므로, **30-40% 컨텍스트 활용률** 유지
- **정밀 컨텍스트 주입**: 실행기가 코드를 작성할 때, 로드맵과 해당 태스크의 XML 계획만 정확히 주입
- **상태 파일 기반 세션 간 메모리**: `STATE.md`가 결정사항, 블로커, 현재 위치를 기록하여 새 세션에서도 컨텍스트를 빠르게 복원

### 멀티 에이전트 오케스트레이션

GSD는 단일 대화 컨텍스트를 전문화된 서브 에이전트 시스템으로 변환한다:

| 단계 | 오케스트레이터 역할 | 에이전트 역할 |
|---|---|---|
| **리서치** | 조율, 결과 발표 | 4개의 병렬 리서처가 스택/기능/아키텍처/함정 조사 |
| **계획** | 검증, 반복 관리 | Planner가 생성, Checker가 검증, 통과까지 반복 |
| **실행** | 웨이브 그룹화, 진행 추적 | Executor가 fresh 200K 컨텍스트에서 병렬 구현 |
| **검증** | 결과 발표, 라우팅 | Verifier가 목표 점검, Debugger가 실패 진단 |

### 6단계 워크플로우

```bash
/gsd:new-project      # 1단계: 프로젝트 초기화 (질문 → 리서치 → 요구사항 추출)
/gsd:discuss-phase N  # 2단계: 구현 전 회색 지대 식별, 선호도 캡처
/gsd:plan-phase N     # 3단계: XML 구조의 원자적 태스크 계획 생성
/gsd:execute-phase N  # 4단계: 웨이브 기반 병렬 실행 + 원자적 git 커밋
/gsd:verify-work N    # 5단계: 자동 검증 + UAT
/gsd:ship N           # 6단계: PR 생성 → 다음 페이즈로 반복
```

**XML 구조화 계획**이 GSD의 특징이다. 각 태스크는 Claude에 최적화된 XML로 정의된다:

```xml
<task type="auto">
  <name>로그인 엔드포인트 생성</name>
  <files>src/app/api/auth/login/route.ts</files>
  <action>
    JWT에 jose 사용 (jsonwebtoken 아님 - CommonJS 이슈).
    users 테이블에서 자격 증명 검증.
    성공 시 httpOnly 쿠키 반환.
  </action>
  <verify>curl -X POST localhost:3000/api/auth/login이 200 + Set-Cookie 반환</verify>
  <done>유효한 자격 증명이 쿠키를 반환, 무효하면 401 반환</done>
</task>
```

각 태스크에 이름, 대상 파일, 구체적 액션, **자동 검증 가능한 bash 명령**, 완료 기준이 명시된다.

### 웨이브 기반 병렬 실행

실행 단계에서 계획을 의존성 기반 웨이브로 그룹화한다:

- **Wave 1 (병렬)**: 독립적 기초 태스크들
- **Wave 2 (병렬)**: Wave 1에 의존하는 태스크들
- **Wave 3 (순차)**: 누적 컨텍스트가 필요한 태스크들

각 태스크 완료 시 **원자적 git 커밋**이 생성되어, `git bisect`로 정확히 어떤 AI 실행 청크가 버그를 도입했는지 특정할 수 있다.

### 모델 프로필 시스템

| 프로필 | 계획 | 실행 | 검증 |
|---|---|---|---|
| `quality` | Opus | Opus | Sonnet |
| `balanced` (기본) | Opus | Sonnet | Sonnet |
| `budget` | Sonnet | Sonnet | Haiku |

### 지원 AI 도구

GSD는 6개 이상의 AI 런타임을 공식 지원한다:

| 런타임 | 커맨드 형식 |
|---|---|
| Claude Code | `/gsd:help` |
| OpenCode | `/gsd-help` |
| Gemini CLI | `/gsd:help` |
| Codex | `$gsd-help` |
| GitHub Copilot CLI | `/gsd:help` |

### GSD-2로의 진화

2026년 3월, GSD-2가 발표되었다. v1이 "마크다운 프롬프트 모음"이었다면, GSD-2는 **Pi SDK 기반의 독립형 TypeScript CLI**로 근본적인 아키텍처 전환을 이뤘다:

- v1: 슬래시 커맨드로 Claude Code에 설치, LLM이 해석
- v2: **상태 머신 애플리케이션**이 실행 파이프라인을 프로그래밍적으로 제어
- 크래시 복구, 비용 추적, stuck-loop 감지 기능 추가
- Git worktree를 사용한 branch-per-slice 격리
- Auto 모드에서 **6시간 57분간 자율 작업** 실행 성공 사례 보고

### 실사용 경험

**좋은 점:**
- 솔로 개발자/소규모 팀에 최적화된 경량 워크플로우
- 원자적 커밋으로 모든 AI 작업이 추적 가능
- Quick Mode(`/gsd:quick`)로 전체 계획 없이 ad-hoc 태스크도 GSD 품질로 실행 가능
- 세션 간 작업 연속성: `/gsd:pause-work` → `HANDOFF.json` 생성 → `/gsd:resume-work`로 복원

**어려운 점:**
- **토큰 소비가 매우 높다.** 오케스트레이션 토큰 대 구현 토큰 비율이 약 4:1
- 계획 단계가 지나치게 길어질 수 있다. "80%+ 계획, 20% 구현"이라는 불만
- 서브 에이전트가 자체 생성한 트랜스크립트를 파싱하지 못하는 경우 보고
- 단순한 프로젝트에는 과잉 엔지니어링

---

## 커뮤니티의 목소리

네 가지 도구 모두 실사용자들의 반응이 갈린다. 직접적인 커뮤니티 반응을 정리했다.

### BMAD Method

**성공 사례:**

> "I tried B-MAD Framework and it was like night and day. Can't work without it."
> - g42gregory, Hacker News

> "I built this MVP in a single day using the BMad Method with GitHub Copilot."
> - GenericApple, Hacker News (FastAPI + HTMX 앱)

> "Pretty surprised BMAD-method wasn't mentioned. For my money it's by far the best Claude Code compliment... completely transformative."
> - matt3D, Hacker News

**비판:**
- GitHub에 110개 이상의 오픈 이슈가 있어, 안정성 문제가 존재한다. 설치 시 race condition으로 소스 파일이 삭제되는 버그(#2005), PRD를 건너뛰면 "out-of-context" 실행 오류(#2038) 등이 보고됨
- AI 도구가 AI 도구가 생성한 YAML/마크다운에서 이슈를 찾는 상황에 대해 "이게 뭐 하는 건가"라는 근본적 회의도:

> "An AI tool finding issues in a set of YAML and Markdown files generated by an AI tool, and humans puzzled by all of it."
> - imiric, Hacker News

### MoAI-ADK

영어권 커뮤니티(Hacker News, Reddit)에서의 논의는 거의 없다. 841 스타에 비해 공개 피드백이 극히 적어, "스타만 누르고 실사용은 적은" 패턴일 가능성이 있다. GitHub 오픈 이슈도 2건뿐이다.

한국 개발자 커뮤니티(GeekNews 등)에서도 뚜렷한 토론을 찾기 어렵다. Claude Code 전용이라는 제약이 커뮤니티 확장의 병목일 수 있다.

### GitHub Spec Kit

가장 날카로운 비판을 받는 도구다. GitHub 공식이라는 기대감 때문에 실망도 큰 편이다.

**"워터폴 재발명" 비판:**

> "Really, we are doing _waterfall, but with AI_, now?"
> - constantcrying, Hacker News

> "I tried SDD, consciously trying to like it, but gave up. I find writing specs much harder than writing code."
> - zvr, Hacker News

**Martin Fowler 팀의 분석** - 가장 체계적인 리뷰:
- 스펙당 **8개의 별도 파일**을 생성하며, 리뷰가 "반복적이고 지루하다"
- 큰 컨텍스트 윈도우에도 불구하고 에이전트가 **지시를 무시**하는 경우 빈번
- 기존 코드 설명을 새 스펙으로 오해하여 **중복 클래스를 생성**
- "small, iterative steps"가 베스트 프랙티스인데 SDD는 대규모 사전 설계를 요구 - 근본적 불일치

**실제 프로젝트 경험:**

> 첫 프로젝트에 10일 소요, "huge gap" 남음, 테스트 실패. AI가 "declares the sprint as done even though tests still fail."
> - yoaviram, Hacker News

> "Generated steps that were equivalent of Tony Stark building a robot from scratch in a cave when just 'screw this bolt on' would have sufficed."
> - ctxc, Hacker News

**긍정적 경험도 있다.** Den Delimarsky는 카메라 앱을 **2시간 이내**에 아이디어에서 동작하는 앱까지 완성했다고 보고했다.

### Get Shit Done (GSD)

가장 활발하게 논의되는 도구이지만, 호불호가 극명하게 갈린다.

**토큰 소비 - 가장 빈번한 불만:**

> "I burned literally a weeks worth of the $20 Claude subscription and then $20 worth of API credits on GSD v2. To get like 500 LOC... I had better experiences just guiding the thing myself."
> - sigbottle, Hacker News

> "Plan Mode had a plan and base implementation in twenty minutes. GSD ran for hours to achieve the same thing."
> - healsdata, Hacker News

> "GSD is a highly overengineered piece of software that unfortunately does not get shit done, burns limits and takes ages while doing so."
> - yolonir, Hacker News

**복잡성 비판:**

> "way too much back and forth... 80%+ planning... didn't need this for implementation."
> - vinnymac, Hacker News

> "way too much of a black box for me as an engineer, not a prompter."
> - ricardo_lien, Hacker News

**성공 사례도 분명히 존재한다:**

> "GSD consistently gets me 95% of the way there on complex tasks... We've used GSD to build and launch a SaaS product."
> - yoaviram, Hacker News (3개월간 집중 사용, whiteboar.it SaaS 출시)

한 솔로 개발자는 macOS Swift 앱을 GSD로 개발해 App Store 출시를 검토 중이라고 보고했다.

### 공통 테마

네 도구의 커뮤니티 반응에서 반복적으로 등장하는 패턴이 있다:

1. **토큰 소비**: SDD 프레임워크 전반의 가장 큰 불만. "프레임워크가 일반 사용 대비 10배 더 토큰을 소비한다"
2. **워터폴 회귀**: Spec Kit에 특히 강하지만, 모든 스펙 기반 도구에 해당하는 비판
3. **브라운필드 적용 어려움**: 모든 도구가 그린필드 프로젝트 튜토리얼만 풍부하고, 레거시 코드베이스 적용 사례는 부족
4. **리뷰 부담**: 마크다운 파일 과다 생성으로 "리뷰가 코드 리뷰보다 더 힘들다"
5. **성공 패턴**: 복잡한 프로젝트에서 인내심을 갖고 사용하면 효과적. 단순한 프로젝트에는 과잉

---

## 네 가지 비교 정리

### 철학 비교

| | BMAD | MoAI-ADK | Spec Kit | GSD |
|---|---|---|---|---|
| 핵심 가치 | **협업** | **품질** | **명확성** | **경량화** |
| AI 역할 | 전문 협업자 | 지능형 오케스트레이터 | 스펙 해석기 | 격리된 서브 에이전트 |
| 접근 방식 | 역할 기반 에이전트 | 단계별 품질 게이트 | 문서 주도 개발 | 컨텍스트 엔지니어링 |
| 인간의 역할 | 감독자 + 의사결정자 | SPEC 작성자 | 스펙 정의자 | 아이디어 제공자 |
| 타겟 | 팀 / 엔터프라이즈 | 품질 중시 개발자 | 기술 스택 무관 팀 | 솔로 / 소규모 팀 |

### 워크플로우 비교

| | BMAD | MoAI-ADK | Spec Kit | GSD |
|---|---|---|---|---|
| 단계 수 | 4단계 | 3단계 (+루프) | 6단계 | 6단계 (웨이브) |
| 자동화 수준 | 중간 (에이전트 조율) | 높음 (Alfred 자율 + 루프) | 낮음 (단계별 수동 진행) | 높음 (서브 에이전트 병렬) |
| 결과물 | YAML 워크플로우 + 코드 | SPEC + MX 주석 + 코드 | Constitution + Spec + Plan + Tasks + 코드 | .planning/ + XML 계획 + 코드 |
| 속도 | 중간 | 빠름 (병렬 실행) | 느림 (많은 문서화) | 중간 (계획 오래, 실행 빠름) |
| 컨텍스트 관리 | 에이전트별 분리 | SPEC + MX 태그 기반 복원 | 단계별 문서로 재개 | 서브 에이전트 격리 + STATE.md |

### 기술 비교

| | BMAD | MoAI-ADK | Spec Kit | GSD |
|---|---|---|---|---|
| 구현 언어 | JavaScript | Go | Python | JavaScript (v1) / TypeScript (v2) |
| 에이전트 수 | 12+ 페르소나 | 20개 전문 에이전트 | 에이전트 없음 | 4종 (리서처/플래너/실행기/검증기) |
| 설치 | `npx bmad-method install` | 단일 바이너리 | `uv tool install` | `npx get-shit-done-cc@latest` |
| AI 도구 통합 | Claude Code 등 | Claude Code 전용 | 17개+ AI 도구 | 6개+ (Claude Code, Gemini, Codex 등) |
| 비용 | 높음 (많은 토큰) | 최적화됨 (역할별 모델 + CG 모드) | 도구에 따라 다름 | 높음 (오케스트레이션 4:1 비율) |

### 커뮤니티 비교

| | BMAD | MoAI-ADK | Spec Kit | GSD |
|---|---|---|---|---|
| Stars | 38k | 841 | 72k | 35k |
| 성숙도 | 높음 (v6, 23개 릴리즈) | 중간 (활발히 개발 중) | 낮음 (v0.1.4, 실험적) | 중간 (v1.26, 3개월 만에 빠른 발전) |
| 문서 | 풍부 | 한/영/일/중 다국어 | GitHub 공식 지원 | 풍부 (DEV Community 가이드 다수) |
| Discord | 있음 | 있음 | 없음 (Discussions) | 있음 |
| 창시자 배경 | 개발자 커뮤니티 | GPT 서비스 개발 실패 경험 | GitHub 공식 | 비개발자 (음악 프로듀서) |

---

## 어떤 상황에 어떤 도구를?

### BMAD Method를 선택해야 할 때

- **팀 단위 개발** - 에이전트 역할이 팀 내 역할 분담을 자연스럽게 반영
- **엔터프라이즈 / 규제 업종** - 감사 가능한 아티팩트와 거버넌스 필요 시
- **레거시 시스템 현대화** - 비즈니스 로직 추적이 중요한 경우
- **애자일 프로세스가 이미 익숙한 팀** - PM-아키텍트-개발자 역할 분리가 자연스러운 환경

### MoAI-ADK를 선택해야 할 때

- **코드 품질이 최우선인 프로젝트** - 단순 기능 구현이 아니라 프로덕션 수준의 코드 필요
- **Claude Code를 주 도구로 사용하는 개발자** - 훅 통합과 최적화가 Claude Code에 맞춰져 있음
- **장기 프로젝트** - Sync의 3방향 동기화 덕분에 수개월 후에도 코드-문서 일관성 유지
- **기존 프로젝트 리팩토링** - DDD 사이클의 ANALYZE-PRESERVE-IMPROVE가 안전한 점진적 개선에 적합
- **API 비용 최적화** - 역할별 모델 분리 + CG 모드로 고비용 모델 사용 최소화
- **한국어 환경** - 다국어 README와 한국 커뮤니티

### GitHub Spec Kit을 선택해야 할 때

- **특정 AI 도구에 종속되기 싫은 경우** - 17개+ 도구 지원, 기술 스택 무관
- **문서화가 중요한 팀** - 상세한 스펙, 플랜, 태스크 아티팩트를 체계적으로 관리
- **그린필드 프로젝트의 초기 설계** - Constitution으로 일관된 거버넌스 원칙 수립
- **GitHub 생태계 활용** - Copilot과의 통합이 자연스럽고 GitHub 공식 지원

### Get Shit Done을 선택해야 할 때

- **솔로 개발자 / 소규모 팀** - 엔터프라이즈 오버헤드 없이 스펙 기반 개발의 이점을 원할 때
- **컨텍스트 로트가 주요 고민인 경우** - 서브 에이전트 격리로 항상 fresh 컨텍스트 보장
- **빠른 프로토타이핑 → 프로덕션** - Quick Mode로 ad-hoc 작업, 전체 워크플로우로 정식 개발
- **여러 AI 도구를 쓰는 경우** - Claude Code, Gemini CLI, Codex 등 6개+ 런타임 지원
- **비개발자/주니어 개발자** - 복잡성이 시스템에 숨겨져 있어 진입 장벽이 낮음

---

## 내 생각

네 도구 모두 결국 같은 문제를 다루고 있다: **AI에게 일을 시킬 때 어떻게 하면 엉망이 안 되는가.**

흥미로운 점은 이들의 해답이 정반대에 가깝다는 것이다:

- **Spec Kit**은 "더 많이 계획하라"고 말한다. 코드보다 문서를 먼저, 그리고 더 많이.
- **BMAD**는 "AI에게 역할을 줘라"고 말한다. 구조화된 에이전트 협업으로 일관성을 만든다.
- **MoAI-ADK**는 "품질 게이트를 걸어라"고 말한다. 자동화된 검증으로 결과물을 보증한다.
- **GSD**는 "컨텍스트를 관리하라"고 말한다. 격리된 서브 에이전트로 항상 fresh한 상태를 유지한다.

GSD의 등장은 특히 흥미롭다. 코드를 직접 쓰지 않는 음악 프로듀서가 만든 도구가 3개월 만에 35K 스타를 달성했다는 것은, 이 문제가 전문 개발자만의 고민이 아니라는 뜻이다. "pro vibe coder"라는 새로운 카테고리의 사용자들이 등장하고 있고, GSD는 그들의 목소리를 대변한다.

Goos Kim의 라이브에서 인상 깊었던 말이 있다:

> "2022년 11월 30일에 ChatGPT 3.5가 나오고 나서 느꼈던 게 뭔가 하면... 전 세계 모든 개발자 리셋이다. 오늘부터 1대1 모두. 프롬프트 엔지니어링부터 모든 환경이 달라지니까."

네 도구의 탄생 배경을 보면 이 말이 더 와닿는다. 개인 실패 경험에서 MoAI-ADK가, 레거시 시스템과의 사투에서 BMAD가, GitHub의 공식 문제 의식에서 Spec Kit이, 비개발자의 코딩 좌절에서 GSD가 나왔다. 방향은 달라도 모두 같은 현실을 마주하고 있다.

그런데 커뮤니티 반응을 보면, 모든 도구에 공통적인 불만이 있다: **토큰 소비**. "프레임워크가 10배 더 토큰을 소비한다"는 지적은 GSD뿐 아니라 거의 모든 SDD 프레임워크에 해당한다. Plan Mode 하나로 충분하다는 의견도 강하다. 결국 이 도구들이 정당화되려면 "더 많은 토큰을 쓰지만 재작업이 줄어서 전체적으로는 효율적"이라는 것을 증명해야 한다.

또 하나 흥미로운 점은 "프레임워크를 30-50%만 커스터마이즈해서 쓰는 것이 가장 효과적"이라는 경험자들의 조언이다. 어떤 도구든 100% 그대로 쓰기보다, 자신의 워크플로우에 맞게 취사선택하는 것이 현실적인 접근일 수 있다.

네 도구가 앞으로 어떻게 수렴하거나 발산할지 지켜보는 것 자체가 흥미롭다. AI 개발 방법론은 지금 막 형성되는 중이다.

---

## 참고 자료

- [BMAD Method GitHub](https://github.com/bmad-code-org/BMAD-METHOD)
- [MoAI-ADK GitHub](https://github.com/modu-ai/moai-adk)
- [GitHub Spec Kit](https://github.com/github/spec-kit)
- [Get Shit Done GitHub](https://github.com/gsd-build/get-shit-done)
- [GSD-2 GitHub](https://github.com/gsd-build/gsd-2)
- [모아이 ADK 소개 라이브 스트림 - Goos Kim 인터뷰](https://www.youtube.com/live/mFBaEZ4VAGI)
- [Applied BMAD - Reclaiming Control in AI Development](https://bennycheung.github.io/bmad-reclaiming-control-in-ai-dev)
- [Putting Spec Kit Through Its Paces: Radical Idea or Reinvented Waterfall?](https://blog.scottlogic.com/2025/11/26/putting-spec-kit-through-its-paces-radical-idea-or-reinvented-waterfall.html)
- [Spec-Driven Development with AI - GitHub Blog](https://github.blog/ai-and-ml/generative-ai/spec-driven-development-with-ai-get-started-with-a-new-open-source-toolkit/)
- [BMAD: The Agile Framework That Makes AI Actually Predictable - DEV Community](https://dev.to/extinctsion/bmad-the-agile-framework-that-makes-ai-actually-predictable-5fe7)
- [MoAI-ADK DeepWiki](https://deepwiki.com/modu-ai/moai-adk)
- [Stop Context Rot: How GSD Powers the Ultimate 10x Agentic Engine](https://hoangyell.com/get-shit-done-explained/)
- [The Complete Beginner's Guide to GSD Framework - DEV Community](https://dev.to/alikazmidev/the-complete-beginners-guide-to-gsd-get-shit-done-framework-for-claude-code-24h0)
- [GSD-2: The AI Coding Agent That Controls Its Own Context Window - Medium](https://medium.com/@sajith_k/gsd-2-the-ai-coding-agent-that-actually-controls-its-own-context-window-fb04706b081e)
- [Hacker News 토론 - Get Shit Done](https://news.ycombinator.com/item?id=47417804)
- [GeekNews/하다뉴스 - Get Shit Done](https://news.hada.io/topic?id=27622)
