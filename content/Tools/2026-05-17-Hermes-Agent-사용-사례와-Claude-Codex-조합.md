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
description: Slack에서 바로 PR을 올리는 Hermes Agent의 사용 사례를 정리하고, Codex를 메인 모델로 쓰면서 Claude Code와 함께 운용하는 실전 조합법을 살펴본다.
summary: "Hermes Agent는 터미널·Slack·Telegram 등 어디서나 도구를 실행하는 자율 에이전트다. 메모리, 스킬, 크론, MCP, 메시징 게이트웨이를 중심으로 사용 사례를 정리하고, OAuth 문제로 Claude Code를 메인으로 쓰기 어려울 때 Codex 기반 Hermes와 Claude Code를 분업시키는 방법을 정리했다."
published: 2026-05-17
modified: 2026-05-17
---

## 들어가며

요즘 AI 코딩 도구를 쓰다 보면 선택지가 너무 많다. Cursor, Claude Code, Codex, Gemini CLI, Devin류 서비스까지 각자 장점이 다르다. 그런데 실제 업무에서는 "어떤 모델이 더 똑똑한가"보다 더 중요한 문제가 있다.

> 내가 쓰는 채팅창, 터미널, GitHub, 로컬 파일, 서버 작업을 하나의 흐름으로 묶을 수 있는가?

[Hermes Agent](https://hermes-agent.nousresearch.com/docs/)는 이 지점에 초점을 둔 오픈소스 AI 에이전트 프레임워크다. 단순한 챗봇이나 IDE 플러그인이 아니라, 터미널·메신저·스케줄러·MCP·파일 시스템·브라우저·GitHub 워크플로우를 연결해 "일을 끝내는" 쪽에 가깝다.

이 글에서는 Hermes Agent의 대표 사용 사례를 정리하고, 특히 **Hermes를 Codex 메인 모델로 사용하면서 Claude Code를 보조 에이전트로 함께 쓰는 방법**을 다룬다. Claude Code OAuth나 구독 환경 때문에 Hermes의 메인 모델로 Claude를 바로 쓰기 어렵다면, Codex를 메인으로 두고 Claude Code CLI를 필요할 때 호출하는 조합이 꽤 실용적이다.

---

## Hermes Agent 한 줄 요약

Hermes Agent는 Nous Research가 만든 **자기 개선형(self-improving) AI 에이전트**다. 공식 문서에서는 Hermes를 "경험으로부터 스킬을 만들고, 사용 중 스킬을 개선하며, 세션을 넘어 사용자를 이해하는 에이전트"로 설명한다.

핵심은 다음 네 가지다.

1. **어디서나 실행**: 로컬 터미널뿐 아니라 Slack, Telegram, Discord, WhatsApp, Email 등 메시징 플랫폼에서 호출 가능
2. **도구 실행**: 파일 편집, 터미널 명령, 웹 검색, 브라우저 자동화, 이미지/음성 도구, GitHub 작업 등을 도구로 수행
3. **지속 기억**: 사용자 선호, 프로젝트 구조, 반복되는 워크플로우를 메모리와 스킬로 보존
4. **모델 독립성**: OpenAI Codex, Anthropic, OpenRouter, Gemini, GitHub Copilot, 로컬 OpenAI 호환 엔드포인트 등 다양한 provider를 선택 가능

즉 Hermes는 "하나의 모델"이라기보다 **여러 모델과 도구를 엮는 작업 운영체제**에 가깝다.

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

## Codex를 Hermes 메인으로 쓰는 이유

Hermes의 provider 문서를 보면 OpenAI Codex는 `hermes model`에서 설정 가능한 provider 중 하나다. 즉 Hermes 자체의 메인 대화 모델을 Codex 계열로 둘 수 있다.

이 구성이 유용한 상황은 다음과 같다.

1. **Claude Code OAuth가 현재 환경에서 잘 안 되는 경우**
   - 회사 SSO, OAuth 리다이렉트, 브라우저 권한, 원격 서버 환경 때문에 Claude 로그인이 막힐 수 있다.
2. **ChatGPT/Codex 계정은 이미 잘 동작하는 경우**
   - Codex CLI는 `codex` 실행 후 ChatGPT 로그인으로 사용할 수 있고, Hermes도 OpenAI Codex provider를 선택할 수 있다.
3. **Hermes를 메신저/자동화 허브로 쓰고 싶은 경우**
   - Hermes의 Slack/Gateway, memory, cron, skill, PR workflow는 모델과 독립적으로 동작한다.

즉 "Claude를 못 쓰니 Hermes를 못 쓴다"가 아니라, **Hermes의 메인은 Codex로 두고 Claude Code는 별도 CLI 도구처럼 필요할 때 호출**하면 된다.

---

## Claude Code와 Codex의 강점 차이

둘 다 코딩 에이전트지만 실전에서 느껴지는 역할은 조금 다르다.

### Codex가 좋은 경우

[openai/codex](https://github.com/openai/codex)는 "터미널에서 실행되는 경량 코딩 에이전트"를 표방한다. 설치도 단순하다.

```bash
npm install -g @openai/codex
# 또는
brew install --cask codex
```

Codex는 다음 작업에 잘 맞는다.

- 작은 버그 수정
- 테스트 추가
- 파일 단위 리팩토링
- 명확한 TODO 처리
- 여러 worktree에 병렬로 issue 처리
- Hermes가 만든 계획을 빠르게 구현

Hermes에서 Codex를 호출한다면 보통 이런 식이다.

```bash
codex exec --full-auto "Fix the failing test and commit the change"
```

주의할 점은 Codex CLI가 보통 git repository 안에서 실행되어야 하며, Hermes 터미널 도구로 다룰 때는 interactive CLI 특성상 PTY가 필요할 수 있다는 점이다.

### Claude Code가 좋은 경우

[Claude Code](https://docs.anthropic.com/en/docs/claude-code/overview)는 코드베이스 전체를 이해하고 기능 구현, 버그 수정, Git 작업, MCP 연결, custom agents, hooks 등을 지원하는 코딩 어시스턴트다.

Claude Code는 다음 작업에 잘 맞는다.

- 큰 리팩토링 전 설계 검토
- PR diff 리뷰
- 보안/성능 관점 코드 리뷰
- 복잡한 코드 경로 추적
- 테스트 전략 수립
- `CLAUDE.md` 기반 프로젝트 컨텍스트 활용

특히 Claude Code는 `-p` print mode가 있어서 Hermes에서 자동화하기 좋다.

```bash
claude -p "Review the current diff for bugs and missing tests" --max-turns 5
```

`-p` 모드는 한 번 실행하고 종료되므로 Hermes가 결과를 받아 요약하기 쉽다. 반대로 긴 상호작용이 필요하면 `tmux` 세션으로 Claude Code를 띄워두고 capture-pane으로 진행 상황을 확인하는 방식이 안정적이다.

---

## 추천 조합: Hermes(Codex main) + Claude Code reviewer + Codex implementer

내가 추천하는 기본 운영 방식은 다음과 같다.

```text
사용자(Slack/CLI)
  ↓
Hermes Agent (Codex provider)
  ├─ 레포/요구사항 파악
  ├─ 작업 계획 수립
  ├─ Codex CLI에 구현 위임
  ├─ Claude Code에 리뷰/설계 검토 위임
  ├─ 테스트/빌드 직접 실행
  └─ Git commit / push / PR 생성
```

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

### 2단계. Codex가 구현한다

구현 범위가 명확하면 Codex에게 맡긴다.

```bash
codex exec --full-auto "Implement the fix described in ISSUE.md. Run tests and commit when done."
```

Codex는 빠르게 파일을 고치고 테스트를 돌리는 역할을 맡는다. 단, Codex 결과를 그대로 믿지 말고 Hermes가 `git diff`, 테스트 결과, 변경 파일을 다시 확인해야 한다.

### 3단계. Claude Code가 리뷰한다

구현 후에는 Claude Code에 diff 리뷰를 맡긴다.

```bash
git diff origin/main...HEAD | claude -p \
  "Review this diff for correctness, edge cases, security issues, and missing tests. Return actionable findings." \
  --max-turns 1
```

Claude Code는 구현 자체보다 "이 변경이 안전한가?"를 보는 reviewer 역할로 두면 좋다. OAuth 문제로 Claude Code를 항상 Hermes 메인 모델로 쓰지 못해도, CLI가 로그인된 환경에서는 필요한 순간에 reviewer로 활용할 수 있다.

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

## 작업 유형별 분업표

| 작업 유형 | Hermes | Codex | Claude Code |
|---|---|---|---|
| 요구사항 정리 | ◎ | △ | ○ |
| 빠른 코드 수정 | ○ | ◎ | ○ |
| 대규모 리팩토링 | ○ | ○ | ◎ |
| PR 생성/CI 확인 | ◎ | △ | △ |
| 코드 리뷰 | ○ | ○ | ◎ |
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

특히 Claude Code OAuth가 매끄럽지 않거나, Codex 계정이 더 안정적인 환경이라면 다음 구성이 현실적이다.

- Hermes 메인 모델: **Codex provider**
- 구현 보조: **Codex CLI**
- 리뷰/설계 보조: **Claude Code CLI**
- 자동화/메신저/PR 관리: **Hermes Agent**

이 조합을 쓰면 Slack에서 요청을 던지고, Hermes가 Codex와 Claude Code를 적절히 불러 작업을 나누고, 마지막에는 테스트와 PR까지 마무리하는 흐름을 만들 수 있다.

AI 에이전트를 잘 쓰는 핵심은 "하나의 만능 모델"을 찾는 것이 아니라, **각 도구의 강점을 분업시키고 검증 루프를 만드는 것**이다. Hermes Agent는 그 오케스트레이션 레이어로 꽤 좋은 위치에 있다.

---

## 참고 자료

- [Hermes Agent Documentation](https://hermes-agent.nousresearch.com/docs/)
- [Hermes Agent - AI Providers](https://hermes-agent.nousresearch.com/docs/integrations/providers/)
- [Hermes Agent - Messaging Gateway](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/)
- [Hermes Agent - Persistent Memory](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory/)
- [Hermes Agent - Skills System](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills/)
- [Hermes Agent - Scheduled Tasks](https://hermes-agent.nousresearch.com/docs/user-guide/features/cron/)
- [Hermes Agent - MCP](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp/)
- [OpenAI Codex GitHub Repository](https://github.com/openai/codex)
- [Claude Code Overview](https://docs.anthropic.com/en/docs/claude-code/overview)
- [Claude Code CLI Reference](https://docs.anthropic.com/en/docs/claude-code/cli-reference)
- [Claude Code Settings](https://docs.anthropic.com/en/docs/claude-code/settings)
