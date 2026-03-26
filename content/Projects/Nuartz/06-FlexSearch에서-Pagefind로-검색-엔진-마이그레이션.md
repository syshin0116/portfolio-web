---
title: "FlexSearch에서 Pagefind로: nuartz 검색 엔진 마이그레이션"
date: 2026-03-26
tags:
  - nuartz
  - pagefind
  - flexsearch
  - search
  - nextjs
description: "nuartz의 검색 엔진을 FlexSearch에서 Pagefind로 마이그레이션한 과정과 비교 분석"
---

## 왜 마이그레이션했나

nuartz의 검색 기능은 원래 FlexSearch 기반이었다. 동작은 했지만, Nextra 등 다른 문서 사이트 프레임워크를 리서치하던 중 Pagefind를 발견했다. Pagefind는 CloudCannon에서 만든 정적 사이트 검색 라이브러리로, Rust/WASM 기반에 BM25 랭킹을 사용한다.

직접 테스트해 보니 검색 품질 차이가 확연했다. FlexSearch는 단순 토큰 매칭이라 의도와 다른 결과가 상위에 올라오는 경우가 많았고, Pagefind의 BM25 기반 랭킹은 사용자의 검색 의도에 훨씬 가까운 결과를 보여줬다.

## FlexSearch vs Pagefind 비교

| 항목 | FlexSearch | Pagefind |
|------|-----------|----------|
| 언어 | JavaScript | Rust + WASM |
| 인덱싱 시점 | 런타임 | 빌드 타임 |
| 데이터 전송 | 전체 콘텐츠 전송 (74KB) | lazy fragment loading |
| 랭킹 알고리즘 | 토큰 매칭 | BM25 |
| CJK 지원 | 커스텀 토크나이저 필요 | 내장 지원 |
| 번들 크기 | ~46KB | ~65KB (초기 로드) |

FlexSearch는 런타임에 전체 콘텐츠를 JSON으로 받아서 클라이언트에서 인덱싱한다. 콘텐츠가 적을 때는 괜찮지만, 페이지 수가 늘어나면 초기 로딩 비용이 선형적으로 증가한다. Pagefind는 빌드 타임에 인덱스를 생성하고, 검색 시 필요한 fragment만 lazy하게 로드하기 때문에 콘텐츠 규모에 관계없이 일정한 성능을 유지한다.

## 검색 품질 테스트 결과

실제 nuartz 문서에서 동일한 쿼리로 검색했을 때 1위 결과 비교:

| 쿼리 | FlexSearch 1위 | Pagefind 1위 |
|------|---------------|-------------|
| `draft` | Deployment | **Draft Filtering** |
| `config` | Authoring Content | **Configuration** |
| `image` | Authoring Content | **Social Images** |
| `remark plugin` | Architecture | **Processing Pipeline** |

FlexSearch는 해당 키워드가 본문에 포함된 문서를 반환하긴 하지만, 가장 관련성 높은 문서를 1위로 올리지 못했다. Pagefind는 BM25 알고리즘 덕분에 키워드의 빈도와 문서 내 중요도를 반영하여 직관적으로 맞는 결과를 상위에 노출시켰다.

## data-pagefind-body의 중요성

Pagefind를 처음 적용했을 때 이상한 결과가 나왔다. `graph view`를 검색하면 "Table of Contents" 페이지가 1위로 나오는 식이었다. 원인은 Pagefind가 네비게이션, 사이드바, 푸터 등 UI 텍스트까지 전부 인덱싱했기 때문이다.

해결책은 `data-pagefind-body` 속성이다. 메인 콘텐츠 영역에만 이 속성을 지정하면 Pagefind는 해당 영역만 인덱싱한다.

```tsx
<article data-pagefind-body>
  {/* 본문 콘텐츠만 인덱싱 대상 */}
  <MDXContent />
</article>
```

이 한 줄로 인덱싱 대상 페이지가 91개에서 57개로 줄었고, UI 노이즈가 제거되면서 검색 품질이 크게 개선됐다.

## 구현 방법

### 1. 빌드 타임 인덱싱

`next build` 이후 postbuild 스크립트로 Pagefind를 실행한다.

```json
{
  "scripts": {
    "build": "next build",
    "postbuild": "pagefind --site .next/server/app --output-path public/_pagefind"
  }
}
```

Pagefind는 빌드된 HTML을 크롤링해서 인덱스를 생성하고, `public/_pagefind/` 디렉토리에 결과물을 저장한다.

### 2. Command Palette에서 동적 로드

검색 UI는 기존 command-palette 컴포넌트를 유지하되, 검색 엔진만 교체했다. Pagefind WASM은 dynamic import로 필요할 때만 로드한다.

```ts
let pagefind: PagefindInstance | null = null;

async function getPagefind() {
  if (!pagefind) {
    pagefind = await import(
      /* webpackIgnore: true */ "/_pagefind/pagefind.js"
    );
    await pagefind.init();
  }
  return pagefind;
}
```

### 3. 개발 모드 Fallback

Pagefind 인덱스는 빌드 후에만 존재하므로 `next dev` 중에는 사용할 수 없다. 기존 API route 기반 검색을 dev 모드 fallback으로 유지했다.

```ts
const isDev = process.env.NODE_ENV === "development";

async function search(query: string) {
  if (isDev) {
    return fetchFromApiRoute(query);
  }
  const pf = await getPagefind();
  return pf.search(query);
}
```

## 번들 크기

초기 로드 기준으로 Pagefind(~65KB)가 FlexSearch(~46KB)보다 약간 크다. 하지만 FlexSearch는 여기에 전체 콘텐츠 JSON(74KB)이 추가로 필요하다. 콘텐츠가 늘어날수록 이 차이는 더 벌어진다.

Pagefind는 WASM 바이너리와 최소한의 인덱스 메타데이터만 초기 로드하고, 실제 검색 결과의 snippet은 fragment 단위로 lazy하게 가져온다. 100페이지든 10,000페이지든 초기 로드 비용은 동일하다.

## 정리

FlexSearch에서 Pagefind로의 마이그레이션은 검색 품질과 확장성 모두에서 의미 있는 개선이었다. 특히 BM25 랭킹과 `data-pagefind-body`를 통한 노이즈 제거가 실질적인 사용자 경험 차이를 만들었다. 구현 난이도도 높지 않아서, 정적 사이트에 검색을 추가해야 한다면 Pagefind를 강력히 추천한다.
