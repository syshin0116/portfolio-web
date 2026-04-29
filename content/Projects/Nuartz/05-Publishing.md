---
title: "Nuartz npm 배포: 버전 관리와 자동화"
date: 2026-03-06
tags:
  - Projects
  - Nuartz
  - npm
  - CI-CD
  - GitHub-Actions
draft: false
enableToc: true
description: Nuartz를 npm에 배포하고, 버전 관리와 CHANGELOG를 정착시키고, GitHub Actions로 publish를 자동화한 과정을 기록한다.
summary: "0.1.0을 수동으로 첫 배포하고, CHANGELOG.md로 버전 히스토리를 관리하고, git 태그를 push하면 GitHub Actions가 자동으로 npm publish하는 파이프라인을 만들었다. 다음 릴리즈부터는 버전 올리고 태그 push하면 끝이다."
---
> [!info] 이전 글
> Headless 설계와 레포 재편 과정은 [[04-Headless-and-Ecosystem|이전 글]]에서 다뤘다.

---

## npm 배포

Nuartz는 `packages/nuartz`가 npm 패키지다. 첫 배포는 수동으로 진행했다.

```bash
cd packages/nuartz
bun run build
npm publish --access public
```

`--access public`을 명시한 이유는 기본값이 scoped 패키지(`@scope/name`) 기준으로 private이기 때문이다. `nuartz`처럼 unscoped 패키지는 사실 없어도 되지만, 명시적으로 두는 게 안전하다.

---

## CHANGELOG.md

버전이 쌓이면 "이 버전에 뭐가 들어갔는지" 추적하기 어려워진다. CHANGELOG.md를 프로젝트 루트에 두고 릴리즈할 때마다 직접 편집한다.

> [!tip] Changesets vs CHANGELOG.md
>
> **Changesets**는 코드 변경할 때마다 `.changeset/` 폴더에 변경 메모를 커밋해두면, 나중에 `changeset version` 명령 하나로 CHANGELOG.md 자동 생성 + package.json 버전 bump까지 해준다. 팀 프로젝트에서 PR 단위로 관리할 때 강력하다.
>
> 솔로 프로젝트에서는 오버킬이다. 직접 편집하는 CHANGELOG.md로 충분하다.

```markdown
## [0.1.1] - 2026-03-06

### Fixed
- FlexSearch CJK 토크나이저 - 한국어 검색 수정
- KaTeX CSS 주입
- Heading anchor 위치 수정
- defineConfig baseUrl 타입 보장

## [0.1.0] - 2026-03-01

Initial release.

### Added
- renderMarkdown() - wikilink, callout, highlight, 수식, 코드 하이라이팅
- getAllMarkdownFiles(), buildFileTree()
- buildSearchIndex() - FlexSearch CJK 지원
- buildBacklinkIndex() / getBacklinks()
- nuartz.config.ts 설정 시스템
```

---

## GitHub Actions로 publish 자동화

매번 수동으로 하면 실수가 생긴다. `v*` 태그를 push하면 자동으로 build → publish하도록 워크플로를 만들었다.

```yaml
# .github/workflows/publish.yml
name: Publish

on:
  push:
    tags:
      - "v*"

jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: oven-sh/setup-bun@v2
      - run: bun install --frozen-lockfile
      - run: bun run --cwd packages/nuartz build
      - run: bun publish --cwd packages/nuartz --access public
        env:
          NPM_TOKEN: ${{ secrets.NPM_TOKEN }}
          NPM_CONFIG_TOKEN: ${{ secrets.NPM_TOKEN }}
```

**사전 조건**: GitHub 레포 Settings → Secrets → `NPM_TOKEN`에 npm Access Token 등록.

---

## 릴리즈 플로우

이제 다음 릴리즈부터는 세 단계면 끝이다.

```bash
# 1. CHANGELOG.md에 새 버전 섹션 추가
# 2. package.json 버전 bump
# 3. 태그 push
git tag v0.1.2
git push --tags
```

태그가 push되는 순간 GitHub Actions가 build → publish까지 처리한다.

---

## 시리즈

- [[01-Motivation|01. 출발점 - Quartz의 한계에서 시작된 여정]]
- [[02-Quartz-Internals|02. Quartz 플러그인 해부: 무엇을 재사용할 수 있나]]
- [[03-Vercel-Deployment|03. 첫 배포: 구현 내용과 Vercel에서 만난 것들]]
- [[04-Headless-and-Ecosystem|04. Headless 설계와 레포 생태계 재편]]
- [[05-Publishing|05. npm 배포: 버전 관리와 자동화]]
