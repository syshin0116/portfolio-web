---
title: GitHub Actions google-protobuf 오류 해결
date: 2024-01-15
tags:
- github-actions
- troubleshooting
- google-protobuf
- python
- dependency
- error-fix
draft: false
enableToc: true
description: GitHub Actions에서 발생한 google-protobuf 의존성 오류 진단 및 해결 방법
summary: "GitHub Actions 워크플로우에서 발생한 google-protobuf 의존성 오류를 진단하고 해결한 과정이다. 오류 메시지 분석, 원인 파악(패키지 버전 충돌), 그리고 requirements.txt 수정을 통한 해결 방법을 포함한다."
published: 2024-01-15
modified: 2024-01-15
---
## 오류:


Github Actions에 다음과 같은 오류가 났다:

![](https://i.imgur.com/K6npfCb.png)


```shell
An error occurred while installing google-protobuf (3.25.2), and Bundler cannot
continue.

In Gemfile:
  jekyll-theme-chirpy was resolved to 5.6.1, which depends on
    jekyll-archives was resolved to 2.2.1, which depends on
      jekyll was resolved to 4.3.3, which depends on
        jekyll-sass-converter was resolved to 3.0.0, which depends on
          sass-embedded was resolved to 1.69.7, which depends on
            google-protobuf
Error: The process '/opt/hostedtoolcache/Ruby/3.3.0/x64/bin/bundle' failed with exit code 5
```



## 해결 방법:

ruby 버전과 호환이 안되서 발생하는 오류다.

.github/workflows/pages-deploy.yml 에서

ruby version을 3 에서 3.2로 변경해주자 해결되었다


```yml
jobs:
  build:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout
        uses: actions/checkout@v3
        with:
          fetch-depth: 0
          # submodules: true
          # If using the 'assets' git submodule from Chirpy Starter, uncomment above
          # (See: https://github.com/cotes2020/chirpy-starter/tree/main/assets)

      - name: Setup Pages
        id: pages
        uses: actions/configure-pages@v3

      - name: Setup Ruby
        uses: ruby/setup-ruby@v1
        with:
          ruby-version: 3.2   # reads from a '.ruby-version' or '.tools-version' file if 'ruby-version' is omitted
          bundler-cache: true

```


![](https://i.imgur.com/AvImp0M.png)

짠 다시 잘 되는것을 확인할 수 있다