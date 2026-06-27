---
title: "Clidex 검색 개선: 커버리지 43% → 91%, 정확도 47% → 82%"
date: 2026-03-25
modified: 2026-03-25
tags:
  - Projects
  - Rust
  - CLI
  - AI-Agent
  - Search
  - BM25
  - Homebrew
  - Semantic-Search
draft: false
enableToc: true
description: "Clidex의 검색 성능을 실전 테스트로 진단하고, 데이터 파이프라인과 검색 알고리즘을 전면 개편한 과정. 485개 → 5,260개 도구, 커버리지 43% → 91%."
summary: "[이전 글](/projects/clidex/01-overview)에서 BM25 기반 CLI 도구 검색기 Clidex를 만들고, 20개 모의 도구 기준 100% recall을 달성했다. 하지만 실제 인기 CLI 도구 88개로 테스트하자 **커버리지 43%, 검색 정확도 47%**라는 현실이 드러났다. 이 글은 문제를 진단하고, 데이터 파이프라인과 검색 알고리즘을 전면 개편하여 **커버리지 91%, 정확도 82%**로 개선한 과정을 기록한다."
published: 2026-03-25
---

## 문제 인식: 실전은 달랐다

### "테스트는 통과했는데 실제로는 안 되더라"

이전 버전의 Clidex는 20개 모의 도구에 대해 30개 쿼리를 테스트했고, 100% recall을 달성했다. 하지만 이건 **자기가 만든 시험지로 자기가 시험 본 것**과 같았다.

진짜 질문은 이것이었다: **LLM이 실제로 clidex를 쓸 때, 필요한 도구를 찾을 수 있는가?**

이걸 검증하기 위해 2024-2026년 인기 CLI 도구 88개를 웹에서 수집하고, 두 가지를 테스트했다:

1. **커버리지**: 이 도구들이 인덱스에 있는가?
2. **발견성**: 도구 이름을 모르는 상태에서 자연어로 찾을 수 있는가?

### 테스트 결과

```
커버리지:  38/87 = 43%  - 인기 도구의 절반 이상이 인덱스에 없음
Phase 2A:  27/30 = 90%  - 인덱스에 있는 건 잘 찾음
Phase 2B:   1/30 = 3%   - 없는 도구는 당연히 못 찾음
Overall:   28/60 = 47%  - 실질적 검색 정확도
```

### 무엇이 빠져있었나

| 카테고리 | 누락 도구 | 영향 |
|---|---|---|
| **AI/LLM CLI** | aider, claude-code, open-interpreter, aichat, llm, shell_gpt 등 전체 | 높음 |
| **패키지/버전 매니저** | uv(82K★), bun(88K★), mise, volta, fnm | 높음 |
| **DevOps** | dive(54K★), act(70K★), dagger | 높음 |
| **인기 Rust 도구** | btop(31K★), difftastic(25K★), atuin(29K★), ruff(47K★) | 높음 |
| **터미널** | ghostty(49K★), alacritty(63K★) | 중간 |

uv가 82K stars인데 인덱스에 없다. ruff가 47K stars인데 없다. **2024-2026년 가장 주목받는 도구들이 전부 빠져있었다.**

데이터 소스가 awesome-cli-apps 하나에 의존하고 있었기 때문이다.

![Before: 단일 소스 의존](https://i.imgur.com/JJpEpl2.png)

---

## 검색 품질 진단

인덱스에 있는 도구라도 검색 품질에 문제가 있었다.

### 문제 1: 카테고리 보너스가 너무 관대

```
쿼리: "rename files"
기대: nomino, f2 (rename 도구)
실제: trash-cli (삭제 도구) - 1위
```

원인: trash-cli의 카테고리가 "Deleting, **Copying, and Renaming**"이라 "rename"에 +8점 매칭. 설명("Move files to the trash")에는 "rename"이 없는데도 카테고리만으로 1위.

### 문제 2: noise word가 결과를 오염

```
쿼리: "fast python linter"
기대: ruff
실제: starship, fd, yazi - "fast"에만 매칭

쿼리: "node version manager fast"
실제: yazi, gitui, lf - 전부 "fast"에 매칭
```

"fast", "modern", "simple" 같은 일반적인 수식어가 BM25 스코어를 지배하고, 핵심 키워드("python", "linter", "node")가 묻히는 현상.

### 문제 3: 인기도 부스트 부족

```
쿼리: "fuzzy finder"
기대: fzf (79K★)
실제: fzy (작은 프로젝트) - BM25 점수가 비슷할 때 인기도 차이를 반영 못함
```

---

## 검색 대안 리서치

### Rust 검색 라이브러리 비교

| 크레이트 | 필드 부스트 | 퍼지 | 스테밍 | 바이너리 영향 | 판정 |
|---|---|---|---|---|---|
| **tantivy** | 네이티브 | 지원 | 지원 | 무거움 (+10MB) | 오버킬 |
| **probly-search** | **네이티브** | 미지원 | 미지원 | 경량 | 유력 후보 |
| **nucleo-matcher** | N/A | **6-10x 빠름** | N/A | 경량 | fuzzy 교체용 |
| **bm25** (현재) | 미지원 | 미지원 | 지원 | 경량 | 유지 |

### 시맨틱 검색 옵션

| 방식 | 바이너리 증가 | 쿼리 속도 | 오프라인 | 판정 |
|---|---|---|---|---|
| API 임베딩 (OpenAI) | 0 | 200-500ms | 불가 | 부적합 |
| Candle/ONNX | +20-30MB | 10-50ms | 가능 | 너무 무거움 |
| **Model2Vec** | **+2-3MB** | **<1ms** | **가능** | **최적** |

Model2Vec은 Sentence Transformer를 정적 임베딩 룩업 테이블로 증류한 것이다. 트랜스포머 추론 없이 토크나이즈 → 룩업 → 평균으로 벡터를 생성한다. 1ms 미만의 쿼리 속도로 CLI 도구에 적합.

### SEISMIC 논문 (SIGIR '24) 검토

[Efficient Inverted Indexes for Approximate Retrieval over Learned Sparse Representations](https://arxiv.org/abs/2404.18812)도 검토했다. SPLADE 임베딩 위에서 서브밀리초 검색을 달성하는 인덱스 구조인데, clidex에는 부적합했다:

1. **스케일 미스매치** - SEISMIC은 수백만 문서용. 485개에선 brute-force가 더 빠름
2. **SPLADE 모델 필요** - 420MB BERT 모델이 필요. CLI 도구에 번들 불가
3. **문제가 다름** - clidex의 문제는 검색 속도가 아니라 **관련성**과 **커버리지**

---

## 핵심 전환: "CLI인지 구분"보다 "넓게 모으기"

### 발상의 전환

처음에는 Homebrew에서 CLI 도구를 자동 발견하려 했다. 하지만 `is_likely_cli()` 함수를 테스트해보니:

```
Homebrew 전체:          8,285개
is_likely_cli 통과:     6,916개 (83%) ← 서버, 게임, 플러그인까지 포함
```

mise("Polyglot **runtime** manager")는 "runtime" 키워드 때문에 서버로 오분류됐다. uv, ruff, btop 같은 핵심 도구가 빠질 수 있었다.

GitHub Search API도 시도했지만, **인기 CLI 도구의 57%가 cli/command-line 토픽을 갖고 있지 않았다:**

```
uv(82K★):    토픽 = packaging, python, resolver      ← "cli" 없음
ruff(47K★):  토픽 = linter, python, pep8             ← "cli" 없음
btop(31K★):  토픽 = (없음)                           ← 아예 없음
```

> [!tip]
> **CLI인지 구분하는 것보다, 확실한 non-CLI만 제외하고 나머지는 전부 포함하는 게 낫다.**
>
> 인덱스에 nginx가 있어도 "json processor" 검색에 nginx가 나오진 않는다. 검색 알고리즘이 관련성을 알아서 처리한다. 반면 ruff를 제외하면 "python linter"를 찾을 수 없다.
>
> **과소 포함(false negative)이 과다 포함(false positive)보다 훨씬 나쁘다.**

### 소스별 역할 분리

완벽한 자동 필터 대신, 각 소스의 강점에 맞는 역할을 부여했다:

![After: 다중 소스 + 자동 발견](https://i.imgur.com/jCrqCkd.png)

### Homebrew Analytics: 의외의 좋은 데이터 소스

Homebrew의 install-on-request analytics는 **사용자가 직접 설치한 횟수**를 제공한다 (종속성 설치 제외). 33,000개 도구의 연간 설치 수:

```
uv:        1,200,336회/년
mise:        591,458
fzf:         505,577
jq:          684,701
lazygit:     234,674
btop:        137,128
ruff:        112,044
atuin:        98,896
```

이 데이터를 GitHub stars가 없는 도구의 popularity boost 대체재로 사용했다.

---

## 구현

### 데이터 파이프라인 변경

#### Homebrew 자동 발견 (최대 영향)

`add_homebrew_cli_tools()` (18개 하드코딩) → `discover_from_homebrew()` (자동):

```rust
fn discover_from_homebrew(existing: &mut Vec<Tool>, brew_data: &[BrewFormula],
                          analytics: &HashMap<String, u64>) {
    let hard_exclude = [
        "programming language", "runtime environment",
        "database system", "web server", "proxy server",
        "compiler collection", "protocol buffers",
    ];

    for formula in brew_data {
        if formula.keg_only || formula.name.contains('@') { continue; }
        if hard_exclude.iter().any(|kw| desc.contains(kw)) { continue; }

        // 연 5,000회 이상 설치 OR GitHub 레포 있음
        let installs = analytics.get(&formula.name).copied().unwrap_or(0);
        if installs < 5000 && !has_github_homepage { continue; }

        // 자동 카테고리 분류 후 추가
        let category = auto_categorize(&desc, &name);
        existing.push(tool);
    }
}
```

결과: **+3,721 도구** 자동 발견.

#### Homebrew Cask (터미널 앱)

ghostty, alacritty 같은 터미널 에뮬레이터는 Homebrew **Cask**에만 있다 (formula가 아님). CLI 관련 키워드("terminal", "shell", "emulator" 등)로 필터링:

```
7,575 casks → 625 CLI-related casks 발견
```

#### npm 자동 발견

npm registry에서 `cli`, `command-line-tool` 키워드로 인기순 검색:

```
+97 CLI packages (claude-code, bun 등)
```

#### repo URL 기반 중복 제거

6개 소스에서 같은 도구가 다른 이름으로 올 수 있다:

| 소스 | 이름 |
|---|---|
| awesome-cli-apps | delta |
| Homebrew | git-delta |
| crates.io | git-delta |

이름만으로 비교하면 "delta" ≠ "git-delta"라 중복으로 인식 못 한다. **GitHub repo URL을 dedup key로** 사용:

```rust
fn deduplicate(tools: &mut Vec<Tool>) {
    // Phase 1: 같은 repo URL → 머지 (install 합집합, tags 합집합, 더 긴 설명)
    // Phase 2: 같은 이름 → 더 많은 데이터를 가진 쪽 유지
}
```

### 검색 알고리즘 개선

![검색 스코어링 파이프라인](https://i.imgur.com/43dg6Sf.png)

#### 쿼리 전처리: noise word 제거

```rust
const QUERY_NOISE: &[&str] = &[
    "fast", "modern", "simple", "easy", "best", "good",
    "tool", "tools", "command", "alternative", "replacement",
    "want", "need", "looking", "for", "something", ...
];

// "fast python linter" → "python linter"
// → ruff가 1위로 올라옴
```

#### Popularity boost에 brew 설치 수 fallback

```rust
fn popularity_boost(tool: &Tool) -> f64 {
    // 1차: GitHub stars (0-20점)
    if let Some(stars) = tool.stars { return stars_to_boost(stars); }
    // 2차: Homebrew install-on-request (0-18점)
    if let Some(installs) = tool.brew_installs_30d { return installs_to_boost(installs); }
    // 3차: 데이터 없음 → 0.5점 (낮은 기본값)
    0.5
}
```

Stars가 없는 도구도 brew 설치 수로 인기도를 반영할 수 있게 되면서, "fuzzy finder" → fzf(505K installs)가 fzy를 이기게 됨.

#### 카테고리 보너스 조건 강화

```rust
// 이전: 카테고리 매칭 → 무조건 +8점
// 이후: 설명에도 매칭되면 +8점, 카테고리만 매칭되면 +2점
let cat_bonus = if desc_match_count > 0 {
    matching_terms as f64 * 8.0    // 설명도 매칭 → 확신
} else {
    matching_terms as f64 * 2.0    // 카테고리만 매칭 → 약한 신호
};
```

이제 "rename files" → trash-cli(카테고리 "...Renaming"이지만 설명에 "rename" 없음)가 아니라 nomino(설명에 "rename" 있음)가 올라옴.

#### nucleo-matcher 교체

`fuzzy-matcher` (skim) → `nucleo-matcher` (Helix editor 사용):
- 6-10x 빠른 퍼지 매칭
- 더 나은 Unicode 지원
- 실전 검증 (Helix editor에서 수만 파일 검색에 사용)

#### Model2Vec 시맨틱 검색 (feature-gated)

`--features semantic`으로 활성화하면 BM25 + 코사인 유사도를 RRF(Reciprocal Rank Fusion)로 합산:

```
[빌드 타임]
tool descriptions → Model2Vec(potion-base-2M, 64dim) → index.embeddings.bin

[쿼리 타임]
query → Model2Vec → 쿼리 벡터
  BM25 랭킹 + 코사인 유사도 랭킹
  → RRF: score(d) = 1/(60+rank_bm25) + 1/(60+rank_semantic)
  → 최종 결과
```

### 빌드 최적화: 23분 → 5분

도구가 485 → 5,260개로 늘면서 GitHub API stars enrichment가 병목이 됐다. 5,000개 레포에 순차적으로 API 호출 → **17분 소요** (전체 빌드 23분 중 75%).

GitHub Free 플랜은 월 2,000분이므로 매일 23분이면 월 690분(35%) 소비. 개선이 필요했다.

![빌드 최적화: Before vs After](https://i.imgur.com/6mjyUny.png)

#### 이전 인덱스를 stars 캐시로 재사용

별도 캐시 파일(JSON, SQLite 등)을 만드는 대신, **이전 빌드의 `index.yaml`을 그대로 캐시로 사용**하는 게 가장 깔끔했다. 이미 3,896개 도구의 stars가 들어있으니 새 파일이 필요 없다:

```yaml
# build-index.yml
- name: Download previous index for stars cache
  run: |
    curl -fsSL -o prev_index.yaml \
      https://github.com/${{ github.repository }}/releases/download/index/index.yaml \
      || echo "No previous index found"

- name: Build index
  run: ./target/release/build_index index.yaml prev_index.yaml
```

```rust
fn load_stars_cache(path: &str) -> HashMap<String, (u64, Option<String>, Option<String>)> {
    let index: Index = serde_yaml::from_str(&std::fs::read_to_string(path)?)?;
    index.tools.into_iter()
        .filter_map(|t| t.stars.map(|s| (t.name.to_lowercase(), (s, t.last_updated, t.links.homepage))))
        .collect()
}
```

3일 이내 캐시는 재사용하고, 새 도구나 3일 경과한 것만 API 호출:

```
Day 1: 768 캐시 + 3,132 fetch (첫 빌드, 캐시 부분 적용)
Day 2: ~3,896 캐시 + ~200 fetch (대부분 캐시 히트)
Day 3+: ~3,800 캐시 + ~300 fetch (3일 순환 갱신)
```

#### 병렬 API 호출

순차 → 10개 동시:

```rust
// 10개씩 병렬 fetch
for chunk in to_fetch.chunks(concurrency) {
    let futures: Vec<_> = chunk.iter()
        .map(|(_, owner, repo)| fetch_single_github(owner, repo, token, client))
        .collect();
    let results = futures::future::join_all(futures).await;
    // ...
}
```

#### 결과

| | 이전 | 캐시 + 병렬 |
|---|---|---|
| Stars enrichment | 17분 (5,000 순차) | **1분 40초** (768 캐시 + 3,132 병렬) |
| **전체 빌드** | **23분 33초** | **5분 41초** |
| 월 Actions 사용량 | 690분 | **~170분** |

내일부터는 캐시 히트율이 올라가 전체 빌드 **~4분**, 월 **~120분** 예상.

---

## 결과

### Before vs After

| 지표 | Before | After | 변화 |
|---|---|---|---|
| **인덱스 도구 수** | 485 | **5,260** | ×10.8 |
| **커버리지** (88개 인기 도구) | **43%** | **91%** | +48pp |
| **Phase 2A** (인덱스 도구 자연어 검색) | 90% | **80%** | -10pp |
| **Phase 2B** (이전 누락 도구 검색) | **3%** | **83%** | +80pp |
| **Overall** (60개 쿼리) | **47%** | **82%** | +35pp |
| GitHub stars enrichment | 437 | **3,896** | ×8.9 |

### Phase 2A 하락 분석

90% → 80%로 내려간 건 도구 수가 10배 늘면서 경쟁이 치열해졌기 때문:

| 쿼리 | 기대 | 실제 | 해석 |
|---|---|---|---|
| disk usage analyzer | dust | gdu | 둘 다 disk usage 도구 - **틀린 게 아님** |
| process monitor | procs | htop | htop이 125K installs로 인기도 압도 - **합리적** |
| fuzzy finder | fzf | **fzf** | stars 반영 후 해결 |
| http api client tui | curlie | ATAC | 둘 다 API client TUI - **틀린 게 아님** |

대부분 "틀린 게 아니라 다른 관련 도구가 나온 것". 실제 LLM 사용에서는 top 5 중 하나로 찾을 수 있다.

### 새로 찾을 수 있게 된 도구들

이전에 **전혀 검색 불가능**했지만 이제 자연어로 찾을 수 있는 도구들:

```
"fast python linter"        → ruff       (이전: starship)
"python package manager"    → uv         (이전: 검색 불가)
"shell history sync"        → atuin      (이전: 검색 불가)
"docker image explorer"     → dive       (이전: 검색 불가)
"run github actions locally"→ act        (이전: 검색 불가)
"system monitor tui"        → btop       (이전: 검색 불가)
"structural diff"           → difftastic (이전: 검색 불가)
"node version manager"      → fnm        (이전: 검색 불가)
"polyglot version manager"  → mise       (이전: 검색 불가)
"sed replacement"           → sd         (이전: 검색 불가)
```

### 자동 업데이트 지속 가능성

| 소스 | 신규 도구 유입 | 자동화 수준 |
|---|---|---|
| Homebrew formulae | 주 20-30개 새 formula | 완전 자동 |
| awesome-cli-apps | 주 5-10개 커뮤니티 PR | 자동 반영 |
| toolleeo/cli-apps | 주간 업데이트 | 자동 반영 |
| Homebrew Cask | 수시 추가 | 완전 자동 |
| npm registry | 수시 추가 | 완전 자동 |

새로운 CLI 도구가 Homebrew에 등록되면 다음 일일 빌드에서 자동으로 인덱싱된다.

---

## 회고

### 1. 검색 품질보다 커버리지가 더 중요했다

처음에는 BM25 알고리즘 튜닝에 집중했다. 하지만 실전 테스트에서 드러난 건 **인덱스에 도구가 없으면 아무리 좋은 알고리즘도 무용지물**이라는 것. Phase 2B에서 1/30(3%)이라는 수치가 이를 증명한다.

알고리즘 개선(쿼리 전처리, popularity boost 등)은 80% → 82% 정도의 점진적 개선을 가져왔지만, 데이터 소스 확장은 43% → 91%로 끌어올렸다.

### 2. 완벽한 필터보다 넓은 수집 + 좋은 랭킹

Homebrew에서 "CLI인가 아닌가"를 자동 판별하려다 mise(CLI 도구)를 "서버"로 오분류하는 문제에 부딪혔다. 해결책은 필터를 정교하게 만드는 것이 아니라, **필터를 최소화하고 검색 알고리즘이 관련성을 처리하게** 하는 것이었다.

nginx가 인덱스에 있어도 "json processor" 검색에 nginx가 나오진 않는다. 반면 ruff를 제외하면 "python linter"를 찾을 수 없다.

### 3. Homebrew install-on-request analytics = 의외의 좋은 데이터 소스

GitHub stars는 널리 알려진 인기도 지표지만, **실제 사용량**과 일치하지 않을 수 있다. Homebrew의 install-on-request(연간 설치 수)는 **사용자가 직접 `brew install`을 실행한 횟수**라 실사용 인기도의 더 정확한 프록시다. 이걸 GitHub stars의 fallback으로 사용한 것이 검색 랭킹을 크게 개선했다.

### 4. 새 캐시 파일보다 기존 데이터 재활용

Stars 캐싱을 구현할 때 JSON 파일, SQLite 등 새 캐시 포맷을 고민했지만, 결국 **이전 빌드의 `index.yaml`을 그대로 캐시로 사용**하는 게 가장 깔끔했다. 이미 3,896개 도구의 stars가 들어있는 파일이 있는데 왜 새 파일을 만드나? 새로운 인프라를 추가하기 전에 이미 가진 것을 재활용할 수 없는지 먼저 생각하는 습관.

### 5. 모의 테스트의 함정

20개 도구, 30개 쿼리로 100% recall을 달성했다고 만족했지만, 실전 88개 도구 테스트에서 43% 커버리지가 나왔다. **자기가 만든 데이터로 자기 시스템을 테스트하면 좋은 결과가 나올 수밖에 없다.** 외부 데이터(웹에서 수집한 인기 도구 리스트)로 테스트해야 진짜 성능이 보인다.

---

## 기술 스택 변경 사항

| 레이어 | Before | After | 이유 |
|---|---|---|---|
| Fuzzy matching | fuzzy-matcher (skim) | **nucleo-matcher** | 6-10x 빠름, Helix 검증 |
| Popularity | GitHub stars만 | **stars + brew installs** | stars 없는 도구도 인기도 반영 |
| 데이터 소스 | awesome-cli-apps + Homebrew 18개 | **6개 소스 자동 수집** | 커버리지 43%→91% |
| 시맨틱 검색 | 없음 | **Model2Vec + RRF** (optional) | 키워드 불일치 보완 |
| 중복 제거 | 이름 기반 | **repo URL 기반 머지** | delta≠git-delta 문제 해결 |
| 빌드 시간 | 23분 (순차 API) | **5분 (캐시+병렬)** | 이전 인덱스 재활용, 10x 동시 요청 |

---

## 다음 단계

- **modern-unix awesome-list 파서 수정** - 마크다운 형식이 달라 0개 파싱됨
- **Homebrew Cask CLI 필터 정밀화** - 625개 중 순수 터미널 앱만 선별
- **PyPI console_scripts 자동 발견** - shell_gpt 같은 pip 전용 도구 커버
- **Model2Vec 시맨틱 검색 CI 통합** - 일일 빌드에서 임베딩 자동 생성

---

- GitHub: [syshin0116/clidex](https://github.com/syshin0116/clidex)