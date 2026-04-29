---
title: "블로그 검색 노출 및 SEO 설정"
type: reference
tags:
  - seo
  - google-search-console
  - sitemap
  - blog
  - quartz
  - frontend
  - search
summary: "블로그를 검색 엔진에 노출시키기 위한 단계별 가이드다. Google Search Console 등록(HTML 파일/메타 태그/Google Analytics 세 가지 소유권 확인 방법), sitemap 제출, robots.txt 설정을 다루며, Quartz 기반 블로그에서의 구체적인 설정 방법을 포함한다."
sources:
  - content/Tools/Obsidian/검색 노출 시키는 방법.md
created: 2026-04-26
updated: 2026-04-26
author: wiki-curator
draft: false
---

## Key Claims

- Google Search Console 등록 시 속성 유형을 선택해야 한다: **URL 접두어**(특정 URL만 추적, 다양한 인증 방법)가 초보자에게 추천된다.[^1]
- 소유권 확인 방법 3가지:
  1. **HTML 파일 업로드** (Quartz에서 가장 간단): 파일을 `content/` 루트에 복사 후 빌드·배포
  2. **HTML 메타 태그**: `quartz/components/Head.tsx` 파일에 `<meta name="google-site-verification">` 태그 추가
  3. **Google Analytics** (가장 간단): 이미 GA가 설정된 경우 자동 확인[^1]
- Quartz에서 Google Analytics 설정이 있다면 Search Console 소유권 확인에 GA 방법을 사용하면 별도 파일 수정이 불필요하다.[^1]
- Sitemap 제출은 Search Console → 색인 생성 → Sitemaps 메뉴에서 수행한다.[^1]
- robots.txt는 검색 엔진 크롤러가 접근할 수 없는 페이지를 지정한다. Quartz에서는 기본 설정으로 대부분의 경우 충분하다.[^1]

## Examples / Code

Quartz `quartz/components/Head.tsx`에 메타 태그 추가 방법:

```tsx
{/* Google Search Console verification */}
<meta name="google-site-verification" content="YOUR_VERIFICATION_CODE" />
```

`quartz.config.ts` Google Analytics 설정:

```typescript
analytics: {
  provider: "google",
  tagId: "G-XZB0EYZF1G",
}
```

## Connections

- [[quartz-publishing]] - Search Console 설정은 Quartz 배포 이후 단계

## Footnotes

[^1]: content/Tools/Obsidian/검색 노출 시키는 방법.md
