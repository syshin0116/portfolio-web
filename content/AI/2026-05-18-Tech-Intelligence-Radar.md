---
title: "변화가 너무 빠른 시대의 기술 정보 레이더"
date: 2026-05-18
tags:
  - AI
  - GitHub
  - Open-Source
  - Research
  - News
  - Automation
  - Knowledge-Management
  - Workflow
  - Events
  - Hackathon
draft: false
enableToc: true
description: 레포, 논문, 뉴스, 블로그, 소셜 신호와 공모전/해커톤/설명회 같은 기회 정보를 자동으로 수집하고 계속 업데이트되는 지식으로 관리하기 위한 기술 정보 레이더 설계안.
summary: "기술 변화가 가속화되면서 사람이 모든 레포, 논문, 뉴스, changelog와 기회성 이벤트를 직접 따라가기는 어렵다. 이 글은 GitHub, 논문, 뉴스, 블로그, 소셜 신호, 공모전/해커톤/설명회를 별도 intelligence feed로 수집하고, 변화 감지와 재평가를 통해 필요한 내용만 지식으로 승격하는 구조를 설명한다."
published: 2026-05-18
modified: 2026-05-20
---

## 문제: 정보가 많아진 게 아니라, 변화 속도가 빨라졌다

요즘 기술 정보를 따라가는 일이 어려운 이유는 단순히 “볼 것이 많아서”가 아니다. 더 큰 문제는 **좋은 정보의 상태가 계속 바뀐다**는 점이다.

새로운 레포가 매일 나오고, 논문은 arXiv와 Hugging Face Papers에 계속 올라오고, GeekNews나 Hacker News에는 새로운 도구와 사례가 쌓인다. 그런데 여기에 더해 이미 알고 있던 레포, 모델, 프레임워크, 방법론도 계속 변한다.

예를 들어 GPT-3.5는 한때 가장 인상적인 범용 모델 중 하나였고, 많은 제품과 워크플로우의 기준점이었다. 하지만 지금 같은 속도의 AI 생태계에서는 “한때 최고였던 것”이 금방 기본값이 되거나, 더 이상 선택지의 중심이 아니게 된다. 레포도 마찬가지다. 작년에 좋아 보였던 프레임워크가 지금은 유지보수가 느릴 수 있고, 반대로 예전에는 실험적이던 프로젝트가 최근 changelog와 production 사례를 통해 도입 후보가 될 수 있다.

그래서 필요한 것은 단순한 북마크나 링크 모음이 아니다. 필요한 것은 다음 질문에 계속 답하는 시스템이다.

- 새로 나온 것 중 볼 만한 것은 무엇인가?
- 이미 알고 있던 것 중 의미 있게 변한 것은 무엇인가?
- 예전에 중요했던 정보가 지금도 유효한가?
- 사용자에게 공유할 만한 정보는 무엇인가?
- 장기 지식으로 승격해야 할 것은 무엇인가?
- 반대로 stale knowledge로 내려야 할 것은 무엇인가?

나는 이 구조를 **기술 정보 레이더(Technical Intelligence Radar)**라고 부르고 싶다.

> 관련 위키 노트: [[tech-intelligence-radar]]

---

## 레포만의 문제가 아니다

처음에는 GitHub 레포 watchlist를 떠올리기 쉽다. 하지만 실제로는 레포만 보면 부족하다. 기술 판단에 영향을 주는 정보는 여러 종류다.

| 정보 종류 | 예시 | 봐야 하는 이유 |
|---|---|---|
| 레포 | GitHub projects, frameworks, libraries | 실제 구현체와 adoption 가능성 확인 |
| Changelog / release note | breaking change, migration guide, new examples | 기존 도구가 어떻게 성숙하거나 망가지는지 확인 |
| 논문 | arXiv, HF Papers, Papers with Code | 새로운 아이디어와 벤치마크 흐름 파악 |
| 뉴스/커뮤니티 | GeekNews, HN, Reddit, Discord | 실무자 반응과 초기 adoption signal 확인 |
| 블로그/RSS | maintainer blog, company engineering blog | 도구의 의도, roadmap, 실제 운영 사례 확인 |
| 공모전/해커톤/설명회 | AI hackathon, 공공데이터 공모전, 웨비나, 지원사업 공고 | 기술이 적용되는 문제 영역과 당장 실행 가능한 기회 확인 |
| 소셜 | Threads, LinkedIn, X | 실무자의 짧은 사용 후기, 논쟁, 확산 속도 확인 |
| 내부 실험 | spike note, PR, ADR, 회고 | 나 또는 팀에게 실제로 유효했는지 확인 |

즉 이 시스템은 “레포 트래커”가 아니라 **기술 정보 트래커**에 가깝다. GitHub는 중요한 source 중 하나일 뿐이다.

---

## 전체 구조

기술 정보 레이더는 크게 네 단계로 나눌 수 있다.

1. 여러 source에서 signal을 모은다.
2. source 종류와 상관없이 공통 형태로 정규화한다.
3. 이전 상태와 비교해 의미 있는 변화와 stale 정보를 찾는다.
4. 사용자에게 digest와 action queue로 제공하고, 필요한 항목만 지식으로 승격한다.

![[tech-intelligence-radar-architecture.svg]]

핵심은 “더 많이 보여주기”가 아니다. 사람이 직접 모든 정보를 찾아내기 어려워졌기 때문에, 시스템이 먼저 넓게 보고 의미 있는 변화만 좁혀줘야 한다.

---

## Intelligence feed와 Knowledge base를 분리해야 한다

이 시스템은 당연히 지식화와 연결된다. 하지만 모든 정보를 바로 지식 위키에 넣으면 안 된다. 정보의 수명이 다르기 때문이다.

| Layer | 역할 | 수명 | 예시 |
|---|---|---:|---|
| Raw signals | 외부에서 들어온 원본 신호 | 짧음 | HN 글, 새 release, 논문 링크, LinkedIn post, 해커톤 공고 |
| Intelligence feed | 사용자에게 보여줄 요약/추천 | 짧음~중간 | 오늘의 alert, 주간 digest, 이번 주 spike 후보, D-day 이벤트 |
| Action queue | 실제 판단과 실험으로 이어지는 목록 | 중간 | spike, adopt 검토, reference note, 지원/참석 검토 |
| Knowledge base | 검증된 장기 지식 | 김 | pattern, comparison, playbook, ADR, 실험 결과, 반복되는 시장/정책 신호 |

대부분의 signal은 digest에서 소비되고 사라져도 된다. 특히 공모전, 해커톤, 설명회, 웨비나 같은 기회성 정보는 매일 보는 alert에는 포함하되, 원문 전체를 장기 지식으로 넣지는 않는 편이 좋다. 이런 정보는 deadline과 action이 핵심이기 때문에 intelligence feed와 action queue에서 처리하고, 지식으로 승격하는 기준은 훨씬 엄격해야 한다.

- 여러 source에서 반복적으로 등장한다.
- 실제 spike/adopt/reference 결과가 생겼다.
- 내부 프로젝트의 설계, 도구 선택, 운영 방식에 영향을 줬다.
- 나중에 다시 설명하거나 의사결정 근거로 써야 한다.
- 단순 뉴스가 아니라 reusable pattern, comparison, playbook이 됐다.
- 기존 지식을 업데이트하거나 폐기해야 할 근거가 된다.

여기서 중요한 챌린지는 “지식을 만드는 것”보다 **이미 만들어진 지식을 계속 업데이트하는 것**이다. GPT-3.5가 한때는 훌륭한 기준점이었지만 지금은 그렇지 않은 것처럼, 기술 지식에는 유효기간과 재평가 주기가 필요하다.

---

## 핵심 챌린지: Knowledge decay

기술 지식은 시간이 지나면 낡는다. 더 정확히 말하면, 처음에는 맞았던 지식이 환경 변화 때문에 덜 맞게 된다.

예를 들면 다음과 같다.

| 예전에는 맞았던 판단 | 시간이 지나며 생기는 문제 |
|---|---|
| “GPT-3.5가 비용/성능의 좋은 기본값이다” | 더 싸고 강한 모델이 나오면 기본값이 바뀜 |
| “이 agent framework는 아직 실험적이다” | release와 examples가 늘며 production 후보가 될 수 있음 |
| “이 논문은 구현체가 없어 참고용이다” | 몇 주 뒤 오픈소스 구현체가 나오면 spike 후보가 됨 |
| “이 라이브러리는 star가 많다” | 유지보수가 멈추면 adoption risk가 커짐 |
| “이 방법론은 SOTA다” | benchmark가 갱신되면 더 이상 SOTA가 아님 |

그래서 기술 정보 레이더에는 `created_at`보다 `last_verified_at`, `valid_until`, `superseded_by`, `confidence` 같은 필드가 중요하다. 지식은 저장하는 순간 끝나는 것이 아니라, 시간이 지나며 계속 재검증되어야 한다.

---

## 무엇을 수집할 것인가

Source별로 수집 방식과 의미가 다르다. 여기서 중요한 원칙은 **링크를 항상 원본 신호와 함께 저장한다**는 점이다. 요약만 남기면 나중에 왜 그렇게 판단했는지 되짚을 수 없고, 사용자가 “이건 왜 중요하다고 봤어?”라고 피드백할 때 근거를 확인하기 어렵다.

| Source | 수집할 것 | 의미 |
|---|---|---|
| GitHub repo | repo URL, stars, forks, commit, issue/PR, license, topics | 프로젝트의 현재 상태 |
| GitHub release/changelog | release/changelog URL, release body, breaking change, migration guide, security fix | 기존 도구의 변화 방향 |
| GitHub Trending | repo URL, language/topic, star delta | 새 후보 발견 |
| arXiv / HF Papers | paper URL, 제목, abstract, authors, topic, implementation link | 새로운 아이디어와 benchmark 흐름 |
| GeekNews / HN | 원문 URL, discussion URL, 댓글 수, upvote, 토론 맥락 | 실무자 관심과 adoption signal |
| Blogs/RSS | post URL, maintainer/company posts | roadmap, 의도, 사례 |
| Events/Opportunities | event URL, deadline, organizer, eligibility, benefit | deadline이 있는 실행 기회와 시장 수요 신호 |
| Threads/LinkedIn/X | post URL, author, 짧은 사용 후기, 논쟁, 확산 | 빠른 신호. 단, noise 큼 |
| 내부 기록 | PR/ADR/spike note URL, 결론, 후속 액션 | 내 맥락에서 검증된 지식 |

수집 데이터에는 최소한 `title`, `url`, `source`, `first_seen_at`, `last_seen_at`, `raw_excerpt`, `summary`, `why_it_matters`, `next_action`이 있어야 한다. `summary`는 최종 산출물이 아니라 피드백을 받기 위한 압축 표현이다. 그래서 digest에서는 모든 항목을 똑같이 나열하지 말고, 중요한 항목과 나머지 항목을 나눠 보여줘야 한다.

```markdown
## 중요하게 볼 것
1. owner/repo — release에 migration guide와 breaking change가 같이 포함됨
   - 링크: https://github.com/owner/repo/releases/tag/v1.0.0
   - 왜 중요함: 기존 사용자는 업그레이드 리스크가 있고, 새 사용자는 API 안정화 신호로 볼 수 있음
   - 추천: 1시간 spike

## 나머지 수집 항목
- Paper A — 새 benchmark 제안. 구현체는 아직 없음. 링크: ...
- Blog B — maintainer roadmap 언급. 당장 액션은 없음. 링크: ...
- Event C — 접수 마감 D-14. 관심 낮음. 링크: ...
```

이렇게 해야 사용자가 “이건 중요하지 않다”, “이 source는 계속 봐야 한다”, “이런 건 spike 후보로 올려달라”처럼 지속적으로 피드백할 수 있다. 피드백은 다음 digest의 scoring과 source 우선순위에 반영한다.

GitHub REST API는 repository, release, activity/events를 가져오는 공식 endpoint를 제공한다. arXiv도 API를 통해 논문 metadata를 가져올 수 있고, Hacker News는 공식 API와 Algolia Search API가 있다. SQLite는 이런 snapshot과 diff를 저장하기 위한 작은 로컬 DB로 적합하다.

참고:

- GitHub REST API: https://docs.github.com/en/rest
- GitHub Releases API: https://docs.github.com/en/rest/releases
- arXiv API: https://info.arxiv.org/help/api/user-manual.html
- Hacker News API: https://github.com/HackerNews/API
- HN Algolia API: https://hn.algolia.com/api
- SQLite: https://sqlite.org/about.html

---

## 왜 SQLite인가

처음에는 YAML 파일이나 Markdown table로도 시작할 수 있다. 하지만 이 문제는 시간이 지나면 “목록 관리”가 아니라 “변화 이력 관리”가 된다. 그래서 SQLite가 좋은 기본값이다.

SQLite 공식 설명처럼 SQLite는 self-contained, serverless, zero-configuration, transactional SQL database engine이다. 즉 별도 서버를 띄우지 않고 파일 하나로 시작할 수 있으면서도 SQL query와 transaction을 쓸 수 있다.

이 프로젝트에서 SQLite를 고르는 이유는 다음과 같다.

| 요구사항 | YAML/Markdown | SQLite |
|---|---|---|
| 사람이 읽기 쉬움 | 좋음 | 보통 |
| 자동 수집 결과를 계속 append | 불편 | 좋음 |
| 이전 snapshot과 비교 | 어렵거나 스크립트 복잡 | SQL로 쉬움 |
| 여러 source dedupe | 수동 관리 필요 | unique key/index 가능 |
| “30일간 star 증가량” 같은 계산 | 별도 파싱 필요 | query로 가능 |
| daily/weekly digest 생성 | 가능하지만 누적될수록 불편 | 좋음 |
| 나중에 dashboard/API로 확장 | 어려움 | 쉬움 |

YAML은 설정 파일에는 좋다. 예를 들어 “내가 추적하고 싶은 source 목록”은 YAML이 적합하다.

```yaml
sources:
  github_repos:
    - openai/codex
    - langchain-ai/langgraph
  topics:
    - agent
    - rag
    - eval
  feeds:
    - https://news.hada.io/rss
```

하지만 수집된 데이터 자체는 SQLite에 넣는 편이 낫다. 왜냐하면 중요한 것은 현재 값 하나가 아니라 **시간에 따른 변화**이기 때문이다.

---

## 스키마는 왜 이렇게 나눠야 하는가

처음 보여준 YAML이 헷갈릴 수 있다. 더 중요한 것은 “필드가 무엇이냐”가 아니라 **왜 그런 구조가 필요한가**다.

이 시스템에는 적어도 네 종류의 데이터가 있다.

1. source: 어디서 온 정보인가?
2. item: 무엇에 대한 정보인가? 레포, 논문, 뉴스, 블로그 글 등
3. observation: 특정 시점에 관측한 값은 무엇인가?
4. assessment: 사람이 또는 LLM이 해석한 의미와 다음 액션은 무엇인가?

이 네 가지를 섞어두면 나중에 업데이트가 어려워진다. 예를 들어 “LangGraph”라는 item은 하나지만, 관측값은 매일 바뀐다. 오늘의 star 수, 이번 주 release, 다음 달 changelog는 모두 다른 observation이다. 반면 “우리 프로젝트에 쓸 만하다”는 assessment는 관측값이 아니라 해석이다.

그래서 SQLite 스키마는 이런 방향이 좋다.

```sql
-- 어디서 온 정보인가
CREATE TABLE sources (
  id INTEGER PRIMARY KEY,
  type TEXT NOT NULL,              -- github, arxiv, news, blog, social, event, internal
  name TEXT NOT NULL,
  url TEXT,
  fetch_frequency TEXT,            -- daily, weekly, manual
  enabled INTEGER DEFAULT 1
);

-- 추적 대상: repo, paper, article, model, framework 등
CREATE TABLE items (
  id INTEGER PRIMARY KEY,
  source_id INTEGER,
  item_type TEXT NOT NULL,         -- repo, paper, news, blog_post, social_post, event, model
  canonical_id TEXT NOT NULL,      -- owner/repo, arxiv_id, url hash 등
  title TEXT NOT NULL,
  url TEXT,
  first_seen_at TEXT,
  last_seen_at TEXT,
  UNIQUE(item_type, canonical_id)
);

-- 시간에 따라 바뀌는 관측값
CREATE TABLE observations (
  id INTEGER PRIMARY KEY,
  item_id INTEGER NOT NULL,
  observed_at TEXT NOT NULL,
  metric_name TEXT NOT NULL,       -- stars, latest_release, comments, citations, etc.
  metric_value TEXT,
  raw_json TEXT
);

-- release/changelog처럼 별도 해석이 필요한 변화 이벤트
CREATE TABLE change_events (
  id INTEGER PRIMARY KEY,
  item_id INTEGER NOT NULL,
  event_type TEXT NOT NULL,        -- release, changelog, paper_update, news_mention, opportunity
  event_at TEXT,
  title TEXT,
  body TEXT,
  summary TEXT,
  has_breaking_change INTEGER DEFAULT 0,
  has_security_fix INTEGER DEFAULT 0,
  has_new_examples INTEGER DEFAULT 0
);

-- 의미 판단과 다음 행동
CREATE TABLE assessments (
  id INTEGER PRIMARY KEY,
  item_id INTEGER NOT NULL,
  assessed_at TEXT NOT NULL,
  relevance TEXT,                  -- high, medium, low
  confidence TEXT,                 -- high, medium, low
  status TEXT,                     -- watch, rising, stale, superseded, try-soon, adopted, ignored
  next_action TEXT,                -- spike, adopt, reference, monitor, apply, attend, ignore, promote_to_knowledge
  rationale TEXT,
  valid_until TEXT,
  superseded_by TEXT
);
```

이렇게 나누는 이유는 단순하다.

- `items`는 “대상”이다. LangGraph, 특정 논문, 특정 뉴스 글, 특정 해커톤 같은 것.
- `observations`는 “시간에 따른 숫자/상태”다. star 수, 댓글 수, 최신 release 같은 것.
- `change_events`는 “변화 사건”이다. release, changelog, 논문 업데이트, 큰 뉴스 언급, 새 공모전/설명회 공지 같은 것.
- `assessments`는 “해석”이다. 지금도 유효한가, 써볼 것인가, 지식으로 승격할 것인가.

이 분리를 해두면 “예전에는 맞았지만 지금은 아닌 지식”을 다룰 수 있다. 예를 들어 어떤 모델이나 프레임워크의 status를 `adopted`에서 `stale` 또는 `superseded`로 바꿀 수 있고, 그 이유를 `rationale`에 남길 수 있다.

---

## Scoring은 순위를 정하려는 게 아니라 업데이트 대상을 고르려는 것

점수화는 “무엇이 최고인가”를 정하려는 목적이 아니다. 더 중요한 목적은 **무엇을 다시 봐야 하는가**를 고르는 것이다.

![[tech-intelligence-radar-scoring.svg]]

추천하는 판단 축은 다음과 같다.

| Dimension | 질문 |
|---|---|
| Relevance | 내 관심사나 프로젝트와 연결되는가? |
| Novelty | 새로 나온 변화인가, 단순 반복인가? |
| Momentum | 관심과 활동이 증가하고 있는가? |
| Maturity delta | 문서, 예제, release, benchmark가 좋아지고 있는가? |
| Trust | maintainer, 기관, 논문, 실제 사용 사례가 신뢰할 만한가? |
| Decay risk | 예전 지식을 업데이트해야 할 정도로 변화가 큰가? |
| Actionability | 지금 spike/adopt/reference/apply/attend 중 하나로 이어질 수 있는가? |

특히 `decay risk`가 중요하다. 기술 정보 레이더는 새로운 것을 찾는 시스템이기도 하지만, **기존 지식의 유효성을 재검증하는 시스템**이기도 하다.

---

## Digest는 “많이 읽게”가 아니라 “판단하게” 만들어야 한다

매일 긴 리포트를 보내면 실패한다. 매일은 긴급 변화만, 매주는 의사결정만 보여주는 것이 좋다.

![[tech-intelligence-radar-digest.svg]]

### Daily alert

```markdown
# Daily Technical Radar

## 긴급 확인
- Framework A: security fix release
- Model B: pricing/API 정책 변경

## 의미 있는 변화
- Paper X: 공식 구현체 공개됨 → spike 후보
- Repo Y: examples와 migration guide 추가 → adoption risk 감소
- Tool Z: 90일째 release 없음 → stale 후보

## 기회/일정
- AI agent 해커톤: 접수 마감 D-5 → 지원 여부 판단
- 공공데이터 활용 공모전 설명회: 내일 진행 → 참석/녹화 확인
- LangChain webinar: Deep Agents 업데이트 설명 예정 → 참고 후보
```

### Weekly digest

```markdown
# Weekly Technical Intelligence

## 1. 이번 주 새로 볼 것
- 논문 A: benchmark 방향이 바뀔 가능성
- 레포 B: GitHub Trending + HN 토론 동시 발생

## 2. 기존 지식 업데이트 후보
- GPT-3.5 관련 기존 메모: baseline 설명 업데이트 필요
- Tool C: 예전에는 실험적이었지만 v1.0 release로 재평가 필요

## 3. 이번 주 액션
- [ ] Paper A 구현체 확인
- [ ] Repo B 1시간 spike
- [ ] Tool C 기존 wiki note 업데이트 여부 판단
- [ ] 해커톤/공모전 D-day 항목 중 지원할 것과 무시할 것 결정
```

---

## 지식으로 승격하는 순간

모든 signal이 지식이 되는 것은 아니다. 하지만 다음 조건을 만족하면 knowledge base로 승격해야 한다.

| 승격 조건 | 예시 |
|---|---|
| 반복 등장 | 여러 주 동안 같은 프레임워크가 계속 언급됨 |
| 실험 완료 | spike 결과 실제 장단점이 확인됨 |
| 의사결정 영향 | 도입/보류/대체 결정에 영향을 줌 |
| 비교 가치 | 여러 도구를 비교하는 기준이 됨 |
| 이벤트에서 나온 durable signal | 공모전 주제나 설명회 내용이 반복되는 시장 수요/정책 방향을 보여줌 |
| 기존 지식 갱신 | 예전 판단이 더 이상 맞지 않음 |

이때 지식 위키에는 단순 링크가 아니라 다음 내용이 들어가야 한다.

- 현재 판단
- 판단 근거
- 마지막 검증일
- confidence
- 언제 다시 볼지
- 무엇에 의해 supersede될 수 있는지

지식은 저장보다 업데이트가 어렵다. 그래서 처음부터 `last_verified_at`, `valid_until`, `superseded_by` 같은 개념을 넣어야 한다.

---

## 시작 로드맵

처음부터 4주짜리 프로젝트처럼 크게 설계하면 오히려 손이 안 간다. 이 레이더는 “완성된 시스템을 한 번에 만든다”보다 **작게 수집하고, 실제로 읽어보고, 피드백으로 필터를 고치는 방식**으로 시작하는 편이 낫다.

### 1. 먼저 링크 inbox를 만든다

처음 할 일은 자동화가 아니라 저장 위치를 정하는 것이다.

- GitHub repo, release, changelog, paper, blog, HN/GeekNews 글, 이벤트 페이지 URL을 모두 같은 inbox에 넣는다.
- 링크만 넣지 말고 `왜 저장했는지`를 한 줄로 적는다.
- 처음에는 “좋은 정보”만 넣으려고 하지 않는다. 나중에 버릴 수 있어야 필터가 좋아진다.

예시:

```yaml
- title: "owner/repo v1.0 release"
  url: "https://github.com/owner/repo/releases/tag/v1.0.0"
  source: github_release
  note: "migration guide가 생겨서 adoption risk 재평가 필요"
  first_seen_at: 2026-05-18
```

### 2. 하루에 한 번 중요한 것만 따로 뽑는다

수집된 링크를 전부 읽게 만들면 실패한다. 매일 볼 화면은 짧아야 한다.

```markdown
## 오늘 중요하게 볼 것
1. owner/repo
   - 링크: ...
   - 이유: security fix + breaking change
   - 추천: 기존 사용 여부 확인

## 나머지 수집 항목
- Paper A — 구현체 없음. 일단 monitor. 링크: ...
- Blog B — roadmap 참고용. 링크: ...
- Event C — D-21. 관심 낮음. 링크: ...
```

핵심은 “나머지”도 완전히 숨기지 않는 것이다. 그래야 사용자가 중요도 판단을 고쳐줄 수 있다. 계속 피드백을 받으면 어떤 source를 더 믿을지, 어떤 키워드를 낮출지, 어떤 항목을 spike 후보로 올릴지 점점 좋아진다.

### 3. SQLite는 링크가 쌓이기 시작하면 붙인다

링크가 20~30개를 넘어가면 Markdown/YAML만으로는 이전 상태와 비교하기 어려워진다. 그때 SQLite로 옮긴다.

- `sources`: 어디서 왔는가
- `items`: 무엇에 대한 정보인가
- `observations`: 특정 시점에 본 값은 무엇인가
- `change_events`: release, changelog, 새 논문, 이벤트 공지 같은 변화
- `assessments`: 그래서 지금 무엇을 할 것인가

이 순서가 자연스럽다. DB를 먼저 설계하는 것이 아니라, 실제 inbox에서 반복되는 필드가 보이면 테이블로 굳힌다.

### 4. Digest를 action queue와 연결한다

마지막으로 digest가 단순 요약에서 끝나지 않게 만든다. 각 중요 항목은 다음 중 하나로 끝나야 한다.

- `spike`: 직접 1~3시간 써본다.
- `adopt`: 도입 계획이나 ADR로 넘긴다.
- `reference`: 구조나 아이디어만 저장한다.
- `monitor`: 다음 release나 논문 구현체를 기다린다.
- `apply/attend`: 공모전, 해커톤, 설명회처럼 일정이 있는 항목을 처리한다.
- `ignore`: 왜 버리는지 짧게 남긴다.
- `promote_to_knowledge`: 반복적으로 중요해진 항목만 위키로 승격한다.

처음 버전의 목표는 “자동화된 완벽한 레이더”가 아니다. 목표는 **링크와 근거를 잃지 않으면서, 중요한 것과 나머지를 구분해 보여주고, 사용자의 피드백으로 다음 digest가 더 좋아지는 루프**를 만드는 것이다.

---

## 마무리

지금 필요한 것은 “좋은 레포 목록”이 아니다. 레포, 논문, 뉴스, 블로그, 소셜, 공모전/해커톤/설명회, 내부 실험까지 포함해서 **계속 변하는 기술 정보와 실행 기회를 추적하고 재평가하는 시스템**이다.

이 시스템의 목적은 더 많은 정보를 쌓는 것이 아니라 다음 질문에 답하는 것이다.

1. 새로 봐야 할 것은 무엇인가?
2. 기존에 알던 것 중 무엇이 변했는가?
3. 예전 지식 중 무엇이 낡았는가?
4. 이번 주에 실험하거나 공유하거나 지원/참석할 것은 무엇인가?
5. 장기 지식으로 승격하거나 업데이트할 것은 무엇인가?

기술 변화가 빨라질수록 중요한 것은 한 번의 정리가 아니라 **계속 업데이트되는 판단 구조**다.

```text
external signals → intelligence feed → action queue → knowledge promotion/update
                         ↘ event reminder / apply-attend decision
```

이렇게 나누면 정보 과부하를 줄이면서도, 필요한 지식은 계속 살아 있게 만들 수 있다.
