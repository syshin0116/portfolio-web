---
title: "GitHub Actions + GCP CI/CD 파이프라인"
type: pattern
tags:
  - github-actions
  - cicd
  - gcp
  - docker
  - devops
  - automation
  - cloud
  - backend
summary: "GitHub Actions로 코드 push 시 Docker 이미지를 빌드해 Docker Hub에 올리고, SSH로 GCP Compute Engine에 접속해 컨테이너를 재배포하는 CI/CD 파이프라인 패턴이다. GitHub Secrets로 민감 정보를 관리하며, 비용 없이 소규모 프로젝트에 적용 가능하다."
sources:
  - content/Tools/Git/2024-11-09-정리-Github CI CD - GCP.md
  - content/Tools/Git/2024-11-17-방법-Github CI CD - GCP.md
created: 2026-04-26
updated: 2026-04-26
author: wiki-curator
draft: false
---

## Key Claims

- CI(Continuous Integration): 코드 변경사항을 자동 빌드·테스트해 충돌을 조기 발견한다.[^1]
- CD(Continuous Deployment): CI를 통과한 코드를 자동으로 프로덕션에 배포한다.[^1]
- GitHub Actions는 `.github/workflows/` 디렉터리의 YAML 파일로 워크플로우를 정의하며, push/PR 등의 이벤트가 트리거다.[^2]
- 전체 파이프라인: 코드 push → Actions 실행 → Docker 이미지 빌드 → Docker Hub push → SSH로 GCP 서버 접속 → 기존 컨테이너 중지 → 신규 이미지 pull → 컨테이너 재시작.[^2]
- GCP Compute Engine 사전 준비: VM 생성, Docker + Docker Compose 설치, 필요 포트 오픈(80/443/8000/3306), SSH 키 설정.[^2]
- GitHub Secrets 필요 항목: `DOCKER_HUB_USERNAME`, `DOCKER_HUB_ACCESS_TOKEN`, `GCP_SSH_PRIVATE_KEY`, `GCP_SERVER_IP`, `GCP_USERNAME`.[^2]
- Docker Hub 이미지 보안: Private 레포지토리를 권장한다.[^2]

## Examples / Code

GitHub Actions 워크플로우 구조 (`deploy.yml`):

```yaml
name: Deploy to GCP

on:
  push:
    branches: [main]

jobs:
  build-and-deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Login to Docker Hub
        uses: docker/login-action@v2
        with:
          username: ${{ secrets.DOCKER_HUB_USERNAME }}
          password: ${{ secrets.DOCKER_HUB_ACCESS_TOKEN }}
      
      - name: Build and push Docker image
        run: |
          docker build -t ${{ secrets.DOCKER_HUB_USERNAME }}/myapp:latest .
          docker push ${{ secrets.DOCKER_HUB_USERNAME }}/myapp:latest
      
      - name: Deploy to GCP via SSH
        uses: appleboy/ssh-action@master
        with:
          host: ${{ secrets.GCP_SERVER_IP }}
          username: ${{ secrets.GCP_USERNAME }}
          key: ${{ secrets.GCP_SSH_PRIVATE_KEY }}
          script: |
            docker pull ${{ secrets.DOCKER_HUB_USERNAME }}/myapp:latest
            docker stop myapp || true
            docker rm myapp || true
            docker run -d --name myapp -p 8000:8000 \
              ${{ secrets.DOCKER_HUB_USERNAME }}/myapp:latest
```

## Connections

- [[docker]] — Docker 이미지 빌드와 컨테이너 실행이 파이프라인의 핵심

## Footnotes

[^1]: content/Tools/Git/2024-11-09-정리-Github CI CD - GCP.md
[^2]: content/Tools/Git/2024-11-17-방법-Github CI CD - GCP.md
