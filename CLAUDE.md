# syshin0116.dev — AI 작업 가이드

이 문서는 **Routine 또는 Claude Code 세션이 이 레포에서 작업할 때**의 규칙을 정의한다.

이 레포는 개인 블로그(`https://syshin0116.vercel.app`)이며, 현재 **Routine 실험용**으로 사용된다:

- 기존 블로그 글들을 **원본 자료(raw)** 로 취급
- Routine이 자동으로 **`content/wiki/`에 정제된 지식 페이지** 생성
- 글들 사이에 wikilink, 백링크, 태그 정합성 보강

---

## 레포 구조

```
content/
├── AI/, Dev/, Events/, Others/, Projects/, Study/, Tools/   ← 기존 블로그 글 (원본/입력)
└── wiki/                                                     ← Routine 출력 (지식 레이어)
agent/    Python RAG 챗봇 (수정 금지)
web/      Next.js + Nuartz 프론트엔드 (수정 금지)
```

## 핵심 규칙

### 절대 금지

- **`content/wiki/` 외 다른 .md 수정 금지** — 기존 블로그 글은 원본. 읽기만 가능.
- **`web/`, `agent/` 수정 금지** — 인프라/애플리케이션 코드.
- **빌드 산출물 커밋 금지** — `.next/`, `node_modules/`, `.generated/` 등.

### 무조건 해야 할 것

- 변경 사항은 **`content/wiki/`에만 쓴다**.
- frontmatter는 아래 [Frontmatter 규칙](#frontmatter-규칙) 따른다.
- 위키 페이지 간 연결은 `[[wikilink]]`, 출처 추적은 `sources` frontmatter.
- 새 wiki 페이지 만들 때 기존 wiki 페이지와 cross-link 추가.

---

## Routine 작업: blog → wiki/ 변환

### 트리거

- 초기: **수동 트리거** (API)
- 검증 후: `main` push 트리거 (단, `content/wiki/` 외 변경분만 대상)

### 작업 순서

1. **변경 감지**

   ```bash
   # 1) Routine 자체 커밋이면 스킵 (무한 루프 방지)
   if git log -1 --format=%s | grep -q "^routine:"; then
     echo "Routine 자체 커밋 — 스킵"
     exit 0
   fi

   # 2) 마지막 routine 커밋 찾기 (없으면 최초 커밋)
   LAST=$(git log --grep "^routine:" -1 --format=%H 2>/dev/null)
   [ -z "$LAST" ] && LAST=$(git rev-list --max-parents=0 HEAD)

   # 3) 변경된 블로그 글 추출 (wiki/ 제외)
   git diff --name-status "$LAST" HEAD -- 'content/*.md' ':(exclude)content/wiki/'
   ```

   - `A`(added), `M`(modified), `D`(deleted), `R`(renamed)으로 분류
   - 변경 없으면 종료
   - **수동 트리거의 경우** 프롬프트에 명시된 범위(예: "최근 N개")만 처리

2. **컨텍스트 수집**
   - 처리 대상 블로그 글 전체 읽기
   - 기존 `content/wiki/` 페이지 목록 + 각 페이지의 `sources` frontmatter 확인
   - 같은 주제 다루는 wiki 페이지가 있는지 판단

3. **변환 결정**

   | 상황 | 동작 |
   |------|------|
   | 새로운 주제의 글 | 새 wiki 페이지 생성 |
   | 기존 wiki 주제와 겹치는 글 | 기존 wiki 페이지 업데이트 (sources에 새 글 추가) |
   | 단편적 메모, 위키화 가치 낮음 | 스킵 (로그만 남김) |
   | 한 글에 여러 주제가 섞임 | 주제별로 wiki 페이지 분할 가능 |

4. **wiki 페이지 작성**
   - **추출 위주, 창작 금지** — 원본 블로그 글에 있는 내용만 사용
   - 정제된 형태로 작성: 군더더기 제거, 명료한 구조
   - 코드/명령어는 코드블록 (원본 그대로 인용)
   - 관련 wiki 페이지에 `[[wikilink]]` 걸기
   - frontmatter 완성 ([아래 규칙](#frontmatter-규칙))

5. **기존 wiki 페이지 cross-link 보강**
   - 새/업데이트된 wiki 페이지를 가리킬 만한 기존 페이지가 있으면 `[[wikilink]]` 추가
   - 단, 본문 흐름이 자연스러운 위치에만 (억지 링크 금지)

6. **커밋 & push**
   - 커밋 메시지: `routine: wiki 정제 — <요약>`
   - 직접 default branch(`main`)에 push

### 변환 품질 기준

좋은 wiki 페이지:
- 한 페이지에 한 주제 (개념, 방법론, 도구 등)
- 자기 완결적 (다른 페이지 안 봐도 이해 가능)
- 200~600자 내외 (너무 짧거나 길지 않게)
- 코드/명령어는 원본에서 그대로 인용 (창작/추측 금지)
- 원본에 없는 내용은 추가하지 않음

피해야 할 것:
- 원본 블로그 글 통째로 복붙
- "TODO", "정리 필요" 같은 미완성 표현
- 출처 없는 일반론
- 같은 내용 여러 페이지에 중복

---

## Frontmatter 규칙

### `wiki/` 페이지

```yaml
---
title: "주제 제목"
tags:
  - <기존 블로그 태그 vocabulary 유지>
sources:
  - content/AI/2026-04-19-LLM-Text-to-SQL-실전-가이드.md
  - content/Tools/2024-07-29-Zettelkasten.md
created: YYYY-MM-DD
updated: YYYY-MM-DD
author: routine
draft: false
---
```

- `title`: 한국어/영어 모두 OK, 짧고 검색 친화적
- `tags`: 아래 [태그 규칙](#태그-규칙) 따름
- `sources`: 출처 블로그 글 경로(들). 여러 글이 한 wiki를 보강하면 모두 나열
- `created`: 페이지 최초 생성일 (변경 금지)
- `updated`: 마지막 갱신일 (Routine이 매번 갱신)
- `author`: Routine이 만든 건 항상 `routine`
- `draft`: 기본 `false`

### 기존 블로그 글 (참고용 — 수정 금지)

기존 글은 폴더(AI, Dev, Tools 등)로 분류되어 있고 frontmatter가 다양함. **건드리지 않는다.**

---

## 태그 규칙

기존 블로그 태그 vocabulary를 우선 사용하고, 비슷한 태그는 통합.

흔히 쓰이는 것:
- `ai`, `llm`, `rag`, `langchain`, `langgraph`
- `python`, `typescript`, `nextjs`, `react`
- `obsidian`, `note-taking`, `pkm`, `zettelkasten`
- `docker`, `git`, `github`
- `pdf-parser`, `text-to-sql`

새 태그 만들기 전에 비슷한 게 있는지 grep으로 확인. 1개 페이지당 1~5개 사이.

---

## sources vs wikilink

| | 위치 | 가리키는 대상 | 목적 |
|---|---|---|---|
| `sources` | frontmatter | 블로그 글 (`content/AI/...`, `content/Tools/...`) | 출처 추적, 업데이트 전파 |
| `[[wikilink]]` | 본문 | wiki 페이지 (확장자 없는 슬러그) | 개념적 연결 |

**규칙**:
- 본문 wikilink는 `wiki/` 페이지만 가리킨다.
- 원본 블로그 글을 본문 wikilink로 걸지 않는다 (sources에만).
- 새 wiki 페이지는 자신을 가리킬 만한 기존 wiki 페이지 1~3개에 백링크가 생기도록 노력.

---

## 파일명 규칙

`wiki/` 파일명: 소문자 + 하이픈. 한글 OK.

좋음: `zettelkasten.md`, `pdf-파서-비교.md`, `text-to-sql-패턴.md`
나쁨: `Zettelkasten Method.md`, `pdf_parser.md`

---

## 빌드/배포는 건드리지 않음

- `web/`, `agent/`, `vercel.json`, `package.json`, `next.config.ts` 등은 사람이 관리
- Routine은 `content/wiki/` 외 다른 디렉토리 수정하지 않음
- Vercel은 push 자동 감지하므로 별도 트리거 불필요
