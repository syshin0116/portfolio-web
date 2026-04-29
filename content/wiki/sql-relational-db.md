---
title: "관계형 데이터베이스 및 SQL 기초"
type: concept
tags:
  - sql
  - database
  - relational-db
  - mysql
  - data
  - backend
  - data-science
summary: "관계형 DB는 1970년 Edgar Codd가 제안한 테이블 기반 데이터 모델로 현재 가장 널리 사용된다. 계층형 DB와 달리 복잡한 관계를 지원하며 데이터 독립성을 보장한다. MySQL 설치 및 기본 사용법도 포함한다."
sources:
  - content/Study/SeSAC/data-analysis/2023-07-20-SeSAC-SQL로 데이터베이스 다루기-1일차.md
created: 2026-04-26
updated: 2026-04-26
author: wiki-curator
draft: false
---

## Key Claims

- **DBMS**: 특정 목적을 처리하기 위해 데이터베이스를 관리하는 프로그램.[^1]
- **계층형(Hierarchical) DB**: 부모/자식 트리 구조. 빠른 데이터 추출이 장점. 복잡한 관계와 중복 데이터 처리가 단점.[^1]
- **관계형(Relational) DB**: Edgar F. Codd가 1970년 논문에서 제안. 데이터를 테이블(릴레이션)에 저장하며 레코드의 물리적 위치를 알 필요 없이 관계를 통해 데이터 접근.[^1]
- 관계형 DB 장점: (1) 내장된 다중 수준 무결성, (2) 논리적/물리적 데이터 독립성, (3) 데이터 일관성과 정확성, (4) 쉬운 데이터 추출.[^1]
- MySQL 8.0은 Homebrew로 설치 가능: `brew install mysql@8.0.34`. 워크스테이션 GUI는 MySQL Workbench 사용.[^1]
- 샘플 데이터베이스(sakila, world)는 [dev.mysql.com/doc/index-other.html](https://dev.mysql.com/doc/index-other.html)에서 다운로드 후 `.sql` 파일 실행.[^1]

## Examples / Code

MySQL 설치 및 확인:

```bash
# macOS Homebrew
brew install mysql@8.0.34

# 시작
brew services start mysql@8.0.34

# 접속
mysql -u root -p

# DB 목록 확인
SHOW DATABASES;
```

MySQL Workbench에서 .sql 파일 실행:
1. 파일 다운로드 (sakila-schema.sql, sakila-data.sql)
2. MySQL Workbench → File → Run SQL Script
3. `SHOW DATABASES;` 로 확인

## Connections

- [[llm-text-to-sql]] - LLM Text-to-SQL은 관계형 DB 스키마를 기반으로 자연어 질의를 SQL로 변환하는 패턴

## Footnotes

[^1]: content/Study/SeSAC/data-analysis/2023-07-20-SeSAC-SQL로 데이터베이스 다루기-1일차.md
