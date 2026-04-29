---
title: "Nuartz 첫 배포: 구현 내용과 Vercel에서 만난 것들"
date: 2026-03-06
tags:
  - Projects
  - Nuartz
  - Vercel
  - Nextjs
  - Deployment
  - Debugging
draft: false
enableToc: true
description: Phase 1 구현 내용 정리, 그리고 Vercel 배포 과정에서 만난 workspace 프로토콜, Turbopack, 각종 버그들을 기록한다.
summary: "monorepo 구조와 3-column 레이아웃을 구현하고 Vercel에 첫 배포를 시도했다. workspace 프로토콜 문제, Turbopack의 worker_threads 충돌로 webpack 전환, D3 graph view 노드 좌표 버그, KaTeX CSS 누락, 한국어 FlexSearch 토크나이저 구현까지 - 배포하면서 만난 것들을 전부 기록했다."
---
> [!info] 이전 글
> Quartz 플러그인 분석을 통해 어떤 전략을 쓸지 정했다. → [[02-Quartz-Internals|Quartz 플러그인 해부]]

---

## 구현 내용

### monorepo 구조

```
nuartz/
├── packages/nuartz/          ← 마크다운 처리 라이브러리
│   └── src/
│       ├── markdown.ts       ← renderMarkdown() - unified 파이프라인
│       ├── fs.ts             ← getAllMarkdownFiles(), buildFileTree()
│       ├── search.ts         ← buildSearchIndex()
│       └── backlinks.ts      ← buildBacklinkIndex(), getBacklinks()
└── apps/web/                 ← Next.js 16 앱 (Turbopack)
    ├── app/
    │   ├── layout.tsx        ← Header + NavSidebar + CommandPalette
    │   ├── page.tsx          ← 최근 노트 리스트 (홈)
    │   ├── [...slug]/        ← 노트 상세 (3-column: nav | content | ToC)
    │   ├── tags/             ← 태그 목록
    │   └── tags/[tag]/       ← 태그별 노트 리스트
    └── components/
        ├── layout/           ← Header, NavSidebar, MobileNav
        ├── ui/               ← shadcn 컴포넌트 10종
        ├── toc.tsx           ← 오른쪽 목차 (IntersectionObserver)
        ├── backlinks.tsx     ← 역링크 표시
        ├── breadcrumb.tsx    ← 경로 표시
        └── command-palette.tsx ← Cmd+K 전역 검색
```

### 노트 상세 페이지 레이아웃

```
┌──────────┬──────────────────────────────┬──────────┐
│ NavSide  │  Home > folder > Note        │  ToC     │
│ bar      │  ─────────────────────────   │          │
│ (260px)  │  # Title                     │ On page  │
│          │  #tag  2026-03-01            │ ▸ Sec 1  │
│          │  ─────────────────────────   │   Sub    │
│          │  content...                  │ ▸ Sec 2  │
│          │                              │          │
│          │  Linked from (N)             │          │
└──────────┴──────────────────────────────┴──────────┘
```

### 개발 환경 트러블슈팅

bun workspace에서 CSS 패키지 hoisting 이슈가 있었다. `tw-animate-css` 같은 third-party 패키지가 root `node_modules/`로 hoist되는데, Turbopack의 CSS `@import` resolver가 앱 디렉토리 위로 올라가지 못해서 `Module not found` 에러가 발생했다. `next.config.ts`에 `turbopack.root`를 monorepo 루트로 설정해서 해결했다.

또 `postcss.config.mjs`가 없어서 `@tailwindcss/postcss`가 전혀 실행되지 않았다. Tailwind utility 클래스(`flex`, `border`, `bg-muted` 등)가 CSS에 생성되지 않아 화면에 스타일이 아예 적용되지 않는 문제였다. postcss 설정 파일 하나로 해결됐다.

---

## Vercel 배포

### workspace 프로토콜 문제

첫 Vercel 배포를 시도하자마자 빌드가 터졌다.

```
Module not found: Can't resolve 'nuartz'
```

원인은 간단했다. Vercel은 기본적으로 `apps/web` 디렉토리 기준으로 `bun install`을 실행한다. 그런데 `package.json`에 `"nuartz": "workspace:*"`로 선언되어 있고, `workspace:*` 프로토콜은 monorepo 루트에서 설치해야만 올바르게 resolve된다.

해결책: `apps/web/vercel.json`에 install/build 커맨드를 직접 지정했다.

```json
{
  "installCommand": "cd ../.. && bun install --frozen-lockfile",
  "buildCommand": "cd ../.. && bun run build:pkg && cd apps/web && next build"
}
```

monorepo 루트로 올라가서 설치하고, 먼저 `packages/nuartz`를 빌드한 뒤 Next.js 앱을 빌드하는 순서다.

### Turbopack → webpack: worker_threads 충돌

두 번째 배포 시도에서 다른 에러가 나왔다.

```
NftJsonAsset: cannot handle filepath worker_threads
```

FlexSearch가 내부에서 `worker_threads` (Node.js 내장 모듈)를 참조하는데, Turbopack이 이 파일을 추적하다가 처리 못하는 상황이었다.

> [!warning] Turbopack 설정으로 해결하려다 실패
>
> 처음엔 `next.config.ts`에 Turbopack alias를 추가했다.
>
> ```ts
> turbopack: {
>   resolveAlias: { "worker_threads": { browser: false } }
> }
> ```
>
> Vercel 빌드에서 `"boolean values are invalid in exports field entries"` 에러. Turbopack이 browser 필드에 boolean을 못 처리했다.

결국 깔끔한 해결책: Turbopack을 포기하고 webpack으로 돌아갔다.

```ts
// next.config.ts
const nextConfig: NextConfig = {
  transpilePackages: ["nuartz"],
  webpack: (config, { isServer }) => {
    if (!isServer) {
      config.resolve.fallback = {
        ...config.resolve.fallback,
        worker_threads: false,  // 브라우저 번들에서 빈 모듈로 처리
      }
    }
    return config
  },
}
```

Turbopack은 개발(`bun dev`)에서만 쓰고, 프로덕션 빌드는 webpack을 쓰는 게 현재로선 안전하다.

---

## 버그 수정

### Graph View - 노드가 전부 (0,0)에 몰리는 버그

그래프 뷰를 열면 모든 노드가 왼쪽 상단 한 점에 겹쳐서 나타났다.

```ts
// 문제가 있던 코드
sim.stop()
for (let i = 0; i < 300; i++) sim.tick()  // 시뮬레이션 미리 실행

sim.on("tick", () => {
  node.attr("transform", d => `translate(${d.x},${d.y})`)
})
```

원인: D3 force simulation에서 `sim.stop()` 후 `sim.tick()`을 수동으로 호출하면 **`sim.on("tick", callback)`은 절대 실행되지 않는다.** tick 이벤트는 `sim.restart()` 이후 비동기로 실행될 때만 발생한다.

```ts
// 수정된 코드
const updatePositions = () => {
  link
    .attr("x1", d => (d.source as SimNode).x!)
    .attr("y1", d => (d.source as SimNode).y!)
    .attr("x2", d => (d.target as SimNode).x!)
    .attr("y2", d => (d.target as SimNode).y!)
  node.attr("transform", d => `translate(${d.x},${d.y})`)
}

sim.on("tick", updatePositions)
updatePositions()  // ← 즉시 호출 - 정지된 상태에서도 좌표 적용
```

pre-run된 시뮬레이션 결과가 노드 객체 (`d.x`, `d.y`)에는 이미 저장되어 있다. DOM에 적용하는 함수를 한 번만 직접 호출하면 됐다.

### KaTeX - 수식이 깨져서 출력되는 문제

LaTeX 문서를 열면 `\frac`, `\sum` 같은 수식이 HTML 태그가 그대로 보이는 상태였다.

원인은 CSS 미임포트였다. `rehype-katex`는 HTML 구조만 생성하고, 실제 수식처럼 보이게 하는 스타일은 `katex/dist/katex.min.css`를 별도로 로드해야 한다.

```ts
// apps/web/app/layout.tsx에 추가
import "katex/dist/katex.min.css"
```

Quartz는 플러그인 `externalResources()`에서 KaTeX CSS를 자동으로 주입했다. nuartz는 그걸 직접 import해야 한다.

### 헤딩 앵커 - 텍스트가 오른쪽으로 밀리는 문제

```ts
// 이전: behavior: "prepend" - 아이콘을 텍스트 앞에 추가
// 수정: behavior: "append" - 아이콘을 텍스트 뒤에 추가
rehypeAutolinkHeadings({ behavior: "append" })
```

### 검색 - 한국어가 안 되는 문제

기존 검색은 단순한 `String.includes(query)` 방식이었다. **FlexSearch + CJK-aware 토크나이저**로 교체했다.

```ts
// 한국어/일본어/중국어 처리: 각 글자를 별개 토큰으로
function cjkEncoder(str: string): string[] {
  const tokens: string[] = []
  let buf = ""
  for (const char of str.toLowerCase()) {
    const cp = char.codePointAt(0)!
    const isCJK =
      (cp >= 0x3040 && cp <= 0x309f) ||  // 히라가나
      (cp >= 0x30a0 && cp <= 0x30ff) ||  // 가타카나
      (cp >= 0x4e00 && cp <= 0x9fff) ||  // 한자
      (cp >= 0xac00 && cp <= 0xd7af)     // 한글
    if (isCJK) {
      if (buf) { tokens.push(buf); buf = "" }
      tokens.push(char)
    } else if (char === " ") {
      if (buf) { tokens.push(buf); buf = "" }
    } else {
      buf += char
    }
  }
  return tokens
}
```

한국어의 경우 공백 단위 분리가 의미 없다. "머신러닝"을 검색할 때 각 글자가 토큰이 되고 연속 매칭으로 찾는 방식이다.

### 홈페이지 설정 - index.md vs 최근 노트

`nuartz.config.ts`에 `homePage` 옵션을 추가했다:

```ts
export const config: NuartzConfig = {
  homePage: "index",  // "index" | "recent"
}
```

- `"index"`: `content/index.md`를 렌더링해서 홈으로 표시
- `"recent"`: 최근 노트 리스트
- `content/index.md`가 없으면 자동으로 `"recent"` 폴백

### 문서 정비

전체 문서를 실제 코드베이스와 대조해서 검토했다.

| 파일 | 문제 | 수정 |
|------|------|------|
| `features/index.md` | citations, i18n이 구현된 것처럼 표시 | Planned 섹션으로 이동 |
| `plugins/index.md` | `rehypeToc` (존재하지 않는 플러그인) | `rehypeExtractToc`으로 수정 |
| `docs/index.md` | FlexSearch를 "Pagefind"로 잘못 표기 | 수정 |

> [!note] 문서를 코드보다 먼저 썼을 때의 위험
>
> "있으면 좋겠다"고 생각한 기능을 문서에 먼저 써두면, 나중에 구현하지 않았는데도 구현된 것처럼 보이는 상태가 된다. 기능이 없다면 "Planned" 섹션에 넣는 게 맞다.

---

## 마치며

nuartz를 기획하면서 가장 크게 깨달은 것은, **Quartz는 라이브러리가 아니라는 것**이다.

Quartz는 완성도 높은 정적 사이트 생성기다. 내부를 뜯어서 다른 프레임워크에 끼워 맞추려는 시도는 처음부터 설계 불일치를 안고 가는 것이었다.

반면 OFM 플러그인 하나는 진짜 재사용 가능한 자산이다. wikilink와 callout 파싱 로직은 Quartz 개발자들이 공들여 만든 것이고, `markdownPlugins` / `htmlPlugins` 인터페이스 덕분에 unified 파이프라인에 깔끔하게 꽂을 수 있다.

결국 "Quartz를 통째로 가져오려는 욕심"을 내려놓고 "필요한 것만 가져오는 현실적인 전략"으로 방향을 바꿨다. 나머지는 npm 생태계가 이미 잘 해결해두었다.
