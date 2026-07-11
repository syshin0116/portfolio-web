---
title: "Tech intelligence radar"
type: pattern
tags:
  - github
  - open-source
  - changelog
  - research
  - automation
  - monitoring
  - pkm
  - workflow
  - ai
  - trend-tracking
summary: "Tech intelligence radar는 지식 위키 그 자체가 아니라 사용자에게 제공할 외부 정보 소스/인텔리전스 피드다. 새로 뜨는 레포와 기존 watchlist 레포의 release note, changelog, commit, issue/PR, 문서 변화를 추적해 digest와 action queue로 제공하고, 필요할 때만 검증된 insight를 지식 위키로 승격한다."
sources:
  - content/AI/2026-05-18-Tech-Intelligence-Radar.md
  - https://docs.github.com/en/rest/repos
  - https://docs.github.com/en/rest/releases
  - https://docs.github.com/en/rest/activity
  - https://github.com/trending
  - https://news.hada.io/
  - https://github.com/HackerNews/API
  - https://hn.algolia.com/api
  - https://info.arxiv.org/help/api/user-manual.html
  - https://huggingface.co/papers/trending
created: 2026-05-18
updated: 2026-07-12
author: wiki-curator
draft: false
---

## Key Claims

- Public-facing article: [기술 정보 레이더 글](../AI/2026-05-18-Tech-Intelligence-Radar.md)이 사용자에게 보여줄 설명 글이고, 이 위키 페이지는 그 글에서 재사용 가능한 운영 패턴만 정리하는 knowledge layer다.
- 정보 과부하의 원인은 “새로운 레포가 너무 많다”만이 아니다. 이미 알고 있는 레포가 release, changelog, examples, benchmark, docs를 통해 계속 변하는데 그 변화를 놓치기 때문이다.
- 그래서 watchlist는 `repo` 단위가 아니라 `repo + changelog + release + docs + community signal` 단위로 관리해야 한다.
- GitHub star 수는 발견용 신호일 뿐이다. 실제 활용 판단에는 release cadence, changelog 품질, issue/PR 반응성, docs/example 변화, 라이선스, 내부 적용 가능성이 더 중요하다.
- GeekNews, GitHub Trending, Hacker News, 최신 논문, Hugging Face Papers, Threads, LinkedIn은 모두 “입구”일 뿐이다. 최종 시스템은 정보를 더 많이 보여주는 것이 아니라 `adopt / spike / reference / ignore`로 압축해야 한다.
- Tech radar는 지식 위키와 연결되지만 같은 것이 아니다. 기본 산출물은 사용자에게 줄 수 있는 public-facing intelligence feed이고, 검증·반복·내부 적용 가치가 생긴 항목만 knowledge base로 승격한다.
- 좋은 repo radar는 매일 모든 것을 읽게 하지 않는다. 매일은 alert, 매주는 digest, 매월은 watchlist 정리로 리듬을 나눈다.

## Problem

AI, agent, RAG, eval, inference, frontend, devtool 분야는 변화 속도가 빠르다. 새 프로젝트가 계속 나오고, 기존 프로젝트도 조용히 성숙한다. GitHub star를 눌러두는 것만으로는 다음 질문에 답하기 어렵다.

- 이 레포가 지난 한 달 동안 의미 있게 좋아졌는가?
- changelog에 breaking change가 있었는가?
- 예제가 늘었는가, 문서만 바뀌었는가?
- 논문이나 커뮤니티에서 반복적으로 언급되는가?
- 우리 프로젝트에서 바로 써볼 만한가, 참고만 할 것인가?

따라서 목표는 “많이 모으기”가 아니라 **변화 감지 → 의미 판별 → 활용 액션**까지 이어지는 루프를 만드는 것이다.

## Radar architecture

_시각화는 public-facing article [기술 정보 레이더 글](../AI/2026-05-18-Tech-Intelligence-Radar.md)에 포함했다._


## Separate source, optional knowledge promotion

이 시스템은 최종적으로 지식 위키에 일부 내용이 들어갈 수 있지만, 출발점은 **지식 그 자체가 아니라 별도의 외부 정보 소스**다. Tech radar는 사용자에게 직접 줄 수 있는 트렌드/레포/논문/커뮤니티 인텔리전스 feed이고, 지식 위키는 그중 오래 남을 만한 것만 정제해서 보관하는 downstream layer다.

| Layer | Purpose | Audience | Persistence |
|---|---|---|---|
| Raw signals | GitHub, changelog, GeekNews, HN, 논문, Threads/LinkedIn 링크 수집 | 시스템/수집기 | 짧게 보관, 중복 제거 |
| Intelligence feed | “이번 주 볼 것”, “변화가 큰 레포”, “실험 후보” 제공 | 사용자/구독자 | daily/weekly digest로 발행 |
| Action queue | spike/adopt/reference/ignore 결정 | 나 또는 팀 | 처리될 때까지 유지 |
| Knowledge promotion | 반복적으로 중요하거나 내 프로젝트에 적용된 insight만 위키화 | 나중에 검색할 나/팀 | 장기 보관 |

따라서 모든 수집 항목을 지식에 넣으면 안 된다. 대부분은 digest에서 소비되고 사라져야 한다. 지식으로 승격하는 기준은 아래처럼 좁게 잡는다.

- 같은 레포/기술이 여러 주 반복해서 등장한다.
- 실제 spike/adopt/reference 결과가 생겼다.
- 내부 프로젝트의 설계, 도구 선택, 운영 방식에 영향을 줬다.
- 나중에 다시 설명하거나 의사결정 근거로 써야 한다.
- 단순 뉴스가 아니라 reusable pattern, comparison, playbook이 됐다.


## What to track

### 1. Repository metadata

기본 repo 상태는 GitHub REST API로 수집한다.[^github-repos]

| Signal | Why it matters |
|---|---|
| stars / forks / watchers | 발견과 인기도의 rough proxy |
| star growth 7d/30d | 갑자기 관심을 받는지 확인 |
| default branch latest commit | 실제 개발이 지속되는지 확인 |
| releases / tags | 안정화된 배포 단위가 있는지 확인 |
| license | 도입 가능성과 리스크 판단 |
| topics / language | 분야 분류와 검색성 |
| open issues / recent PRs | 유지보수 상태와 커뮤니티 활동 |

하지만 metadata만으로는 부족하다. 진짜 변화는 changelog와 release note에 있다.

### 2. Changelog and release notes

Watchlist의 핵심은 레포 자체가 아니라 **변화 이력**이다. GitHub Releases API는 release body, tag, prerelease/draft 여부, published date를 제공한다.[^github-releases]

추적해야 할 changelog 신호:

| Changelog signal | Interpretation |
|---|---|
| breaking change | 도입 전 검토 필요 |
| new example / tutorial | 실제 사용 가능성 상승 |
| performance improvement | benchmark나 production 적용 가능성 상승 |
| bug fix only | 안정화 중일 가능성 |
| migration guide | API가 성숙하거나 크게 바뀌는 중 |
| deprecation | 의존 중이면 대체 계획 필요 |
| security fix | 즉시 확인 필요 |
| docs restructure | 프로젝트 방향성 변화 가능성 |

좋은 watchlist는 “v0.4.2가 나왔다”에서 멈추지 않고 다음처럼 요약해야 한다.

```text
owner/repo v0.4.2
- 의미: examples와 docs가 크게 늘어 try-soon 후보로 상승
- 리스크: API rename이 있어 기존 코드와 호환성 확인 필요
- 액션: 1시간 spike로 sample 실행
```

### 3. Docs and examples changes

AI/개발 도구 레포는 코드보다 docs/examples 변화가 도입 가능성을 더 잘 보여줄 때가 있다.

- `README.md`가 설치 중심에서 use case 중심으로 바뀌었는가?
- `examples/`, `cookbook/`, `templates/`가 추가되었는가?
- benchmark, eval, integration 문서가 생겼는가?
- Docker, Helm, Terraform, GitHub Actions 예제가 생겼는가?
- quickstart가 5분 안에 실행 가능한 수준인가?

이 신호는 `git diff`나 GitHub contents API로도 볼 수 있지만, 처음에는 releases/changelog 요약만 추적해도 충분하다.

## Source map

| Source | Use | Collection strategy | Caveat |
|---|---|---|---|
| GitHub watchlist | 이미 관심 있는 레포의 변화 추적 | REST API, releases, events, Atom feeds | rate limit와 중복 이벤트 처리 필요 |
| GitHub Trending | 새로 뜨는 레포 발견 | topic/language별 daily scrape 또는 RSS mirror | star spike는 hype일 수 있음 |
| GeekNews | 한국 개발/스타트업 맥락 | 뉴스레터, RSS/웹, 수동 큐레이션 | 코멘트 맥락을 함께 봐야 함 |
| Hacker News | 글로벌 개발자 반응 | Official API 또는 Algolia Search API[^hn-api][^hn-algolia] | 댓글 품질 편차 큼 |
| arXiv | 최신 논문 원천 | arXiv API query[^arxiv-api] | 구현체가 있는지 별도 확인 필요 |
| Hugging Face Papers | ML 논문/모델 트렌드 | trending page, paper metadata | 논문 popularity와 production readiness는 다름 |
| Blogs/RSS | maintainer의 의도와 로드맵 | RSS/Atom, blogwatcher | feed 품질이 제각각 |
| Threads/LinkedIn | 실무자 반응과 adoption signal | 공식 API/수동 저장/링크 큐레이션 | 공개 API·권한 제한, noise 큼 |

Threads와 LinkedIn은 자동 수집 욕심을 줄이는 편이 좋다. 공개 API, 로그인, 약관, rate limit 이슈가 커서 처음에는 “좋은 스레드/포스트 링크를 inbox에 저장 → 주간 digest에서 함께 요약”하는 semi-manual 방식이 현실적이다.

## Watchlist schema

처음부터 복잡한 DB를 만들 필요는 없다. 최소 스키마는 아래 정도면 된다.

```yaml
repo: owner/name
url: https://github.com/owner/name
category: agent | rag | eval | inference | ui | infra | research | devtool
status: watch | rising | maturing | try-soon | adopt-candidate | reference-only | ignored
first_seen: 2026-05-18
last_checked: 2026-05-18

repo_signals:
  stars: 12000
  star_growth_7d: 430
  commits_30d: 52
  merged_prs_30d: 18
  open_issues: 41
  latest_commit_at: 2026-05-16

release_signals:
  latest_release: v0.8.2
  latest_release_at: 2026-05-14
  changelog_summary: "examples added, API renamed, migration guide included"
  breaking_change: true
  security_fix: false
  docs_or_examples_changed: true

external_signals:
  github_trending: false
  geeknews_mentions_30d: 1
  hn_mentions_30d: 2
  paper_links: []
  social_links: []

assessment:
  relevance: high
  maturity: medium
  risk: medium
  reason: "agent workflow에 바로 참고 가능하지만 API rename 확인 필요"

next_action:
  type: spike
  priority: high
  owner: syshin0116
  due: 2026-05-24
```

## Scoring model

점수는 정확한 예측 모델보다 “비교 가능한 언어”를 만드는 데 목적이 있다.

_Scoring 시각화는 public-facing article [기술 정보 레이더 글](../AI/2026-05-18-Tech-Intelligence-Radar.md)에 포함했다._

권장 가중치:

| Dimension | Weight | Example signal |
|---|---:|---|
| Relevance | 30% | 내 프로젝트와 직접 연결되는가 |
| Maturity delta | 25% | release, docs, examples, issue/PR 개선 |
| Growth | 15% | star velocity, trending, mentions |
| Trust | 15% | maintainer, company, citations, license |
| Adoption cost | 15% | 설치 난이도, API 안정성, migration cost |

새 레포는 growth 비중을 조금 높이고, watchlist 레포는 maturity delta와 changelog 비중을 높인다.

## Digest rhythm

_Digest rhythm 시각화는 public-facing article [기술 정보 레이더 글](../AI/2026-05-18-Tech-Intelligence-Radar.md)에 포함했다._

### Daily alert

매일은 짧아야 한다.

```markdown
# Repo Radar Daily

## 긴급 확인
- owner/repo: security fix 포함 release
- owner/repo2: breaking change 포함 v1.0 release

## 의미 있는 변화
- owner/repo3: examples 추가 → try-soon 후보
- owner/repo4: 60일째 release 없음 → risk 상승
```

### Weekly digest

주간 리포트는 의사결정 중심으로 만든다.

```markdown
# Weekly Repo Intelligence

## 1. Watchlist에서 변화가 큰 레포
1. owner/repo
   - 변화: v0.8 release, changelog에 migration guide 추가
   - 해석: API 안정화 단계로 보임
   - 추천: spike

## 2. 새로 발견한 레포
1. owner/new-repo
   - 근거: GitHub Trending + HN discussion + maintainer blog
   - 추천: reference-only

## 3. 최신 논문/구현체 연결
- Paper A → implementation repo X 존재
- Paper B → 아직 구현체 없음, 아이디어만 기록

## 4. 이번 주 액션
- [ ] repo X 1시간 spike
- [ ] repo Y changelog만 follow
- [ ] repo Z ignore 처리
```

## 활용 루프

| Action | When to choose | Output |
|---|---|---|
| adopt | 안정적이고 지금 프로젝트에 바로 필요 | 도입 계획, ADR, PR |
| spike | 좋아 보이지만 검증 필요 | 1~3시간 실험 노트 |
| reference | 구조/아이디어/UX만 참고 | wiki note, code pattern link |
| monitor | 아직 이르지만 계속 볼 가치 있음 | watchlist 유지 |
| ignore | hype가 크지만 쓸모/신뢰 낮음 | archive reason |

Spike 결과는 짧아야 다음 의사결정으로 이어진다.

```markdown
## Spike result: owner/repo

결론: adopt-candidate / reference-only / ignore

좋았던 점:
- 

막힌 점:
- 

내 프로젝트 적용 가능성:
- 

다음 액션:
- 
```

## Implementation roadmap

### Week 1: Manual watchlist

- 관심 레포 30~100개를 `watch`, `try-soon`, `reference-only`로 분류한다.
- 레포마다 category와 reason을 1줄씩만 적는다.
- changelog URL, release URL, docs URL을 같이 저장한다.

### Week 2: GitHub collector

- GitHub API로 repo metadata와 releases를 매일 snapshot한다.
- latest release body를 LLM으로 3줄 요약한다.
- 이전 snapshot과 비교해 `new release`, `star spike`, `inactive`, `docs/examples changed`를 감지한다.

### Week 3: External signal collector

- GitHub Trending, GeekNews, HN, arXiv, Hugging Face Papers를 topic별로 수집한다.
- 같은 repo/link/paper를 dedupe한다.
- social source는 자동화보다 링크 inbox로 시작한다.

### Week 4: Digest and action queue

- 매주 Slack 또는 블로그 draft로 digest를 만든다.
- 상위 3개만 spike 후보로 올린다.
- 매월 watchlist에서 `ignored`, `dead-or-risky`, `adopted`를 정리한다.

## Design principle

Tech intelligence radar의 목적은 더 많은 탭을 열게 만드는 것이 아니다. 목적은 다음 네 가지 질문에 빨리 답하게 만드는 것이다.

1. 지금 새로 봐야 할 것은 무엇인가?
2. 이미 보고 있던 것 중 의미 있게 변한 것은 무엇인가?
3. 이번 주에 실험할 것은 무엇인가?
4. 버리거나 보류할 것은 무엇인가?

이 네 질문에 답하지 못하는 수집은 정보 수집이 아니라 정보 부채다.

## Related pages

- [[llm-wiki]]
- [[second-brain-rag]]
- [[agentic-decision-workflow]]
- [[blog-seo]]

## Footnotes

[^github-repos]: GitHub REST API repository endpoints: https://docs.github.com/en/rest/repos
[^github-releases]: GitHub REST API releases endpoints: https://docs.github.com/en/rest/releases
[^hn-api]: Official Hacker News API documentation: https://github.com/HackerNews/API
[^hn-algolia]: Hacker News Search API powered by Algolia: https://hn.algolia.com/api
[^arxiv-api]: arXiv API User Manual: https://info.arxiv.org/help/api/user-manual.html
