---
title: "Vibe Coding"
type: concept
tags:
  - ai
  - coding-assistant
  - cursor
  - productivity
  - llm
  - vibe-coding
  - agent
  - pattern
summary: "Vibe coding은 Andrej Karpathy가 명명한 개발 철학으로, LLM과 AI 에디터에 코드 생성을 완전히 위임하고 개발자는 의도와 방향에 집중하는 방식이다. Cursor + Composer 조합이 대표적 구현 도구이며, 프로토타입과 주말 프로젝트에 효과적이나 프로덕션 코드에서는 코드 이해 부재가 위험 요소다."
sources:
  - content/Tools/바이브코딩과 커서(Cursor).md
created: 2026-04-26
updated: 2026-04-26
author: wiki-curator
draft: false
---

## Key Claims

- Vibe coding은 전 Tesla AI 디렉터이자 OpenAI 설립 멤버인 Andrej Karpathy가 2025년 처음 사용한 용어다. "코딩에 별로 공수를 들이지 않고 LLM에게 다 시켜서 바이브대로 간다"는 의미.[^1]
- Karpathy의 원문 정의: "fully give in to the vibes, embrace exponentials, and forget that the code even exists." diff를 읽지 않고, 오류 메시지를 복붙해 넣고, AI가 고칠 때까지 랜덤 변경을 요청하는 방식.[^1]
- 이 접근이 가능해진 이유는 Cursor Composer + Claude Sonnet 조합 등 LLM 코딩 능력이 급격히 향상됐기 때문이다.[^1]
- Cursor는 VS Code 기반 AI 코딩 에디터다. Tab(인라인 자동완성), Chat(맥락 기반 Q&A), Composer(멀티 파일 편집)의 세 레이어로 구성된다.[^1]
- Upstage 사례: 많은 개발자가 Cursor를 활용해 생산성을 높이고 있다고 보고된다.[^1]
- 소규모 프로토타입·주말 프로젝트에 적합하지만, 코드가 개발자 이해 범위를 벗어나므로 프로덕션 적용에는 주의가 필요하다.[^1]

## Examples / Code

Karpathy 원문 인용:

```
"I ask for the dumbest things like 'decrease the padding on the sidebar by half' because I'm too lazy to find it.
I 'Accept All' always, I don't read the diffs anymore.
When I get error messages I just copy paste them in with no comment, usually that fixes it."
```

Cursor Composer 활용 패턴:
- SuperWhisper 등 음성 입력 → Composer로 자연어 명령
- "Accept All" 워크플로우로 코드 변경 수락
- 에러 복붙 → 자동 수정 루프

## Connections

- [[cursor-project-rules]] — Cursor Project Rules로 AI 동작을 프로젝트별로 맞춤화하는 보완적 기법

## Footnotes

[^1]: content/Tools/바이브코딩과 커서(Cursor).md
