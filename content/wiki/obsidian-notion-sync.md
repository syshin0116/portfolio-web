---
title: "Obsidian ↔ Notion 동기화"
type: pattern
tags:
  - obsidian
  - notion
  - automation
  - pkm
  - markdown
  - workflow
  - productivity
summary: "Obsidian은 개인 지식 관리에, Notion은 협업에 각각 강점이 있다. 두 도구 모두 Markdown 기반이므로 'Share to Notion' 플러그인과 Notion API Integration을 사용해 Obsidian 노트를 Notion으로 자동 동기화할 수 있다."
sources:
  - content/Tools/2024-03-09-Obsidian to Notion 자동화.md
created: 2026-04-26
updated: 2026-04-26
author: wiki-curator
draft: false
---

## Key Claims

- Obsidian은 개인 사용에, Notion은 협업 목적에 강점을 가진다. 두 도구 모두 Markdown을 기반으로 하므로 상호 호환이 가능하다.[^1]
- 자동화 방법: Obsidian Community Plugin의 **Share to Notion** 플러그인 + Notion Integration API 조합.[^1]
- 설정 단계:
  1. Share to Notion 플러그인 설치 및 활성화
  2. [notion.so/my-integrations](https://notion.so/my-integrations)에서 새 Integration 생성
  3. Secret Key 복사
  4. 동기화할 Notion 페이지에 Integration 권한 부여[^1]
- 플러그인 설치 후 Community Plugin 설정에서 활성화하는 것을 잊지 않아야 한다.[^1]

## Examples / Code

Notion API Integration 설정 경로:
- 통합 생성: `https://www.notion.so/my-integrations`
- Secret Key는 Integration 설정 페이지에서 복사
- 페이지 권한 부여: Notion 페이지 우측 상단 `...` → Connections → Integration 추가

## Connections

- [[zettelkasten]] — Obsidian은 Zettelkasten 방법론의 디지털 구현 도구

## Footnotes

[^1]: content/Tools/2024-03-09-Obsidian to Notion 자동화.md
