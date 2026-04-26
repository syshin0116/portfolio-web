---
title: "Cursor Project Rules"
type: tool
tags:
  - cursor
  - ai
  - coding-assistant
  - project-rules
  - configuration
  - ai-agent
  - pattern
summary: "Cursor의 Project Rules 시스템은 .cursor/rules/ 디렉터리에 YAML+Markdown 파일로 파일 패턴별 AI 동작 규칙을 정의한다. 구버전 .cursorrules 파일보다 유연하고 버전 관리가 가능하며, 팀 코딩 컨벤션 표준화에 효과적이다."
sources:
  - content/Tools/Cursor-Project-Rules.md
created: 2026-04-26
updated: 2026-04-26
author: wiki-curator
draft: false
---

## Key Claims

- Cursor Rules for AI는 두 가지 방식으로 구현된다: Project Rules(`.cursor/rules/` 디렉터리)와 Global Rules(Cursor 설정 → General → Rules for AI).[^1]
- Project Rules는 glob 패턴으로 적용 대상 파일을 지정하고, 매칭 파일 참조 시 자동 첨부된다. 일반 파일이므로 Git 버전 관리 가능.[^1]
- Project Rules의 주요 속성: 의미론적 설명, 파일 패턴 매칭, 자동 첨부, `@file` 파일 참조, 여러 규칙 연결.[^1]
- 새 규칙 생성: `Cmd+Shift+P` → "New Cursor Rule" 명령.[^1]
- Global Rules는 출력 언어, 응답 길이처럼 모든 프로젝트에 항상 적용할 규칙에 사용한다.[^1]
- 구버전 `.cursorrules` 파일은 제거 예정(deprecated)이며 Project Rules로 마이그레이션을 권장한다.[^1]
- 커뮤니티 리소스: [awesome-cursorrules](https://github.com/PatrickJS/awesome-cursorrules)에 React, Next.js, FastAPI, TypeScript 등 다양한 스택별 규칙 모음이 있다.[^1]

## Examples / Code

React 컴포넌트 규칙 예시:

```
// .cursor/rules/react-components.md
다음 파일 패턴에 적용: *.tsx, *.jsx

React 컴포넌트를 작성할 때 다음 규칙을 따른다:
1. 함수형 컴포넌트만 사용한다
2. React.memo()를 활용하여 성능을 최적화한다
3. 모든 props는 명시적 타입을 가져야 한다
4. hooks는 컴포넌트 상단에 배치한다
```

자동 생성 파일 처리:

```
// .cursor/rules/proto-files.md
다음 파일 패턴에 적용: *.proto

protobuf 파일은 자동 생성되므로 직접 수정하지 말고,
원본 스키마를 수정한 후 재생성해야 한다.
```

## Connections

- [[vibe-coding]] — Project Rules는 vibe coding 워크플로우에서 AI 출력 품질을 높이는 보완 도구

## Footnotes

[^1]: content/Tools/Cursor-Project-Rules.md
