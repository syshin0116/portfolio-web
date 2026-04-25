---
title: Quartz, GitHub Pages 사용하여 Obsidian 노트 배포
date: 2025-03-06
tags:
- obsidian
- quartz
- github-pages
- blog
draft: false
enableToc: true
description: Obsidian 노트를 Quartz를 사용하여 GitHub Pages에 배포하는 방법을 단계별로 설명
summary: "이 문서는 Obsidian에서 작성한 Markdown 노트를 Quartz를 사용하여 정적 웹사이트로 변환하고 GitHub Pages에 배포하는 방법을 안내한다. 먼저 Quartz를 클론하고 초기화한 후, GitHub 저장소를 설정하여 Quartz 프로젝트를 자신의 저장소와 연결한다. 배포 자동화를 위해 GitHub Actions 설정 파일을 생성하고, GitHub Pages를 활성화한다. 로컬에서 Quartz 사이트를 빌드하여 확인한 후, 변경사항을 GitHub에 동기화한다. 마지막으로, 사용자 정의 도메인을 설정하는 방법도 안내한다. 이 가이드를 통해 Obsidian 노트를 쉽게 공유하고 관리할 수 있다."
published: 2025-03-06
modified: 2025-03-06
---
## 개요

이 가이드는 **Obsidian**에서 작성한 Markdown 노트를 **Quartz**를 사용하여 정적 웹사이트로 변환하고 **GitHub Pages**에 배포하는 방법을 설명한다.

### 참고자료
- **YouTube**: [How to publish your notes for free with Quartz](https://www.youtube.com/watch?v=6s6DT1yN4dw&t=1s)
- **Quartz 공식 문서**: [Quartz 4.0](https://quartz.jzhao.xyz/)

![](https://i.imgur.com/r5O2hdl.png)

---

## 1. Quartz 로컬 폴더 초기화하기

Quartz를 클론하고, 의존성을 설치한 후 프로젝트를 초기화한다.

```bash
git clone https://github.com/jackyzha0/quartz.git
cd quartz
npm i
npx quartz create
```

### 초기화 옵션

- 처음부터 시작하는 경우 **Empty Quartz** 선택
- 링크 해결 방식은 **Treat links as shortest path** 선택

![](https://i.imgur.com/z1HbfPW.png)
![](https://i.imgur.com/J5VcxZh.png)

---

## 2. GitHub Repository 설정하기

**Quartz 공식 문서**: [Setting up your GitHub repository](https://quartz.jzhao.xyz/setting-up-your-GitHub-repository)

### Remote Repository 업데이트
Quartz를 공식 저장소에서 클론했기 때문에, 기본 remote(`origin`)가 Quartz 저장소를 가리킨다. 이를 자신의 GitHub 저장소로 변경해야 한다.

```bash
# 현재 remote 저장소 확인
git remote -v
 
# origin remote를 자신의 GitHub 저장소로 변경
git remote set-url origin https://github.com/syshin0116/syshin0116.github.io.git
 
# 공식 Quartz 저장소의 업데이트를 받기 위해 upstream remote 추가
git remote add upstream https://github.com/jackyzha0/quartz.git
```

이제 Quartz 프로젝트가 자신의 GitHub 저장소와 연결되어 배포할 준비가 되었다.

---

## 3. GitHub Pages에 배포하기

GitHub Pages를 사용하여 Quartz 사이트를 호스팅한다.

### 1) GitHub Actions 설정
배포를 자동화하기 위해 `.github/workflows/deploy.yml` 파일을 생성하고 다음 내용을 추가한다:

>[!Note] 
>Quartz 4.0은 기본 브랜치로 `v4`를 사용하지만, 저는 이를 선호하지 않아 `main`으로 변경했다.

```yml
name: Deploy Quartz site to GitHub Pages

on:
  push:
    branches:
      - main

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: "pages"
  cancel-in-progress: false

jobs:
  build:
    runs-on: ubuntu-22.04
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0 # git 이력 전체를 가져옴
      - uses: actions/setup-node@v4
        with:
          node-version: 22
      - name: Install Dependencies
        run: npm ci
      - name: Build Quartz
        run: npx quartz build
      - name: Upload artifact
        uses: actions/upload-pages-artifact@v3
        with:
          path: public

  deploy:
    needs: build
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to GitHub Pages
        id: deployment
        uses: actions/deploy-pages@v4
```

>[!Note]- 제가 한 것처럼 메인 브랜치를 `main`으로 설정했다면, `quartz/cli/constants.js` 파일도 수정해야 한다.
>```javascript
>import path from "path"
>import { readFileSync } from "fs"
>
>export const ORIGIN_NAME = "origin"
>export const UPSTREAM_NAME = "upstream"
>export const QUARTZ_SOURCE_BRANCH = "main" // 브랜치 업데이트
>export const cwd = process.cwd()
>export const cacheDir = path.join(cwd, ".quartz-cache")
>export const cacheFile = "./quartz/.quartz-cache/transpiled-build.mjs"
>export const fp = "./quartz/build.ts"
>export const { version } = JSON.parse(readFileSync("./package.json").toString())
>export const contentCacheFolder = path.join(cacheDir, "content-cache")
>``` 

### 2) GitHub Pages 활성화
- **GitHub → Repository → Settings → Pages**로 이동
- **Source**를 **GitHub Actions**로 설정
- 배포 후 사이트 URL 확인

---

## 4. 사이트 빌드 및 동기화

### Quartz 사이트 로컬 빌드
배포하기 전에 Quartz가 로컬 환경에서 올바르게 빌드되는지 확인한다.

```bash
npx quartz build --serve
```

브라우저에서 [http://localhost:8080](http://localhost:8080)을 열어 사이트를 미리 본다.

### GitHub과 변경사항 동기화

공식 문서에서는 다음과 같이 안내한다:
```bash
npx quartz sync
```

이제 사이트가 GitHub Pages에서 라이브로 제공된다.

---

## 5. 사용자 정의 도메인 설정 (선택사항)

기본적으로 사이트는 `https://yourusername.github.io/your-repository-name/`에서 호스팅된다.
사용자 정의 도메인을 사용하려면 다음 단계를 따르자:

### 1) 도메인 DNS 설정
도메인의 **DNS 레코드**에 다음 A 레코드들을 추가한다:

```
185.199.108.153
185.199.109.153
185.199.110.153
185.199.111.153
```

### 2) GitHub Pages 설정 업데이트
- **GitHub → Repository → Settings → Pages**로 이동
- **Custom domain**에 사용자 정의 도메인을 입력하고 **Save** 클릭
- **Enforce HTTPS** 활성화

DNS 변경사항이 전파되면 사용자 정의 도메인을 통해 사이트에 접속할 수 있다.

---

## 결론
이제 Obsidian 노트를 정적 웹사이트로 변환하여 GitHub Pages에 성공적으로 배포했다. 다음으로 `quartz.config.ts`를 수정하거나, 테마를 변경하거나, 추가 Obsidian 플러그인을 통합하여 사이트를 더 커스터마이징할 수 있다.

깃 블로그의 장점은 커스텀이 아닐까, 앞으로도 꾸준히 커스텀하면서 보기 좋은 블로그를 만들어 보고자 한다.