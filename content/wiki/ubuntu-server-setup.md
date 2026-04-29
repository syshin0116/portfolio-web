---
title: "Ubuntu 서버 초기 설정"
type: reference
tags:
  - ubuntu
  - server
  - devops
  - docker
  - bash
  - infrastructure
  - setup
  - python
summary: "Ubuntu 서버를 새로 받을 때 필수 패키지를 한 번에 설치하는 bash 스크립트다. build-essential, git, curl, tmux 등 기본 도구와 함께 Python용 uv, Docker CE(공식 레포지토리 경유)를 설치하고 사용자를 docker 그룹에 추가한다."
sources:
  - content/Tools/Ubuntu-Server-Setup.md
created: 2026-04-26
updated: 2026-04-26
author: wiki-curator
draft: false
---

## Key Claims

- 스크립트는 Ubuntu(Debian 계열) 전용이며 `sudo` 권한이 필요하다.[^1]
- 기본 도구 설치: `build-essential`, `git`, `curl`, `wget`, `unzip`, `vim`, `htop`, `net-tools`, `lsof`, `tmux`.[^1]
- Python 패키지 관리자로 `uv`를 사용한다. `pyenv + pip`의 대체재로 속도가 빠르다.[^1]
- Docker는 Ubuntu 기본 저장소의 `docker.io`가 아닌 **Docker 공식 apt 저장소**에서 설치해야 최신 버전을 받는다.[^1]
- Docker 설치 후 `sudo usermod -aG docker $USER`로 사용자를 docker 그룹에 추가해야 sudo 없이 docker 사용 가능. 재로그인 필요.[^1]

## Examples / Code

전체 설치 스크립트:

```bash
#!/bin/bash
set -e

sudo apt update && sudo apt upgrade -y

sudo apt install -y \
    build-essential git curl wget unzip vim htop net-tools lsof tmux

# UV (Python 패키지 관리자)
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env

# 기존 Docker 패키지 제거
for pkg in docker.io docker-doc docker-compose docker-compose-v2 podman-docker containerd runc; do
    sudo apt-get remove -y $pkg 2>/dev/null || true
done

# Docker 공식 버전 설치
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
$(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" | \
sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

sudo usermod -aG docker $USER
```

주요 패키지 용도:

| 패키지 | 설명 |
|--------|------|
| `tmux` | 터미널 세션 유지 (SSH 끊겨도 프로세스 유지) |
| `lsof` | 포트 사용 확인 (`lsof -i :8080`) |
| `htop` | CPU/메모리 실시간 모니터링 |
| `uv` | Python 패키지/버전 관리 (pyenv+pip 대체) |
| `docker-compose-plugin` | Docker Compose V2 (`docker compose` 명령) |

## Connections

- [[docker]] - Docker CE 설치와 컨테이너 기초 개념

## Footnotes

[^1]: content/Tools/Ubuntu-Server-Setup.md
