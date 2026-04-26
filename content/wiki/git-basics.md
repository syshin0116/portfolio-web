---
title: "Git / GitHub 기초"
type: reference
tags:
  - git
  - github
  - version-control
  - devops
  - cli
  - backend
summary: "Git은 Linus Torvalds가 2005년 개발한 분산형 버전 관리 시스템(DVCS)이다. GitHub는 Git 저장소를 클라우드에서 호스팅하는 서비스다. 핵심 명령어(add, commit, push, branch, merge, rebase)와 브랜치 전략을 정리한다."
sources:
  - content/Tools/Git/2022-09-08-_Github_Github정리.md
created: 2026-04-26
updated: 2026-04-26
author: wiki-curator
draft: false
---

## Key Claims

- Git: 2005년 Linus Torvalds가 개발한 분산형 버전 관리 시스템(DVCS). 파일 변경사항을 로컬에서 추적한다.[^1]
- GitHub: Git 프로젝트를 클라우드에서 호스팅하는 서비스. Git(로컬) + GitHub(원격 공유)의 조합이 표준 워크플로우다.[^1]
- `git fetch` vs `git pull`: fetch는 원격 변경사항을 가져오되 병합하지 않음. pull = fetch + merge.[^1]
- `git merge` vs `git rebase`: merge는 모든 commit을 master에 기록, rebase는 불필요한 commit을 생략하고 필요한 것만 master에 병합. `-i` 옵션으로 중간 커밋 메시지 수정 가능.[^1]
- `-u` 옵션: 최초 push 시 `git push -u origin main`으로 업스트림 설정 후, 이후 `git push`만으로 동작.[^1]
- clone vs fork: clone 또는 fork 후 commit 시 원본 레포로 merge되어야 GitHub 잔디가 심어진다. 이를 피하려면 `download zip` + 새 레포 방식을 사용.[^1]

## Examples / Code

핵심 명령어 요약:

| 명령어 | 설명 |
|--------|------|
| `git init` | 현재 디렉토리를 Git 저장소로 초기화 |
| `git add .` | 현재 디렉토리 모든 변경사항 스테이징 |
| `git add -A` | 작업 디렉토리 전체 변경사항 스테이징 |
| `git commit -m "msg"` | 스테이징 상태를 저장소에 기록 |
| `git push -u origin main` | 원격 저장소에 push (업스트림 설정) |
| `git clone <url>` | 저장소 복제 (`origin` 자동 등록) |
| `git fetch` | 원격 변경사항 가져오기 (병합 X) |
| `git pull` | fetch + merge |
| `git branch <name>` | 브랜치 생성 |
| `git checkout -b <name>` | 브랜치 생성 후 이동 |
| `git merge <branch>` | 브랜치 병합 |
| `git rebase -i <branch>` | 인터랙티브 리베이스 |

## Connections

- [[github-actions-gcp-cicd]] — GitHub Actions는 Git push 이벤트를 트리거로 하는 CI/CD 자동화 도구

## Footnotes

[^1]: content/Tools/Git/2022-09-08-_Github_Github정리.md
