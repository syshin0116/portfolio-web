---
title: "Quartz 플러그인 해부: 무엇을 재사용할 수 있나"
date: 2026-03-01
tags:
  - Projects
  - Nuartz
  - Quartz
  - remark
  - rehype
  - OFM
draft: false
enableToc: true
description: Quartz 플러그인 구조를 직접 뜯어보고, Next.js에서 재사용 가능한 것과 그렇지 않은 것을 구분한다. OFM이 Quartz의 진짜 자산인 이유.
summary: "Quartz 플러그인 대부분은 npm 패키지 래퍼였다. GFM, LaTeX, SyntaxHighlighting은 직접 써도 동일하다. 진짜 Quartz의 자산은 OFM — wikilink, callout, tag 파싱 로직을 직접 구현한 플러그인이다. externalResources는 Quartz 자체 런타임에 의존해서 Next.js에서 쓸 수 없고, React 컴포넌트로 대체하면 된다."
---
> [!info] 이전 글
> sync-quartz 전략이 왜 막혔는지는 [[01-Motivation|첫 번째 글]]에서 다뤘다. 이 글은 그 원인을 파악하기 위해 Quartz 플러그인 구조를 직접 해부한 기록이다.

---

## 플러그인 인터페이스

Quartz의 Transformer 플러그인은 4가지 메서드로 구성된다:

```typescript
// quartz/plugins/types.ts
type QuartzTransformerPluginInstance = {
  name: string
  textTransform?: (ctx: BuildCtx, src: string) => string     // 파싱 전 텍스트 변환
  markdownPlugins?: (ctx: BuildCtx) => PluggableList          // remark 플러그인 목록 반환
  htmlPlugins?: (ctx: BuildCtx) => PluggableList              // rehype 플러그인 목록 반환
  externalResources?: (ctx: BuildCtx) => { js, css }         // 브라우저 런타임 리소스
}
```

핵심은 `markdownPlugins`와 `htmlPlugins`가 결국 **remark/rehype 플러그인 배열을 반환**한다는 점이다. Quartz는 unified 파이프라인 위에서 동작한다.

---

## 대부분은 npm 패키지 래퍼

플러그인들을 하나씩 열어보면 실체가 보인다.

**GFM (GitHub Flavored Markdown):**
```typescript
// quartz/plugins/transformers/gfm.ts
markdownPlugins() {
  return [remarkGfm, smartypants]  // 그냥 npm 패키지 반환
}
htmlPlugins() {
  return [rehypeSlug, rehypeAutolinkHeadings]  // 그냥 npm 패키지 반환
}
```

**Latex:**
```typescript
// quartz/plugins/transformers/latex.ts
import remarkMath from "remark-math"
import rehypeKatex from "rehype-katex"

markdownPlugins() { return [remarkMath] }
htmlPlugins() { return [[rehypeKatex, { output: "html" }]] }
```

**SyntaxHighlighting:**
```typescript
// quartz/plugins/transformers/syntax.ts
import rehypePrettyCode from "rehype-pretty-code"

htmlPlugins() { return [[rehypePrettyCode, opts]] }
```

이 세 개는 Quartz 래퍼 없이 npm 패키지를 직접 써도 완전히 동일하다.

---

## 진짜 핵심: OFM

**ObsidianFlavoredMarkdown (OFM)** 만이 진짜 Quartz의 자산이다.

wikilink, callout, highlight(`==text==`), block reference(`^id`), tag 파싱 — 이 로직들을 Quartz 개발자들이 직접 구현했다.

```typescript
// quartz/plugins/transformers/ofm.ts - 직접 구현한 정규식들
export const wikilinkRegex = new RegExp(
  /!?\[\[([^\[\]\|\#\\]+)?(#+[^\[\]\|\#\\]+)?(\\?\|[^\[\]\#]*)?\]\]/g
)
export const calloutRegex = new RegExp(/^\[\!([\w-]+)\|?(.+?)?\]([+-]?)/)
export const tagRegex = new RegExp(
  /(?<=^| )#((?:[-_\p{L}\p{Emoji}\p{M}\d])+(?:\/[-_\p{L}\p{Emoji}\p{M}\d]+)*)/gu
)
```

실제 callout 파싱도 직접 구현했다:

```typescript
markdownPlugins(ctx) {
  plugins.push(() => {
    return (tree: Root, _file) => {
      visit(tree, "blockquote", (node) => {
        const match = firstLine.match(calloutRegex)
        if (match) {
          node.data = {
            hProperties: {
              className: ["callout", calloutType],
              "data-callout": calloutType,
            }
          }
        }
      })
    }
  })
}
```

정리하면:

| 플러그인 | 출처 |
|---|---|
| Latex | npm 래퍼 (`remark-math`, `rehype-katex`) |
| SyntaxHighlighting | npm 래퍼 (`rehype-pretty-code`) |
| GFM | npm 래퍼 (`remark-gfm`, `rehype-slug`) |
| FrontMatter | npm 래퍼 (`gray-matter`, `remark-frontmatter`) |
| **OFM** | **Quartz 자체 구현** ← 진짜 가치 |
| TOC, Links | 부분 자체 구현 |

---

## externalResources란?

inline script 이슈의 실체가 바로 `externalResources`다.

### 동작 방식

`externalResources()`는 플러그인이 **브라우저에서 실행될 JS/CSS를 선언**하는 메서드다.

```typescript
// ofm.ts
externalResources() {
  return {
    js: [
      { script: calloutScript, loadTime: "afterDOMReady", contentType: "inline" },
      { script: checkboxScript, loadTime: "afterDOMReady", contentType: "inline" },
      { script: mermaidScript, loadTime: "afterDOMReady", moduleType: "module" },
    ]
  }
}
```

Quartz 빌드 파이프라인은 이걸 수집해서 생성된 HTML의 `<head>`에 `<script>` 태그로 주입한다.

```
[플러그인 externalResources()]
    ↓ getStaticResourcesFromPlugins(ctx)
    ↓ emitter.emit(ctx, content, staticResources)
[생성된 HTML에 <script> 주입]
    ↓ 브라우저에서 실행
[callout 접기/펼치기, mermaid 렌더링 등]
```

### 왜 Next.js에서 안 되나

Quartz의 스크립트들은 Quartz 고유 런타임에 의존한다.

```typescript
// callout.inline.ts
document.addEventListener("nav", setupCallout)
//                         ↑
//          Quartz SPA 라우터가 dispatch하는 커스텀 이벤트
//          Next.js에는 이 이벤트가 없음
```

Quartz는 자체 SPA 라우터(`spa.inline.ts`)가 있고, 페이지 이동 시마다 `nav` 이벤트를 dispatch한다. 스크립트들은 이 이벤트를 들어서 재초기화한다.

> [!note] static site라서 필요한 것
>
> Quartz는 완전한 `.html` 파일을 생성하는 정적 사이트 생성기다. React 런타임이 없으니 인터랙션을 `<script>` 태그로 직접 주입해야 한다.
>
> Next.js에서는 같은 기능을 React 컴포넌트로 구현하면 된다.
>
> ```diff
> // Quartz 방식
> - document.addEventListener("nav", () => {
> -   document.querySelectorAll(".callout-title").forEach(el => {
> -     el.addEventListener("click", toggle)
> -   })
> - })
>
> // Next.js 방식
> + function Callout({ type, title, children }) {
> +   const [collapsed, setCollapsed] = useState(false)
> +   return (
> +     <div onClick={() => setCollapsed(!collapsed)}>{title}</div>
> +   )
> + }
> ```

결국 `externalResources()`는 Quartz가 자체 런타임을 가지고 있기 때문에 필요한 개념이다. Next.js에서는 React 컴포넌트로 대체하면 그만이다.

---

## 결론: 무엇을 가져올 것인가

분석을 통해 명확해진 것:

- Quartz 플러그인의 `markdownPlugins()` / `htmlPlugins()`는 **재사용 가능**하다
- `externalResources()`는 **무시하면 된다** (React로 대체)
- Latex, GFM, Syntax는 **npm 패키지 직접 사용**이 더 단순하다

OFM 플러그인을 직접 가져오는 방식:

```typescript
import { ObsidianFlavoredMarkdown } from "../quartz/plugins/transformers/ofm"

const ofm = ObsidianFlavoredMarkdown({ wikilinks: true, callouts: true })

const processor = unified()
  .use(remarkParse)
  .use(ofm.markdownPlugins({ allSlugs: [] }))  // wikilink, callout, tag 파싱
  .use(remarkRehype)
  .use(ofm.htmlPlugins())                       // block reference, YouTube embed
  .use(rehypeStringify)
```

`ctx.allSlugs`는 broken wikilink 감지 옵션에서만 쓰이고, 나머지는 ctx 의존성이 거의 없다. 빈 배열로 넘겨도 동작한다.

> [!tip] sync-quartz는 이 목적으로는 유효하다
>
> OFM 파일 하나만 복사해서 쓰는 용도라면 sync-quartz 전략은 여전히 의미가 있다. 문제는 Quartz 전체를 래핑하려 했던 초기 설계였다.
>
> ```
> 수정된 전략:
> upstream/quartz/quartz/plugins/transformers/ofm.ts  ← 이것만 가져옴
> 나머지는 npm 패키지 직접 사용
> ```
