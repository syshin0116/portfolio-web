---
title: "정적 사이트 생성기(SSG) 비교"
type: reference
tags:
  - ssg
  - blog
  - jekyll
  - hugo
  - gatsby
  - frontend
  - github-pages
  - comparison
summary: "GitHub Pages 배포용 SSG 중 Jekyll(Ruby), Hugo(Go), Hexo(Node.js), Gatsby(React)를 비교한 가이드다. Jekyll은 GitHub Pages 기본 지원으로 초보자에 적합하고, Hugo는 빌드 속도가 가장 빠르며 대규모에 적합하다. Hyde 테마 기반 Jekyll 포트폴리오 블로그 설정 방법도 포함한다."
sources:
  - content/Tools/2024-01-03-Git Blog SSG 비교.md
  - content/Tools/2024-01-01-깃 블로그 생성.md
  - content/Tools/2024-01-05-Hugo 블로그 생성 연습.md
  - content/Tools/Git/2023-12-11-Git Blog Themes.md
created: 2026-04-26
updated: 2026-04-26
author: wiki-curator
draft: false
---

## Key Claims

- SSG(Static Site Generator)는 Markdown 파일을 정적 HTML로 변환해 GitHub Pages 등에 호스팅하는 도구다.[^1]
- **Jekyll**: Ruby 기반, GitHub Pages가 기본 지원. 간단한 블로그에 적합. 단점: 대규모 빌드 느림, Ruby 환경 설정 필요.[^1]
- **Hugo**: Go 기반, 가장 빠른 빌드 속도, 대규모 사이트에 적합. GitHub Pages에도 배포 가능.[^1]
- **Hexo**: Node.js 기반, 빠른 렌더링, 풍부한 플러그인. 단점: Node.js 종속성 이슈 가능.[^1]
- **Gatsby**: React 기반, 현대적 JS 생태계. 단점: 빌드 속도 느림, React 지식 필요.[^1]
- Jekyll Hyde 테마 설정 시 `git clone` 대신 `download zip`을 사용해야 GitHub 잔디(contribution)가 정상적으로 심어진다. clone/fork 시 원본 레포로 commit merge되어야 잔디가 반영된다.[^2]
- Hugo는 레이아웃 파일이 없으면 "found no layout file for 'html'" 오류가 발생한다. 테마 submodule이 제대로 연결됐는지 확인 필요.[^3]

## Examples / Code

SSG 비교 표:

| | Jekyll | Hugo | Hexo | Gatsby |
|---|---|---|---|---|
| 언어 | Ruby | Go | Node.js | React/JS |
| 빌드 속도 | 느림(대규모) | 매우 빠름 | 빠름 | 느림 |
| GitHub Pages | 기본 지원 | 가능 | 가능 | 가능 |
| 학습 곡선 | 낮음 | 중간 | 낮음 | 높음 |
| 추천 용도 | 개인 블로그 | 대규모/기술 | 블로그 | 앱 수준 |

Jekyll `_config.yml` 기본 설정:

```yaml
title: My Blog
description: 포트폴리오 블로그
url: "https://username.github.io"
github: username
google_analytics: "UA_TOKEN"
```

## Connections

- [[quartz-publishing]] — Quartz는 Obsidian 노트를 위한 SSG로, 마크다운 기반 블로그의 대안적 접근

## Footnotes

[^1]: content/Tools/2024-01-03-Git Blog SSG 비교.md
[^2]: content/Tools/2024-01-01-깃 블로그 생성.md
[^3]: content/Tools/2024-01-05-Hugo 블로그 생성 연습.md
