---
title: GitHub CI/CD와 GCP 통합 정리
date: 2024-11-09
tags:
- github-actions
- cicd
- gcp
- devops
- automation
- cloud
draft: false
enableToc: true
description: GitHub Actions와 GCP를 연동한 CI/CD 파이프라인 개념 및 구조 정리
summary: "GitHub Actions와 GCP를 연동하여 CI/CD 파이프라인을 구축하는 개념과 구조를 정리한 문서이다. 지속적 통합(CI)과 지속적 배포(CD)의 원리, GitHub Actions 워크플로우 구성, GCP 서비스 활용, 그리고 전체 시스템 아키텍처를 개념적으로 이해한다."
published: 2024-11-09
modified: 2024-11-09
---
## Intro:

GCP에 개인 서버를 만들고, 관리하려는데, CI/CD를 만들어놔야 시간 절약을 할 수 있을것 같아 공부해보려 한다.

## CI/CD란?

- **CI/CD**는 Continuous Integration과 Continuous Deployment의 약자로, 소프트웨어 개발 과정에서 코드 변경 사항을 자동으로 빌드, 테스트, 배포하는 일련의 프로세스를 의미
- 코드 수정 후 수동으로 배포하는 번거로움 없이 자동화된 시스템으로 빠르고 안정적으로 업데이트를 진행할 수 있다

### Continuous Integration (CI)

- **지속적 통합**: 여러 개발자가 작업한 코드 변경 사항을 정기적으로 중앙 리포지토리에 병합하고, 이 병합된 코드를 자동으로 빌드하고 테스트하는 과정
- 코드 충돌을 최소화하고, 문제를 조기에 발견하여 품질을 유지하는 데 도움이 된다

### Continuous Deployment (CD)

- **지속적 배포**: CI 과정을 거친 코드가 자동으로 프로덕션 환경에 배포되는 것을 의미
- 새로운 기능이나 수정 사항을 사용자에게 신속하게 제공
- 배포 과정에서 발생할 수 있는 인적 오류를 줄일 수 있다

### CI/CD의 장점

- **자동화된 프로세스**: 빌드, 테스트, 배포 과정을 자동화하여 효율성 향상
- **빠른 피드백 루프**: 코드 변경에 대한 즉각적인 피드백으로 빠른 문제 해결
- **높은 코드 품질**: 지속적인 테스트와 검증으로 안정적인 소프트웨어 제공
- **협업 개선**: 여러 개발자가 동시에 작업해도 통합 과정이 원활하여 팀 생산성이 향상

### GCP에서의 CI/CD 적용

- Google Cloud Platform(GCP)은 Cloud Build, Cloud Deploy 등 다양한 서비스를 통해 CI/CD 파이프라인을 구축할 수 있는 환경을 제공한다. 
- 하지만, 나는 Github Actions를 공부 목적으로 위 서비스는 사용하지 않는다.



## GitHub Actions란?

**GitHub Actions**는 GitHub에서 제공하는 CI/CD(지속적 통합 및 지속적 배포) 플랫폼으로, 리포지토리 내에서 빌드, 테스트, 배포 등의 워크플로를 자동화할 수 있는 도구이다.

[GitHub Docs](https://docs.github.com/ko/actions)

### 주요 구성 요소

- **워크플로(Workflow)**: 자동화된 프로세스를 정의하는 YAML 파일로, `.github/workflows` 디렉터리에 위치한다.
    
- **이벤트(Event)**: 워크플로를 트리거하는 리포지토리 내의 특정 활동으로, 예를 들어 코드 푸시, 풀 리퀘스트 생성 등이 있다.
    
- **잡(Job)**: 워크플로 내에서 실행되는 작업 단위로, 여러 스텝(Step)으로 구성되며, 각 잡은 독립적인 가상 환경에서 실행된다.
    
- **스텝(Step)**: 잡 내에서 순차적으로 실행되는 개별 작업으로, 셸 스크립트나 액션(Action)을 실행한다.
    
- **액션(Action)**: 자주 사용되는 작업을 재사용 가능하게 만든 코드 조각으로, GitHub Marketplace에서 다양한 액션을 찾아 활용할 수 있다.

### GitHub Actions의 장점

- **자동화된 워크플로**: 코드 푸시, 풀 리퀘스트 등 다양한 이벤트에 반응하여 자동으로 작업을 수행한다.
    
- **다양한 환경 지원**: Linux, macOS, Windows 등 다양한 운영체제에서 워크플로를 실행할 수 있다.
    
- **커뮤니티 액션 활용**: GitHub Marketplace에서 제공되는 다양한 액션을 활용하여 워크플로를 손쉽게 구성할 수 있다.
    

### 사용 예시

예를 들어, 코드가 푸시될 때마다 자동으로 빌드하고 테스트를 실행하는 워크플로를 설정할 수 있다.

```yaml
name: CI Pipeline
on:
  push:
    branches:
      - main
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
      - name: Set up Node.js
        uses: actions/setup-node@v3
        with:
          node-version: '14'
      - name: Install dependencies
        run: npm install
      - name: Run tests
        run: npm test

```
이러한 설정을 통해 코드 변경 시 자동으로 빌드와 테스트가 수행되어 개발 효율성과 코드 품질을 향상시킬 수 있다.

GitHub Actions를 활용하면 GCP에 종속되지 않고도 효율적인 CI/CD 파이프라인을 구축하여 개발 및 배포 프로세스를 자동화할 수 있다.


## 서버에서 코드를 서버에서 docker build 방식 vs docker pull/push 사용 방식

### 1. 코드를 서버에서 docker build 실행

애플리케이션 **소스 코드와 도커 관련 파일**(예: Dockerfile, docker-compose.yaml, .env 등)을 서버로 직접 복사한 뒤, 서버에서 도커 이미지를 빌드하고 컨테이너를 실행한다.
  

#### 특징
• **코드를 직접 서버로 복사**
• 서버에서 매번 새로 docker build를 실행
• **간단하고 직관적**이지만, 다음과 같은 단점:
1. 서버마다 코드 복사와 빌드 과정이 필요
2. 빌드 환경에 따라 빌드 결과가 달라질 수 있다
3. 민감한 정보(.env, 소스 코드 등)가 서버에 노출될 위험이 있다
4. 동일한 이미지를 여러 서버에 배포할 때 비효율적일 수 있다


### 2. Docker Push/Pull 방식

**로컬 또는 CI/CD 서버**에서 Docker 이미지를 빌드한 뒤, 이미지를 컨테이너 레지스트리(Docker Hub, GCP Artifact Registry 등)에 푸시한다. 서버는 이미지를 푸시한 레지스트리에서 docker pull로 내려받아 컨테이너를 실행한다.


#### 특징
• **코드를 서버로 복사하지 않고**, 빌드된 이미지만 서버에서 내려받아 사용
• 빌드와 배포가 분리되어 있어 **일관된 빌드 환경**을 보장
• **이미지 푸시/풀 과정**이 필요하므로 네트워크 트래픽이 발생할 수 있지만, 여러 서버에 동일한 이미지를 배포할 때 효율적이다


### 차이점 비교

|**항목**|**서버에서 `docker build`**|**Docker Push/Pull**|
|---|---|---|
|**소스 코드 복사**|서버로 직접 복사|서버로 복사하지 않음|
|**빌드 위치**|서버에서 빌드|로컬 또는 CI/CD 서버에서 빌드|
|**배포 효율성**|서버마다 별도로 빌드 필요|레지스트리에 이미지를 저장 후 여러 서버에서 `pull`|
|**일관성**|서버 환경에 따라 빌드 결과 달라질 수 있음|동일한 이미지를 사용하므로 일관성 보장|
|**민감 정보 관리**|코드와 `.env` 파일이 서버에 노출될 가능성 있음|`.env` 파일은 서버에서만 관리|
|**복잡도**|단순함|약간의 초기 설정 필요 (레지스트리 연결 등)|
|**네트워크 사용**|코드 업로드 (소량)|이미지 푸시/풀 (대량)|

> 나는 사실 1번 방법을 수동으로 주로 사용하고 있었으나, 2번 방법을 Github Actions CI/CD로 사용하고자 한다


##  테스트: Github Action을 이용한 CI/CD 적용 sample test


참고 자료: [https://docs.github.com/en/actions/about-github-actions/understanding-github-actions](https://docs.github.com/en/actions/about-github-actions/understanding-github-actions) 


### Sample Workflow Test


Github Documentation 제공 기본 `github-actions-demo.yml`. `.github/workflows/` 위치에 저장해야 한다


```bash
mkdir -p .github/workflows/
```

```yaml
name: GitHub Actions Demo
run-name: ${{ github.actor }} is testing out GitHub Actions 🚀
on: [push]
jobs:
  Explore-GitHub-Actions:
    runs-on: ubuntu-latest
    steps:
      - run: echo "🎉 The job was automatically triggered by a ${{ github.event_name }} event."
      - run: echo "🐧 This job is now running on a ${{ runner.os }} server hosted by GitHub!"
      - run: echo "🔎 The name of your branch is ${{ github.ref }} and your repository is ${{ github.repository }}."
      - name: Check out repository code
        uses: actions/checkout@v4
      - run: echo "💡 The ${{ github.repository }} repository has been cloned to the runner."
      - run: echo "🖥️ The workflow is now ready to test your code on the runner."
      - name: List files in the repository
        run: |
          ls ${{ github.workspace }}
      - run: echo "🍏 This job's status is ${{ job.status }}."

```


![](https://i.imgur.com/Hek3ndh.png)

Github에 push 시 아래와 같이 Github Action이 동작한다는것을 확인할 수 있다.


![](https://i.imgur.com/0ijXeL7.png)
![](https://i.imgur.com/tij8pdJ.png)
![](https://i.imgur.com/95M2ztm.png)




