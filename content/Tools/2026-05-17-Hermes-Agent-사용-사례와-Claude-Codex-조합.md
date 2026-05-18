---
title: "Hermes Agent 사용 사례와 Claude Code + Codex 조합 전략"
date: 2026-05-17
tags:
  - Hermes-Agent
  - Claude-Code
  - Codex
  - AI-Agent
  - AI도구
  - 생산성
  - Tools
draft: false
enableToc: true
description: Hermes Agent와 Codex CLI, Claude Code의 차이를 정리하고, 프로젝트·팀·조직 지식을 수집·통합·검색·권한 관리하는 운영 모델까지 살펴본다.
summary: "Hermes Agent는 모델이 아니라 작업 실행 레이어다. Codex를 Hermes의 메인 모델로 연결해도 Slack, 메모리, 스킬, cron, MCP, PR 관리가 붙는다는 점에서 Codex CLI 단독 사용과 다르다. 여기에 프로젝트→팀→조직으로 지식을 수집·통합하고, 검색 가능한 second brain과 권한 관리까지 붙이는 운영 모델을 정리했다."
published: 2026-05-17
modified: 2026-05-17
---

## 들어가며

요즘 AI 코딩 도구를 쓰다 보면 선택지가 너무 많다. Cursor, Claude Code, Codex, Gemini CLI, Devin류 서비스까지 각자 장점이 다르다. 그런데 실제 업무에서는 "어떤 모델이 더 똑똑한가"보다 더 중요한 문제가 있다.

> 내가 쓰는 채팅창, 터미널, GitHub, 로컬 파일, 서버 작업을 하나의 흐름으로 묶을 수 있는가?

[Hermes Agent](https://hermes-agent.nousresearch.com/docs/)는 이 지점에 초점을 둔 오픈소스 AI 에이전트 프레임워크다. 단순한 챗봇이나 IDE 플러그인이 아니라, 터미널·메신저·스케줄러·MCP·파일 시스템·브라우저·GitHub 워크플로우를 연결해 "일을 끝내는" 쪽에 가깝다.

이 글에서는 Hermes Agent의 대표 사용 사례를 정리하고, 특히 **Hermes를 Codex 메인 모델로 연결해서 쓰는 것과 Codex CLI를 그냥 쓰는 것의 차이**를 따로 짚는다. 처음엔 나도 Hermes, Codex, Claude Code를 서로 다른 코딩 도구처럼만 나눠서 생각했는데, 실제로는 층위가 다르다. Hermes는 작업 실행 레이어이고, Codex나 Claude는 그 안에 꽂는 모델 또는 하위 도구에 가깝다.

---

## Hermes Agent 한 줄 요약

Hermes Agent는 Nous Research가 만든 **자기 개선형(self-improving) AI 에이전트**다. 공식 문서에서는 Hermes를 "경험으로부터 스킬을 만들고, 사용 중 스킬을 개선하며, 세션을 넘어 사용자를 이해하는 에이전트"로 설명한다.

핵심은 다음 네 가지다.

1. **어디서나 실행**: 로컬 터미널뿐 아니라 Slack, Telegram, Discord, WhatsApp, Email 등 메시징 플랫폼에서 호출 가능
2. **도구 실행**: 파일 편집, 터미널 명령, 웹 검색, 브라우저 자동화, 이미지/음성 도구, GitHub 작업 등을 도구로 수행
3. **지속 기억**: 사용자 선호, 프로젝트 구조, 반복되는 워크플로우를 메모리와 스킬로 보존
4. **모델 독립성**: OpenAI Codex, Anthropic, OpenRouter, Gemini, GitHub Copilot, 로컬 OpenAI 호환 엔드포인트 등 다양한 provider를 선택 가능

즉 Hermes는 "하나의 모델"이라기보다 **여러 모델과 도구를 엮는 작업 운영체제**에 가깝다.

## Hermes에 Codex를 연결한다는 뜻

여기서 헷갈리기 쉬운 부분이 있다.

"Hermes를 Codex로 쓴다"는 말은 보통 **Hermes의 메인 LLM provider를 OpenAI/Codex 계열로 둔다**는 뜻이다. 이 경우 실제 추론은 GPT-5.5나 Codex 계열 모델이 하지만, 작업을 받는 입구와 도구 실행 방식은 Hermes가 관리한다.

반대로 "Codex를 그냥 쓴다"는 말은 보통 Codex CLI를 터미널에서 직접 실행한다는 뜻이다.

| 구분 | Codex CLI 단독 | Hermes + Codex provider |
|---|---|---|
| 기본 입구 | 터미널 | 터미널, Slack, Telegram, Discord 등 |
| 기억 | 세션/레포 컨텍스트 중심 | 장기 memory, skill, session search |
| 반복 작업 | 직접 스크립트화 필요 | cron job, webhook, gateway delivery |
| 도구 확장 | Codex CLI가 제공하는 범위 | Hermes toolset, MCP, 브라우저, 파일, 웹, 이미지, 음성 |
| GitHub 작업 | 가능하지만 직접 흐름 관리 | 브랜치, 커밋, PR, CI 확인을 한 흐름으로 묶기 좋음 |
| 모델 교체 | Codex 계열 중심 | OpenAI, Anthropic, OpenRouter, Gemini, 로컬 endpoint 등 교체 가능 |

그래서 둘은 경쟁 관계라기보다 계층이 다르다. Codex CLI는 "코딩 실행기"에 가깝고, Hermes는 그 실행기를 포함해 여러 도구를 호출하는 "작업 관리자"에 가깝다.

내가 Slack에서 "블로그 글 만들고 PR 올려줘"라고 시키는 상황을 생각하면 차이가 확실하다. Codex CLI 단독이면 터미널을 열고 레포 안에서 직접 실행해야 한다. Hermes + Codex provider라면 Slack 메시지를 입구로 삼고, 레포 위치 기억, 문서 조사, 파일 수정, 빌드, 커밋, PR 생성까지 한 번에 이어갈 수 있다.

---

## 사용 사례 1. Slack/Telegram에서 바로 작업시키기

Hermes의 가장 체감되는 장점은 [Messaging Gateway](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/)다. Gateway를 켜두면 Slack, Telegram, Discord 같은 메신저에서 Hermes에게 직접 일을 시킬 수 있다.

예를 들어 Slack에서 다음처럼 요청할 수 있다.

```text
Hermes Agent 사용 사례 조사해서 내 블로그 레포에 글 만들고 PR 올려줘
```

그러면 Hermes는 대화창 안에서:

1. 레포 위치를 확인하고
2. 공식 문서를 조사하고
3. Markdown 글을 작성하고
4. 로컬 빌드를 검증하고
5. 브랜치를 만들고 커밋한 뒤
6. GitHub PR까지 생성한다.

이 흐름은 IDE 안에서만 동작하는 코딩 어시스턴트와 다르다. 사용자는 노트북을 열지 않아도 되고, 모바일 메신저에서 지시만 내려도 된다. Hermes 문서도 Gateway가 "하나의 백그라운드 프로세스"로 여러 플랫폼을 연결하고, 플랫폼별 세션과 cron job까지 관리한다고 설명한다.

### 언제 유용한가?

- 이동 중 Slack/Telegram으로 간단한 PR 요청
- 서버에서 돌고 있는 장기 작업 모니터링
- 배포 후 로그 확인 및 요약
- 블로그 초안, 리서치 노트, 이슈 정리 자동화
- 팀 채널에서 에이전트를 호출해 반복 업무 처리

---

## 사용 사례 2. 메모리와 스킬로 "다시 설명하지 않기"

Hermes에는 두 종류의 장기 기억이 있다.

- **Memory**: 사용자 선호, 프로젝트 위치, 환경 정보 같은 짧은 사실
- **Skills**: 반복 가능한 절차를 담은 Markdown 기반 워크플로우 문서

[Persistent Memory 문서](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory/)에 따르면 Hermes는 `~/.hermes/memories/` 아래의 메모리를 세션 시작 시 시스템 프롬프트에 주입한다. 예를 들면 "사용자는 GitHub 레포를 `/Users/.../Desktop/...` 아래에 둔다" 같은 정보가 다음 세션에도 살아 있다.

[Skills System](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills/)은 더 절차적이다. 예를 들어 "GitHub PR 만들기", "Claude Code 호출하기", "블로그 글 작성하기" 같은 반복 작업을 스킬로 만들면 Hermes가 필요할 때 해당 문서를 로드한다.

이게 중요한 이유는 간단하다.

> AI 도구를 오래 쓰다 보면 성능 차이보다 "내 환경을 매번 다시 설명해야 하는 비용"이 더 크게 느껴진다.

Hermes의 메모리/스킬 구조는 이 비용을 줄인다. 단순히 대화 기록을 길게 유지하는 방식이 아니라, 필요한 사실과 절차를 압축해서 다음 작업의 기본 컨텍스트로 삼는다.

---

## 사용 사례 3. Cron으로 정기 작업 자동화하기

Hermes는 [Scheduled Tasks(Cron)](https://hermes-agent.nousresearch.com/docs/user-guide/features/cron/) 기능을 제공한다. 자연어로 "매일 오전 9시에 뉴스 요약해서 보내줘"라고 요청하면 cron job으로 등록할 수 있다.

활용 예시는 다음과 같다.

- 매일 아침 AI 뉴스, Hacker News, arXiv 요약 받기
- 매주 블로그 소재 후보 수집하기
- 정해진 시간에 서버 상태 확인 후 Slack에 보고하기
- GitHub PR/CI 상태를 주기적으로 확인하기
- RSS 피드나 특정 웹페이지 변경 감지하기

흥미로운 점은 cron job도 skill을 로드할 수 있다는 것이다. 예를 들어 `blogwatcher` 스킬과 `maps` 스킬을 함께 붙여 "동네 행사와 새 글을 합쳐 브리핑" 같은 작업을 만들 수 있다.

또한 `no_agent` 모드에서는 LLM 없이 스크립트 출력만 전달할 수 있다. 단순 모니터링에는 비용을 아끼고, 요약·판단이 필요한 작업에만 LLM을 쓰는 구조다.

---

## 사용 사례 4. MCP로 외부 도구 붙이기

Hermes는 [MCP(Model Context Protocol)](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp/)를 지원한다. MCP는 외부 도구 서버를 에이전트에 붙이는 표준 인터페이스다.

MCP로 연결할 수 있는 예시는 다음과 같다.

- GitHub
- 데이터베이스
- 파일 시스템
- 브라우저 자동화
- 사내 API
- 다른 MCP 호환 서비스

Hermes는 MCP 서버의 도구를 시작 시 자동 등록하고, `mcp_<server>_<tool>` 같은 이름으로 충돌을 피한다. 이 구조 덕분에 Hermes 자체에 모든 도구를 네이티브로 구현하지 않아도 된다. 이미 MCP 서버가 있는 도구라면 설정만 추가해서 Hermes의 작업 범위를 넓힐 수 있다.

---

## 사용 사례 5. 코딩 에이전트 오케스트레이션

Hermes는 직접 코드를 수정할 수도 있지만, 필요하면 다른 코딩 에이전트를 호출하는 **오케스트레이터**로도 쓸 수 있다.

대표 조합은 다음과 같다.

| 역할 | 추천 도구 | 이유 |
|---|---|---|
| 전체 작업 지휘 | Hermes Agent | Slack/터미널에서 요청 수신, 레포 탐색, 브랜치/PR 관리, 결과 보고 |
| 빠른 구현 | Codex CLI | 터미널 기반 경량 코딩 에이전트, ChatGPT 계정/OAuth 활용 가능 |
| 깊은 코드 리뷰/설계 검토 | Claude Code | 코드베이스 이해, 리뷰, 계획 수립, 복잡한 리팩토링에 강점 |
| 장기/정기 작업 | Hermes Cron | 주기 실행, 결과 전달, 스크립트+LLM 조합 |

이때 Hermes는 "모든 일을 직접 하는 에이전트"라기보다, **어떤 하위 에이전트에게 어떤 일을 맡길지 결정하고 결과를 검증하는 관리자**로 동작한다.

---

## GPT-5.5와 Claude Opus 4.7 기준 역할 나누기

2026년 기준으로 보면 GPT-5.5와 Claude Opus 4.7은 둘 다 코딩을 잘한다. 다만 성향이 다르다. 공개 페이지 기준으로 GPT-5.5는 OpenRouter에서 1M급 컨텍스트, 텍스트+이미지 입력, 복잡한 전문 작업과 코딩을 강조한다. Anthropic은 Opus 4.7을 발표하면서 고난도 소프트웨어 엔지니어링, 긴 agentic task, 지시 이행, 고해상도 이미지 이해, 문서/슬라이드 같은 전문 산출물 품질을 강조했다.

내 기준의 결론은 이렇다.

| 작업 | 더 자주 먼저 쓰고 싶은 쪽 | 이유 |
|---|---|---|
| 작은 버그 수정, 테스트 추가, 명확한 구현 | GPT-5.5 / Codex | 빠르고 도구 호출 흐름이 안정적이다. 구현 지시가 명확할수록 효율이 좋다. |
| 큰 리팩토링 전 설계 검토 | Claude Opus 4.7 / Claude Code | 코드 구조를 비판적으로 보고, 놓친 전제나 위험을 짚는 데 강하다. |
| PR diff 리뷰 | Claude Opus 4.7 / Claude Code | "이 변경이 맞나?"를 따지는 reviewer 역할에 잘 맞는다. |
| 긴 컨텍스트 문서 정리와 대량 파일 읽기 | GPT-5.5 또는 Opus 4.7 | 둘 다 가능하다. 비용, 속도, 접근성을 보고 고르면 된다. |
| UI/UX 방향, 문서/슬라이드/기획안 | Claude Opus 4.7 | Opus 쪽이 디자인 의도, 정보 구조, 톤 비평을 잘하는 편이다. |
| 이미지 생성 | OpenAI 쪽 이미지 모델 | Claude Opus는 이미지를 잘 "이해"하지만, 이미지 생성 모델은 아니다. 실제 생성은 OpenAI 이미지 계열이나 전용 이미지 모델이 낫다. |
| Slack에서 시키고 PR까지 마무리 | Hermes | 모델 문제가 아니라 orchestration 문제다. |

즉 "Hermes에서 Codex로 코딩하고 Claude로 리뷰하는 게 가장 좋냐"에 대한 답은 **대체로 좋은 기본값이지만 항상 최선은 아니다**에 가깝다.

좋은 기본값인 이유는 간단하다. 구현자와 리뷰어를 분리하면 한 모델이 만든 실수를 다른 모델이 다른 관점에서 볼 가능성이 생긴다. Codex/GPT-5.5가 빠르게 수정하고, Claude Opus 4.7이 설계·리뷰·엣지 케이스를 보는 조합은 실전에서 꽤 안정적이다.

다만 다음 경우에는 바꾸는 게 낫다.

- 요구사항이 애매하고 설계가 더 중요하면: 먼저 Opus 4.7로 계획/리뷰를 받고, 구현을 GPT-5.5/Codex에 맡긴다.
- 단순 반복 수정이면: Claude 리뷰까지 돌리지 않고 GPT-5.5/Codex + 테스트로 끝낸다.
- UI/UX 설계나 글/문서 톤이 중요하면: Opus 4.7을 앞단에 둔다.
- 이미지 생성이 포함되면: Hermes에서 OpenAI 이미지 도구나 별도 이미지 생성 backend를 호출하고, Opus는 프롬프트/시안 비평에 쓴다.

---

## 추천 조합: Hermes는 관리자, Codex는 구현자, Claude는 리뷰어

내가 추천하는 기본 운영 방식은 다음과 같다.

```text
사용자(Slack/CLI)
  ↓
Hermes Agent (GPT-5.5 또는 Codex provider)
  ├─ 레포/요구사항 파악
  ├─ 작업 계획 수립
  ├─ Codex/GPT-5.5로 구현
  ├─ Claude Opus 4.7/Claude Code로 리뷰·설계 검토
  ├─ 테스트/빌드 직접 실행
  └─ Git commit / push / PR 생성
```

중요한 점은 Hermes가 "또 하나의 코딩 모델"이 아니라는 것이다. Hermes가 Codex provider로 떠 있으면 답변을 만드는 두뇌는 GPT-5.5/Codex지만, 기억·도구·메신저·스케줄러·PR 흐름은 Hermes가 잡고 있다.

### 1단계. Hermes가 요구사항을 정리한다

사용자는 Slack에서 자연어로 요청한다.

```text
이 이슈 보고 수정해서 PR 올려줘. 리뷰는 Claude Code로 한 번 돌려줘.
```

Hermes는 먼저 레포 상태를 확인한다.

```bash
git status --short --branch
git fetch origin
git checkout -b fix/some-issue
```

그리고 필요한 문서를 읽고 작업 범위를 좁힌다.

### 2단계. GPT-5.5/Codex가 구현한다

구현 범위가 명확하면 Codex 계열 모델에게 맡긴다. Hermes의 메인 모델이 GPT-5.5라면 Hermes가 직접 파일을 수정해도 되고, 별도 Codex CLI를 호출해도 된다.

```bash
codex exec --full-auto "Implement the fix described in ISSUE.md. Run tests and commit when done."
```

단, Codex 결과를 그대로 믿으면 안 된다. Hermes가 `git diff`, 테스트 결과, 변경 파일을 다시 확인해야 한다.

### 3단계. Claude Opus 4.7이 리뷰한다

구현 후에는 Claude Code에 diff 리뷰를 맡긴다.

```bash
git diff origin/main...HEAD | claude -p \
  "Review this diff for correctness, edge cases, security issues, and missing tests. Return actionable findings." \
  --max-turns 1
```

Claude는 구현 자체보다 "이 변경이 안전한가?", "설계가 어색하지 않은가?", "테스트가 빠지지 않았나?"를 보는 reviewer로 두면 좋다.

### 4단계. Hermes가 최종 검증하고 PR을 만든다

마지막은 Hermes가 직접 처리한다.

```bash
bun run build
git status --short
git add <changed-files>
git commit -m "docs: add Hermes Agent use cases"
git push -u origin HEAD
gh pr create --title "docs: add Hermes Agent use cases" --body "..."
```

여기서 중요한 원칙은 **최종 책임자는 Hermes**라는 점이다. Codex나 Claude Code가 "완료"라고 말해도, Hermes가 실제 파일과 테스트 결과, Git 상태를 확인한 뒤 PR을 올려야 한다.

---

## Hermes에 사람들이 많이 붙이는 것들

정확한 사용량 telemetry가 공개되어 있지는 않다. 다만 공식 문서, OpenRouter 연동 문서, 설치 가이드류에서 반복적으로 등장하는 조합은 꽤 뚜렷하다.

| 연결 대상 | 많이 쓰는 이유 |
|---|---|
| Slack / Telegram / Discord | 노트북을 열지 않아도 작업을 시킬 수 있다. 개인 자동화는 Telegram, 팀 작업은 Slack/Discord가 자연스럽다. |
| OpenRouter | 여러 모델을 한 API key로 바꾸기 쉽다. Claude, OpenAI, Gemini, DeepSeek 등을 Hermes에서 라우팅하기 좋다. |
| Anthropic / OpenAI provider | 고성능 코딩·리뷰 모델을 직접 붙이는 기본 조합이다. |
| MCP 서버 | GitHub, DB, 파일 시스템, 브라우저, 내부 API 같은 외부 도구를 Hermes tool로 노출할 수 있다. |
| Web search / Firecrawl / Tavily / Exa | 리서치, 블로그 초안, 문서 조사에 필요하다. |
| Browser automation | 로그인된 웹앱 확인, UI QA, 폼 입력, 시각 검증에 쓴다. |
| Cron / webhook | 매일 요약, PR 상태 확인, RSS 감시, 서버 점검 같은 unattended 작업에 쓴다. |
| Open WebUI / LobeChat / LibreChat | Hermes를 OpenAI-compatible API처럼 열어 다른 chat frontend에서 쓰는 패턴이다. |
| Voice / TTS | Telegram 같은 메신저에서 음성 메모를 받아 요약하거나 답변하는 용도다. |
| Home Assistant / 스마트홈 | 개인 서버에 상주시켜 집안 자동화까지 연결하는 사례가 있다. |

내가 보기엔 Hermes의 강점은 "어떤 모델이 제일 똑똑한가"보다 "어디에 붙여두면 귀찮은 일을 실제로 끝내는가"에서 나온다. 그래서 많이 쓰는 연결도 모델 하나가 아니라 메신저, OpenRouter, MCP, cron 쪽으로 몰린다.

---

## 자동 티키타카: 사람은 decision gate에 집중하기

Claude, Codex, 다른 모델을 "티키타카"하게 만드는 핵심은 모델을 많이 부르는 것이 아니라 **역할과 승인 지점을 분리하는 것**이다. Atlassian HULA 사례처럼 좋은 human-in-the-loop 구조는 agent가 Jira/GitHub issue를 읽고 plan, code, PR까지 만들지만, 사람은 plan 승인과 중요한 trade-off 결정에 남는다. GitHub Agentic Workflows도 같은 방향이다. agent는 GitHub Actions 안에서 실행되고, repo owner가 permissions, logs, review boundary를 정한다.

내가 보기에 Hermes 기반으로 최적화하려면 다음 6단계가 좋다.

| 단계 | agent가 하는 일 | 사람이 하는 일 | 추천 모델/도구 |
|---|---|---|---|
| 1. Repository scan | README, AGENTS.md, package, test, 기존 ADR/issue를 읽고 repo map 작성 | 목표와 제약만 제공 | Hermes + GPT-5.5 |
| 2. Research brief | 관련 문서, 경쟁안, 기존 구현 사례 조사 | 빠진 맥락 지적 | Hermes web + GPT-5.5 |
| 3. Decision brief | 대안 A/B/C, 비용, 위험, 되돌리기 난이도, 추천안 작성 | **선택/보류/수정 결정** | Claude Opus 4.7 리뷰 |
| 4. ADR + issue 생성 | accepted/proposed ADR, task issue, acceptance criteria 작성 | ADR의 decision outcome 승인 | Hermes + GitHub CLI |
| 5. Implementation PR | Codex/GPT-5.5가 구현, 테스트, PR 작성 | 큰 방향 변경만 승인 | Codex/GPT-5.5 |
| 6. Review loop | Claude가 PR 리뷰, Codex가 수정, Hermes가 CI/댓글 반영 | merge 여부 결정 | Claude + Codex + Hermes |

여기서 중요한 건 자동화율을 100%로 올리는 게 아니다. **low-risk loop는 자동화하고, irreversible decision은 사람에게 올리는 것**이 성능 대비 비용이 좋다.

### Decision gate 기준

사람에게 물어봐야 하는 경우를 명확히 정해두면 agent가 쓸데없이 멈추지도 않고, 위험한 결정을 혼자 하지도 않는다.

| 사람 승인 필요 | 자동 진행 가능 |
|---|---|
| public API 변경 | 내부 구현 정리 |
| DB schema / migration | 테스트 추가 |
| 인증/권한/비용/보안 영향 | 문서 보강 |
| 되돌리기 어려운 아키텍처 결정 | lint, format, 작은 버그 수정 |
| 제품 방향/UX trade-off | PR 설명, changelog 초안 |
| ADR status를 accepted로 바꾸는 순간 | proposed ADR 초안 작성 |

즉 사람은 "어떤 안을 택할지"만 결정하고, agent는 그 결정을 실행 가능한 문서와 PR로 바꾼다.

### PR comment는 트리거일 뿐, 지식 저장소는 아니다

PR이나 issue comment는 좋은 communication 수단이다. 하지만 모든 레포에서 생긴 decision과 insight를 장기 자산으로 쌓고 싶다면, PR comment를 지식의 source of truth로 두면 안 된다. 댓글은 맥락이 흩어지고, 레포마다 포맷이 다르고, merge 이후에는 다시 찾기 어렵다.

더 나은 구조는 **중앙 knowledge inbox**를 두는 것이다.

| 단계 | 역할 | 저장 위치 |
|---|---|---|
| 1. Signal capture | PR, issue, commit, Slack, 회의 메모, 로컬 작업 로그에서 후보 이벤트 수집 | 각 레포 / Slack / Hermes session |
| 2. Asset triage | "다시 쓸 지식인가?", "decision인가?", "단순 작업 로그인가?" 분류 | 중앙 inbox |
| 3. Decision record | 되돌리기 어렵거나 팀 합의가 필요한 선택은 ADR로 기록 | 중앙 wiki 또는 각 레포 `docs/adr/` |
| 4. Wiki synthesis | 여러 이벤트에서 반복되는 패턴과 현재 결론을 정제 | 중앙 wiki |
| 5. Backlink | 원래 PR/issue/commit/Slack thread로 근거 연결 | wiki footnote / source list |

이렇게 하면 PR comment는 여러 입력 중 하나가 된다. 중요한 건 comment 자체가 아니라, comment에서 나온 결정과 이유가 **ADR 또는 wiki로 승격되는 기준**이다.

이 레포에는 우선 작은 검증 트리거만 붙였다. PR에서 `content/wiki/**`, `content/**/*.md`, `scripts/verify-wiki.py`, `.github/workflows/wiki-verify.yml`이 바뀌면 GitHub Actions가 `scripts/verify-wiki.py`를 실행한다. 이 검사는 wiki frontmatter, wikilink 해석, index 누락, 비공개 레포명/조직명 같은 금지어 노출을 막는다. 아직 "모든 레포 → 중앙 inbox → 자산 선별 → wiki PR" 자동화까지는 아니다. 그건 이 블로그 레포 안의 PR comment workflow가 아니라, Hermes cron/webhook이 여러 레포를 읽고 중앙 wiki에 PR을 여는 별도 파이프라인으로 가는 편이 맞다.

### 프로젝트 → 팀 → 조직으로 통합하기

지식 운영의 단위는 도구가 아니라 **scope**여야 한다. GitHub Issue/PR, Linear, Jira, Slack, Notion은 모두 surface일 뿐이고, 장기적으로 남길 단위는 `Project`, `Team`, `Organization`, `Decision`, `Requirement`, `Artifact`, `Source` 같은 중립 엔티티다.

| Scope | 무엇을 남기나 | 저장 위치 | 자동화 기본값 |
|---|---|---|---|
| 개인 | 작업 중 메모, AI 대화 요약, 임시 판단 | 개인 vault / Hermes memory / session log | 저장은 느슨하게, 공유 전 정제 |
| 프로젝트 | 요구사항, ADR, runbook, 코드 경로와 연결된 운영 맥락 | repo `docs/`, project wiki, Linear/Jira project | PR/티켓 종료 시 후보 추출 |
| 팀 | 여러 프로젝트에서 반복되는 workflow, 표준, reusable playbook | team wiki / shared vault | 주간 digest + human triage |
| 조직 | cross-project policy, 보안·권한 기준, 고객별 공통 맥락 | org knowledge hub | 승인된 요약과 링크만 통합 |

프로젝트 문서는 코드와 가까워야 덜 썩고, 조직 위키는 모든 세부사항을 복붙하지 말고 **요약·링크·정책·공통 패턴**만 가져가야 한다. 즉 source of truth는 프로젝트 가까이에 두고, 조직 단위는 compiled view로 운영한다.

일상 대화에서 트리거는 세 단계가 적당하다.

1. **명시적 트리거**: `@Hermes 이거 decision으로 남겨줘`, `이 스레드 요구사항으로 정리해줘`처럼 사람이 호출한다.
2. **후보 제안**: "이 방향으로 가자", "고객 요구사항 변경", "다음부터 이렇게 하자" 같은 표현을 감지하면 agent가 저장 후보를 제안한다. 바로 저장하지 않는다.
3. **주기적 수확**: 매주 Slack thread, 회의록, 닫힌 issue/Linear ticket, merged PR, AI worklog에서 decision/requirement 후보를 모아 triage PR을 만든다.

이렇게 하면 GitHub 중심으로 과적합하지 않는다. GitHub PR은 좋은 실행 로그지만, Linear ticket도 같은 `Task` 엔티티의 provider가 될 수 있고, 회의록이나 고객 문서도 같은 `Source` 엔티티로 들어온다.

### 검색하기 좋은 지식으로 남기는 법

통합된 지식은 "문서가 어딘가에 있다"만으로는 부족하다. 나중에 사람과 agent가 찾기 쉬우려면 **문서 자체가 검색 인덱스처럼 작성**되어야 한다.

최소 frontmatter는 이렇게 잡는 편이 좋다.

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

### 권한 관리는 검색보다 먼저 설계해야 한다

조직 지식베이스에서 가장 위험한 실패는 "검색이 안 됨"보다 **보면 안 되는 문서가 검색됨**이다. 특히 고객 문서, 계약 조건, 보안 이슈, 인사 관련 결정, 비공개 레포명은 요약본에 섞여 나오기 쉽다.

기본 원칙은 다섯 가지다.

1. **source ACL을 보존한다**: Slack private channel, 고객 폴더, repo 권한, Notion page 권한을 ingest 시점에 metadata로 복사한다.
2. **권한 없는 문서는 retrieval 전에 제외한다**: LLM에게 보여준 뒤 "말하지 마"가 아니라, 검색 결과에서 애초에 빼야 한다.
3. **요약본은 원본보다 더 공개적이면 안 된다**: confidential 고객 문서를 요약한 wiki page도 최소 confidential이다.
4. **공개 블로그와 내부 위키를 분리한다**: 이 블로그처럼 공개 `content/`와 내부 `.wiki-cache/`, inbox, ledger를 분리해야 한다.
5. **승격에는 review gate를 둔다**: private source에서 public artifact로 나가는 순간은 자동화하지 말고 사람이 승인한다.

| 데이터 종류 | 권한 기본값 | 공개 가능성 |
|---|---|---|
| 공개 문서, 공개 GitHub 이슈 | public | 바로 인용 가능 |
| 사내 회의록, 내부 PR | internal | 요약만 내부 공유 |
| 고객 문서, 계약·가격·보안 논의 | confidential | 고객명/수치 제거 후 별도 승인 |
| 개인 메모, DM, 인사 관련 대화 | restricted | 원칙적으로 조직 위키 승격 금지 |

따라서 agent pipeline도 `collect → classify sensitivity → redact → draft → review → publish` 순서가 되어야 한다. 검색 아키텍처보다 권한 아키텍처가 앞선다.

### Second Brain 개념은 도움이 되지만 그대로 쓰면 부족하다

Second Brain/PARA는 이 문제를 설명하는 데 꽤 도움이 된다. Tiago Forte의 PARA는 정보를 `Projects`, `Areas`, `Resources`, `Archives`로 나누고, 주제보다 **actionability** 중심으로 정리하라고 말한다. 조직 지식에도 이 원칙은 유효하다.

- `Projects`: 진행 중인 제품/고객/기능 단위 지식
- `Areas`: 보안, 데이터, 플랫폼, 채용처럼 계속 유지되는 책임 영역
- `Resources`: 기술 조사, 경쟁사 분석, reusable pattern
- `Archives`: 종료 프로젝트, superseded ADR, 과거 고객 맥락

하지만 개인용 Second Brain을 조직에 그대로 복사하면 세 가지가 빠진다.

1. **권한**: 개인 노트는 내가 다 볼 수 있지만, 조직 지식은 사람마다 볼 수 있는 범위가 다르다.
2. **책임자**: 개인 지식은 owner가 하나지만, 조직 지식은 page owner와 review cycle이 필요하다.
3. **승격 기준**: 개인 메모가 곧 지식이 될 수 있지만, 조직에서는 raw 대화가 곧 canonical knowledge가 되면 안 된다.

그래서 조직형 Second Brain은 PARA 위에 `permission`, `owner`, `source`, `review_after`, `status`를 더한 형태가 되어야 한다. 개인의 second brain은 **capture와 연결**을 돕고, 조직의 second brain은 **검색·권한·감사 가능성**까지 책임져야 한다.

### 구요한님의 CMDS / CommandSpace에서 참고할 만한 점

구요한님의 [cmds-vault](https://github.com/prodbartist/cmds-vault)는 이 주제에 꽤 직접적인 참고 사례다. CMDS는 Obsidian 기반 PKM 시스템이고, `Connect → Merge → Develop → Share`라는 지식 생애주기를 명확히 둔다. starter vault에는 `WELCOME.md`, `CMDS.md`, `CLAUDE.md`, `AGENTS.md`, `🏛 CMDS Guide`, `🏛 CMDS Head Quarter` 같은 시스템 파일이 있고, Claude/Codex 같은 agent가 어떤 순서로 무엇을 읽어야 하는지도 precedence로 정해둔다.

내가 참고하고 싶은 포인트는 네 가지다.

1. **프로세스 이름이 있다**: capture를 그냥 "정리"라고 부르지 않고 Connect, Merge, Develop, Share로 나눈다. 조직 지식도 `Capture → Triage → Synthesize → Publish`처럼 명령어화하는 게 좋다.
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

즉 Second Brain은 철학을 주고, CMDS는 프로세스 언어를 주고, LLM Wiki는 agent가 유지할 수 있는 Markdown 구현 방식을 준다. Hermes는 이 셋을 실제 작업 표면(Slack, GitHub, Linear, 로컬 레포, cron)과 연결하는 orchestration layer가 된다.

### Wiki로 들어가야 지식이 된다

프로젝트가 굴러가며 생긴 decision은 PR 안에만 있으면 금방 사라진다. 진짜 지식으로 남기려면 세 층으로 저장하는 게 좋다.

| 레이어 | 역할 | 저장 예시 |
|---|---|---|
| Issue / PR | 작업의 실행 기록 | "이 버그를 고쳤다", 리뷰 댓글, CI 결과 |
| ADR | 결정의 append-only 기록 | "왜 이 아키텍처를 선택했나", 대안과 trade-off |
| Wiki | 현재 팀 지식의 정제본 | "현재 우리 시스템은 이렇게 동작한다", 관련 ADR 링크 |

ADR은 Microsoft ADR 가이드처럼 append-only로 두고, 결정이 바뀌면 기존 ADR을 수정하지 말고 새 ADR이 supersede하게 둔다. Wiki는 반대로 최신 상태를 반영하는 mutable 문서다. 그래서 **ADR은 왜를 보존하고, wiki는 지금 무엇인지를 설명한다**고 나누면 된다.

팀 decision을 wiki에 넣을 때도 단순 결론만 쓰면 지식이 아니다. 최소한 다음을 포함해야 한다.

```markdown
## Decision summary
무엇을 결정했는가

## Context
어떤 문제, 제약, 요구사항 때문에 결정이 필요했는가

## Options considered
검토한 대안과 버린 이유

## Decision drivers
성능, 비용, 보안, 운영, 개발 속도 중 무엇을 우선했는가

## Consequences
좋아지는 점, 나빠지는 점, 나중에 다시 볼 조건

## Links
관련 ADR, issue, PR, 코드 경로
```

이 구조가 있어야 나중에 agent가 wiki를 읽고 "그때 왜 그렇게 했는지"까지 이해한다. 그냥 최신 결론만 있으면 다음 agent가 같은 논쟁을 반복한다.

---
## 작업 유형별 분업표

| 작업 유형 | Hermes | Codex | Claude Code |
|---|---|---|---|
| 요구사항 정리 | ◎ | △ | ○ |
| 빠른 코드 수정 | ○ | ◎ | △ |
| 대규모 리팩토링 | ○ | △ | ◎ |
| PR 생성/CI 확인 | ◎ | △ | △ |
| 코드 리뷰 | ○ | △ | ◎ |
| 반복 업무 자동화 | ◎ | △ | △ |
| Slack/Telegram 작업 | ◎ | × | × |
| 프로젝트 규칙 기억 | ◎(memory/skill) | ○ | ◎(CLAUDE.md) |
| 병렬 issue 처리 | ◎(orchestration) | ◎(worktree) | ○(worktree/tmux) |

기호는 개인적인 추천이다. `◎`는 주 담당, `○`는 보조, `△`는 상황에 따라 가능, `×`는 직접 담당하기 어렵다는 뜻이다.

---

## 실전 프롬프트 예시

### Hermes에게 전체 작업 요청

```text
이 레포에서 로그인 실패 버그를 조사해줘.
1. 새 브랜치를 만들고
2. Codex로 수정안을 구현한 뒤
3. Claude Code로 diff 리뷰를 받고
4. 테스트 통과하면 PR을 올려줘.
리뷰에서 지적된 내용은 반영하고, 최종 요약도 남겨줘.
```

### Codex에게 구현만 맡기기

```text
Implement the minimal fix for the login redirect bug.
Do not change unrelated files.
Run the relevant tests.
Leave a concise commit message suggestion.
```

### Claude Code에게 리뷰만 맡기기

```text
Review this diff as a senior engineer.
Focus on correctness, missing tests, security, and maintainability.
Do not rewrite the code unless necessary.
Return findings in priority order.
```

### Hermes가 Claude/Codex 결과를 검증할 때

```text
Compare Codex's changes with Claude Code's review findings.
Apply only high-confidence fixes.
Run the project's build/test command.
If anything is uncertain, report it instead of guessing.
```

---

## 주의할 점

### 1. 하위 에이전트의 말을 그대로 믿지 않기

Codex나 Claude Code가 "테스트 통과"라고 말해도 실제로는 실패했거나, 다른 디렉터리에서 실행했을 수 있다. Hermes가 직접 테스트 명령과 `git diff`를 확인해야 한다.

### 2. 권한을 과하게 열지 않기

Claude Code에는 `--dangerously-skip-permissions`, Codex에는 `--yolo` 같은 강력한 옵션이 있다. 빠르지만 위험하다. 개인 실험 레포가 아니라면 최소 권한 원칙을 지키는 편이 좋다.

### 3. 역할을 섞지 않기

한 에이전트에게 구현, 리뷰, PR 생성, 배포까지 모두 맡기면 검증 지점이 사라진다. 구현은 Codex, 리뷰는 Claude Code, 최종 검증과 PR은 Hermes처럼 역할을 나누면 품질 관리가 쉬워진다.

### 4. 프로젝트 컨텍스트 파일을 관리하기

Hermes는 `AGENTS.md`, `CLAUDE.md`, `.cursorrules` 같은 프로젝트 컨텍스트 파일을 읽을 수 있다. Claude Code는 `CLAUDE.md`와 `.claude/settings.json`을 활용한다. Codex도 레포의 작업 가이드를 참고할 수 있다.

따라서 프로젝트 루트에는 다음 정보를 명확히 적어두는 것이 좋다.

- 수정 가능한 디렉터리와 금지된 디렉터리
- 테스트/빌드 명령
- 커밋 메시지 규칙
- 배포 주의사항
- 비밀키/환경파일 접근 금지 규칙

---

## 결론

Hermes Agent의 강점은 단순히 "답변을 잘하는 모델"이 아니라, **여러 도구와 모델을 하나의 작업 흐름으로 묶는 능력**에 있다.

Hermes를 GPT-5.5/Codex provider로 쓴다고 해서 Codex CLI 단독 사용과 같아지는 것은 아니다. 추론 엔진은 같거나 비슷할 수 있지만, Hermes에는 Slack 입구, 장기 기억, 스킬, cron, MCP, GitHub PR 흐름이 붙는다. 이 차이가 실사용에서는 꽤 크다.

내 기본값은 이렇다.

- Hermes 메인 모델: **GPT-5.5 또는 Codex provider**
- 빠른 구현: **Hermes 내부 도구 실행 또는 Codex CLI**
- 설계/리뷰: **Claude Opus 4.7 / Claude Code**
- 이미지 생성: **OpenAI 이미지 계열 또는 전용 이미지 모델**
- 최종 검증/PR 관리: **Hermes Agent**

다만 이건 고정 공식이 아니다. 단순 구현은 GPT-5.5/Codex만으로 충분하고, 설계가 어려운 작업은 Opus 4.7을 먼저 쓰는 편이 낫다. 이미지 생성은 Claude가 아니라 OpenAI 쪽이나 전용 이미지 모델을 붙이는 게 자연스럽다.

AI 에이전트를 잘 쓰는 핵심은 "하나의 만능 모델"을 찾는 것이 아니라, **작업의 성격에 맞춰 모델과 도구를 나누고 검증 루프를 만드는 것**이다. Hermes Agent는 그 오케스트레이션 레이어로 꽤 좋은 위치에 있다.

---

## 참고 자료

- [Hermes Agent Documentation](https://hermes-agent.nousresearch.com/docs/)
- [Hermes Agent - Integrations](https://hermes-agent.nousresearch.com/docs/integrations/)
- [Hermes Agent - AI Providers](https://hermes-agent.nousresearch.com/docs/integrations/providers/)
- [Hermes Agent - Messaging Gateway](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/)
- [Hermes Agent - Persistent Memory](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory/)
- [Hermes Agent - Skills System](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills/)
- [Hermes Agent - Scheduled Tasks](https://hermes-agent.nousresearch.com/docs/user-guide/features/cron/)
- [Hermes Agent - MCP](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp/)
- [OpenRouter - Hermes Agent Integration](https://openrouter.ai/docs/cookbook/coding-agents/hermes-integration)
- [Anthropic - Introducing Claude Opus 4.7](https://www.anthropic.com/news/claude-opus-4-7)
- [OpenRouter - GPT-5.5 model page](https://openrouter.ai/openai/gpt-5.5/benchmarks)
- [Atlassian - Human in the Loop Software Development Agents](https://www.atlassian.com/blog/atlassian-engineering/hula-blog-autodev-paper-human-in-the-loop-software-development-agents)
- [GitHub Blog - Automate repository tasks with GitHub Agentic Workflows](https://github.blog/ai-and-ml/automate-repository-tasks-with-github-agentic-workflows/)
- [MSR 2026 - How AI Coding Agents Communicate](https://arxiv.org/html/2602.17084)
- [AWS Architecture Blog - ADR best practices](https://aws.amazon.com/blogs/architecture/master-architecture-decision-records-adrs-best-practices-for-effective-decision-making/)
- [Microsoft - Maintain an architecture decision record](https://learn.microsoft.com/en-us/azure/well-architected/architect-role/architecture-decision-record)
- [Architectural Decision Records](https://adr.github.io/)
- [Claude Code GitHub Actions](https://code.claude.com/docs/en/github-actions)
- [OpenAI Cookbook - Build Code Review with the Codex SDK](https://developers.openai.com/cookbook/examples/codex/build_code_review_with_codex_sdk)
- [Karpathy - LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
- [구요한 / Yohan Koo - CMDS Vault](https://github.com/prodbartist/cmds-vault)
- [cmds-vault - cmds-llm-wiki skill](https://github.com/prodbartist/cmds-vault/blob/main/90.%20Settings/91.%20Skills/cmds-llm-wiki/SKILL.md)
- [Forte Labs - PARA Method](https://fortelabs.com/blog/para/)
- [Azure AI Search - Document-Level Access Control](https://learn.microsoft.com/en-us/azure/search/search-document-level-access-overview)
- [Dataquest - Metadata Filtering and Hybrid Search](https://www.dataquest.io/blog/metadata-filtering-and-hybrid-search-for-vector-databases/)
- [OpenAI Codex GitHub Repository](https://github.com/openai/codex)
- [Claude Code Overview](https://docs.anthropic.com/en/docs/claude-code/overview)
- [Claude Code CLI Reference](https://docs.anthropic.com/en/docs/claude-code/cli-reference)
- [Claude Code Settings](https://docs.anthropic.com/en/docs/claude-code/settings)
