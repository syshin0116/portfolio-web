---
title: Ubuntu 서버 초기 설정 스크립트
date: 2025-01-27
tags:
- Ubuntu
- server
- setup
- script
- docker
- dev-tools
- automation
- bash
- DevOps
- infrastructure
- tools
draft: false
enableToc: true
description: Ubuntu 서버 초기 설정을 자동화하는 bash 스크립트와 설치되는 각 패키지의 상세 설명 및 사용법 가이드
summary: "Ubuntu 서버를 새로 받을 때마다 반복적으로 설치해야 하는 필수 패키지들이 귀찮아서 한 번에 설치하는 스크립트를 만들어 둔 것이다. Git, Docker, UV, 각종 개발 도구들을 자동으로 설치하고, 각 패키지가 무엇인지 간단히 정리해둔다."
published: 2025-01-27
modified: 2025-01-27
---
# Ubuntu 서버 초기 설정 스크립트

> [!warning] Ubuntu 전용 스크립트
> 이 스크립트는 **Ubuntu (Debian 계열)** 전용이다. 다른 Linux 배포판에서는 작동하지 않을 수 있다.

## 자동 설치 스크립트

```bash
#!/bin/bash

set -e

echo "🚀 Ubuntu 서버 초기 설정을 시작합니다..."

echo "📦 시스템 패키지 업데이트 중..."
sudo apt update && sudo apt upgrade -y

echo "🛠️ 기본 개발 도구 설치 중..."
sudo apt install -y \
    build-essential \
    git \
    curl \
    wget \
    unzip \
    vim \
    htop \
    net-tools \
    lsof \
    tmux

echo "🐍 UV (Python Package Manager) 설치 중..."
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env

echo "🗑️ 기존 Docker 패키지 제거 중..."
for pkg in docker.io docker-doc docker-compose docker-compose-v2 podman-docker containerd runc; do 
    sudo apt-get remove -y $pkg 2>/dev/null || true
done

echo "🐳 Docker 공식 버전 설치 중..."
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
$(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" | \
sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

echo "👥 사용자를 docker 그룹에 추가 중..."
sudo usermod -aG docker $USER

echo "✅ 설치 완료!"
echo ""
echo "📋 설치된 버전 확인:"
echo "Git: $(git --version)"
echo "UV: $(uv --version 2>/dev/null || echo 'UV 설치 완료 (재로그인 필요)')"
echo "Docker: $(docker --version)"
echo ""
echo "⚠️ Docker를 sudo 없이 사용하려면 로그아웃 후 다시 로그인하세요."
echo "🎉 Ubuntu 서버 초기 설정이 완료되었습니다!"
```

## 설치되는 패키지들

각각 어떤 용도인지 간단히 정리해둔다.

| 카테고리 | 패키지/도구 | 설명 | 용도 |
|---------|------------|------|------|
| **시스템 기본** | `build-essential` | GCC 컴파일러, make 등 기본 빌드 도구 | C/C++ 컴파일, 패키지 빌드 |
| **버전 관리** | `git` | 분산 버전 관리 시스템 | 소스코드 관리, 협업 |
| **네트워크** | `curl` | 명령줄 데이터 전송 도구 | API 호출, 파일 다운로드 |
| **네트워크** | `wget` | 파일 다운로드 도구 | 웹에서 파일 다운로드 |
| **압축** | `unzip` | ZIP 파일 압축 해제 도구 | 압축 파일 처리 |
| **편집기** | `vim` | 고급 텍스트 편집기 | 파일 편집, 설정 수정 |
| **모니터링** | `htop` | 인터랙티브 프로세스 뷰어 | 시스템 리소스 모니터링 |
| **네트워크** | `net-tools` | 네트워크 유틸리티 (ifconfig 등) | 네트워크 설정 확인 |
| **프로세스** | `lsof` | 열린 파일 목록 도구 | 포트 사용 확인, 프로세스 추적 |
| **터미널** | `tmux` | 터미널 멀티플렉서 | 세션 관리, 백그라운드 실행 |
| **Python** | `uv` | 빠른 Python 패키지 관리자 | Python 패키지 설치/관리 |
| **컨테이너** | `docker-ce` | Docker 커뮤니티 에디션 | 컨테이너 실행 |
| **컨테이너** | `docker-ce-cli` | Docker 명령줄 인터페이스 | Docker 명령어 사용 |
| **컨테이너** | `containerd.io` | 컨테이너 런타임 | 컨테이너 실행 환경 |
| **컨테이너** | `docker-buildx-plugin` | Docker 빌드 확장 | 멀티 플랫폼 이미지 빌드 |
| **컨테이너** | `docker-compose-plugin` | Docker Compose V2 | 멀티 컨테이너 앱 관리 |

## 주의사항

- **Ubuntu 전용**: 이 스크립트는 Ubuntu(Debian 계열) 전용이다
- **루트 권한**: sudo 권한이 필요하다
- **재시작**: Docker 그룹 추가 후 재로그인이 필요하다
- **인터넷 연결**: 패키지 다운로드를 위해 인터넷 연결이 필요하다

## 설치 확인 명령어

```bash
# 시스템 정보
lsb_release -a

# 설치된 도구 버전 확인
git --version
uv --version
docker --version
docker compose version

# Docker 그룹 확인
groups $USER
``` 