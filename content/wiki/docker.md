---
title: "Docker 컨테이너 기초"
type: concept
tags:
  - docker
  - container
  - devops
  - virtualization
  - backend
  - docker-compose
  - infrastructure
summary: "Docker는 OS 커널을 공유하는 앱 수준 가상화 기술이다. VM(수 GB, 하이퍼바이저)과 달리 컨테이너는 수십 MB로 가볍고 빠르다. Docker Compose로 멀티 컨테이너를 오케스트레이션하며, 컨테이너 간 통신 시 localhost 대신 컨테이너 이름을 호스트로 사용한다."
sources:
  - content/Tools/Docker/2023-05-08-Docker와 VM 차이.md
  - content/Tools/Docker/2023-11-09-Docker-실습.md
  - content/Tools/Docker/2024-03-27-Docker Compose에서 Flask와 MySQL 연결 문제.md
created: 2026-04-26
updated: 2026-04-26
author: wiki-curator
draft: false
---

## Key Claims

- Docker는 컨테이너(코드 + 의존성 + 실행 환경 패키지)를 이용한 앱 수준 가상화 기술이다. 여러 컨테이너가 호스트 OS 커널을 공유하며 격리된 프로세스로 실행된다.[^1]
- VM vs Docker: VM은 하이퍼바이저로 전체 OS를 가상화(수 GB, 느림), Docker는 커널 공유로 앱만 격리(수십 MB, 빠름).[^1]
- Docker 이미지는 레지스트리(Docker Hub)에서 pull하거나 Dockerfile로 직접 빌드한다.[^1]
- 핵심 run 옵션: `-it`(대화형 터미널), `--ipc=host`(호스트 IPC 공유, 고성능 병렬 처리용), `-p` 포트 바인딩, `-v` 볼륨 마운트.[^2]
- Docker Compose: 여러 컨테이너를 단일 `docker-compose.yml`로 정의·실행하는 오케스트레이션 도구.[^3]
- **컨테이너 간 통신**: Docker Compose 환경에서 Flask가 MySQL에 접속할 때 호스트를 `localhost`가 아닌 **MySQL 컨테이너 이름**으로 지정해야 한다. 같은 네트워크에 있어야 한다.[^3]
- `docker network ls`로 컨테이너 네트워크 확인, `docker exec -it <name> bash`로 컨테이너 내부 접속.[^3]

## Examples / Code

기본 Docker 명령어:

```bash
# 이미지 pull 및 실행
docker pull ultralytics/ultralytics:latest
docker run -it --ipc=host docker.io/ultralytics/ultralytics:latest

# 컨테이너 관리
docker ps          # 실행 중인 컨테이너
docker ps -a       # 전체 컨테이너
docker stop <id>
docker rm <id>

# 컨테이너 내부 접속
docker exec -it <container_name> bash
```

Docker Compose Flask + MySQL 연결 패턴:

```yaml
# docker-compose.yml
services:
  db:
    image: mysql:8.0
    environment:
      MYSQL_ROOT_PASSWORD: password
      MYSQL_DATABASE: mydb
    networks:
      - app-network

  api:
    build: .
    environment:
      # 호스트를 'localhost'가 아닌 컨테이너 이름 'db'로 지정
      DB_HOST: db
      DB_PORT: 3306
    depends_on:
      - db
    networks:
      - app-network

networks:
  app-network:
```

```python
# Flask에서 MySQL 연결 (pymysql)
connection = pymysql.connect(
    host='db',        # 컨테이너 이름
    user='root',
    password='password',
    database='mydb'
)
```

## Connections

- [[github-actions-gcp-cicd]] - GitHub Actions CI/CD 파이프라인에서 Docker 이미지 빌드와 배포가 핵심 단계
- [[ubuntu-server-setup]] - 서버 초기화 스크립트에 Docker CE 설치 포함

## Footnotes

[^1]: content/Tools/Docker/2023-05-08-Docker와 VM 차이.md
[^2]: content/Tools/Docker/2023-11-09-Docker-실습.md
[^3]: content/Tools/Docker/2024-03-27-Docker Compose에서 Flask와 MySQL 연결 문제.md
