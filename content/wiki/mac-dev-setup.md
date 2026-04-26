---
title: "맥북 개발 환경 초기 설정"
type: reference
tags:
  - mac
  - setup
  - homebrew
  - devtools
  - productivity
  - python
  - nodejs
  - docker
summary: "새 맥북을 받을 때 설치할 필수 도구 목록이다. Homebrew를 기반으로 Raycast, uv(Python), fnm(Node.js), Bun, Docker Desktop을 설치하고, App Store → Homebrew → 공식 웹사이트 순서로 설치를 진행한다."
sources:
  - content/Tools/Mac/2025-04-18-맥북 초기 세팅.md
created: 2026-04-26
updated: 2026-04-26
author: wiki-curator
draft: false
---

## Key Claims

- 설치 우선순위: **App Store** → **Homebrew** → **공식 웹사이트** 순서를 권장한다.[^1]
- Homebrew가 모든 설치의 기본이다. iTerm2, Oh My Zsh로 터미널 환경을 먼저 구성한다.[^1]
- Python 버전/패키지 관리는 `uv` 사용 (pyenv + pip 대체). Node.js 버전 관리는 `fnm` 사용 (nvm 대체, 속도 빠름).[^1]
- `Bun`은 JavaScript 런타임 + 패키지 매니저 역할. `npm`/`yarn` 대체 가능.[^1]
- `Raycast`는 macOS Spotlight 대체 런처로 클립보드 관리, 윈도우 관리까지 포함한다.[^1]
- `Rectangle`은 무료 윈도우 크기/위치 관리 도구. `LinearMouse`는 마우스 가속도/스크롤 방향을 기기별로 세밀 조정.[^1]
- 생산성 도구: Obsidian(마크다운 노트), Slack, Discord.[^1]

## Examples / Code

mas-cli를 통한 App Store 앱 일괄 설치:

```sh
brew install mas
mas install 803453959  # Slack
mas install 985746746  # Discord
```

Homebrew 개발 도구 일괄 설치:

```sh
brew install git curl wget
brew install iterm2 visual-studio-code
brew install uv fnm
brew install --cask docker
brew install bun
```

개발 도구 요약:

| 도구 | 역할 | 대체 대상 |
|------|------|----------|
| uv | Python 버전+패키지 관리 | pyenv + pip |
| fnm | Node.js 버전 관리 | nvm |
| Bun | JS 런타임+패키지 관리 | node + npm |
| Raycast | 런처+유틸리티 | Spotlight |
| Rectangle | 윈도우 배치 | 없음 (무료) |

## Footnotes

[^1]: content/Tools/Mac/2025-04-18-맥북 초기 세팅.md
