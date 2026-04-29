---
title: "Quartz로 Obsidian 노트 배포하기"
type: pattern
tags:
  - obsidian
  - quartz
  - github-pages
  - blog
  - publishing
  - ssg
  - markdown
summary: "Quartz는 Obsidian 마크다운 노트를 정적 웹사이트로 변환해 GitHub Pages에 배포하는 오픈소스 SSG다. jackyzha0/quartz를 클론하고, GitHub Actions 워크플로우로 자동 배포를 설정하며, 커스텀 도메인 연결도 지원한다."
sources:
  - content/Tools/Obsidian/Quartz, GitHub Pages 사용하여 Obsidian 노트 배포.md
created: 2026-04-26
updated: 2026-04-26
author: wiki-curator
draft: false
---

## Key Claims

- Quartz는 Obsidian Markdown 노트를 정적 웹사이트로 변환하는 오픈소스 SSG다. jackyzha0/quartz 저장소 기반.[^1]
- 초기화: `git clone https://github.com/jackyzha0/quartz.git && cd quartz && npm i && npx quartz create`. 링크 해결 방식은 "Treat links as shortest path" 선택.[^1]
- 원본 origin을 자신의 GitHub 저장소로 변경하고, Quartz 업스트림 업데이트를 받기 위해 upstream remote를 추가한다.[^1]
- GitHub Pages 배포는 `.github/workflows/deploy.yml` Actions 파일로 자동화한다.[^1]
- Quartz 4.0의 기본 브랜치는 `v4`지만 `main`으로 변경 가능하다.[^1]
- Google Analytics 설정이 이미 있다면 Google Search Console 소유권 확인을 가장 쉽게 처리할 수 있다. `quartz.config.ts`에서 `analytics.provider: "google", tagId: "G-XXXX"` 설정.[^1]

## Examples / Code

Remote 설정:

```bash
# origin을 자신의 레포로 변경
git remote set-url origin https://github.com/username/username.github.io.git

# Quartz 공식 저장소를 upstream으로 추가
git remote add upstream https://github.com/jackyzha0/quartz.git
```

GitHub Actions 배포 파일 위치: `.github/workflows/deploy.yml`

Google Analytics + Search Console 설정 (`quartz.config.ts`):

```typescript
analytics: {
  provider: "google",
  tagId: "G-YOUR_TAG_ID",
}
```

## Connections

- [[blog-seo]] - Quartz 배포 후 Google Search Console 등록과 SEO 최적화 설정 단계
- [[static-site-generators]] - Quartz는 Obsidian에 특화된 SSG이며, Jekyll/Hugo 등 범용 SSG와 비교 가능

## Footnotes

[^1]: content/Tools/Obsidian/Quartz, GitHub Pages 사용하여 Obsidian 노트 배포.md
