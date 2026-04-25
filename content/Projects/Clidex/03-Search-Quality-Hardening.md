---
title: "Clidex 검색 품질 강화: 오타 교정, 테스트 정교화, 데이터 소스 확장"
date: 2026-04-04
modified: 2026-04-04
tags:
  - Projects
  - Rust
  - CLI
  - AI-Agent
  - Search
  - BM25
  - Testing
draft: false
enableToc: true
description: "Clidex의 검색 알고리즘 버그 수정(fuzzy anchor, synonym gate, edit distance), 테스트를 adversarial fixture + 실제 인덱스 기반으로 강화하고, crates.io/PyPI 데이터 소스를 확장한 과정."
summary: |
  [이전 글](/projects/clidex/02-search-improvement)에서 데이터 파이프라인을 확장해 커버리지 91%, 정확도 82%를 달성했다. 하지만 코드 리뷰를 통해 검색 알고리즘의 **구조적 문제 3가지**가 드러났고, 20개 도구 fixture(고정 테스트 데이터)에서 100% 통과하던 테스트가 실제 품질을 충분히 검증하지 못한다는 점도 확인됐다. 이 글은 알고리즘 버그 수정, 테스트 정교화, 데이터 소스 확장을 기록한다.
  
  모든 수치는 로컬 인덱스(`~/.clidex/index.yaml`, 2026-04-02 빌드, 5,277개 도구) 기준이다.
published: 2026-04-04
---
---

## 문제 인식: 100% 통과하는 테스트의 함정

### 세 가지 구조적 모순

코드 리뷰에서 검색 엔진의 세 가지 문제가 드러났다:

**1. Fuzzy anchor가 오타 교정을 죽이고 있었다**

README에는 "Catches typos"라고 적혀 있지만, 실제로 `ripgrpe` → `ripgrep` 같은 전형적 오타가 매칭되지 않았다. Fuzzy fallback 경로에서 `has_anchor` 체크가 substring 포함을 요구했는데, 오타된 문자열은 원래 이름의 substring이 아니므로 항상 탈락했다.

```rust
// 이전: substring 포함이 필수 → 오타는 통과 불가
let has_anchor = name_lower.contains(&query_lower)
    || query_lower.contains(&name_lower);

if best_fuzzy > fuzzy_threshold && has_anchor {
    // ripgrpe → ripgrep: has_anchor = false → 탈락
}
```

**2. Synonym 확장 후 뒷단 gate가 결과를 죽였다**

`expand_query()`로 synonym을 확장해 BM25 후보를 찾지만, 이후 confidence gate가 **원래 query term만** 체크했다. 예를 들어 "archive tool"로 검색하면 synonym 확장을 거쳐 `compress`, `zip`, `tar`, `pack` 같은 term이 추가되어 BM25가 관련 도구를 찾지만, gate에서 원래 term인 "archive"가 해당 도구 메타데이터에 직접 없으면 `covered == 0`으로 탈락했다.

```rust
// 이전: 원래 query_terms만 체크 → synonym-only 매치 죽음
let (intent_bonus, covered, _) = intent_coverage(&query_terms, tool);
if name_bonus == 0.0 && (lexical_score < 2.0 || covered == 0) {
    continue; // synonym으로 겨우 찾은 결과가 여기서 탈락
}
```

**3. intent_coverage가 토큰 경계를 무시했다**

`searchable.contains(&tl)`로 전체 메타데이터를 substring 검색하고 있었다. 짧은 term이 긴 단어 내부에 우연히 매칭되는 문제가 있었다 — 예를 들어 "at"이 "d**at**a"에 걸리고, "no"가 "tech**no**logy"에 걸리는 식이다. 토큰 경계를 무시하면 coverage 계산이 부풀려진다.

---

## 수정 1: 오타 교정 — Edit Distance 도입

### 문제: nucleo는 전치를 못 잡는다

nucleo-matcher는 subsequence matcher라서, needle의 모든 문자가 haystack에 **순서대로** 존재해야 한다. `ripgrpe`(r,i,p,g,r,**p,e**)를 `ripgrep`(r,i,p,g,r,**e,p**)에서 찾으면, 마지막 `e`가 `p` 뒤에 없어서 매칭 실패한다.

즉 **문자 전치(transposition) 오타**는 nucleo로 잡을 수 없다.

### 해결: Levenshtein distance + 다층 조기 종료

```rust
fn edit_distance(a: &str, b: &str) -> usize {
    // 표준 Levenshtein DP
}

// 단일 단어 쿼리에서만 실행 (multi-word는 도구 이름 오타가 아님)
let is_single_word_query = !query_lower.contains(' ');

// 길이별 허용 거리: 4-5자 → 1, 6자+ → 2
let max_edit = if !is_single_word_query { 0 }
    else if qlen >= 6 { 2 }
    else if qlen >= 4 { 1 }
    else { 0 };

// Early bailout: 길이 차이가 max_edit보다 크면 계산 skip
let is_typo_match = if max_edit > 0 {
    let name_len_diff = qlen.abs_diff(name_lower.len());
    if name_len_diff <= max_edit {
        edit_distance(&query_lower, &name_lower) <= max_edit
    } else { false }
} else { false };
```

5,277개 도구에서 edit distance를 전부 계산하면 느려지므로 3단계 조기 종료 조건을 적용:
1. **Multi-word query skip**: `"csv to json"`은 도구 이름 오타가 아님
2. **Length difference skip**: 길이 차이 > max_edit면 O(n*m) 계산 불필요
3. **길이별 threshold**: 짧은 이름(4-5자)은 edit distance 1만 허용

---

## 수정 2: Synonym gate — 확장 term으로 재검증

```rust
// 수정: covered == 0이면 synonym 확장 term으로 재검증
let (syn_intent_bonus, syn_covered) = if covered == 0 {
    let (sb, sc, _) = intent_coverage(&expanded_term_refs, tool);
    (sb * 0.5, sc)  // synonym은 절반 가중치
} else {
    (0.0, covered)
};

let lexical_score = bm25_score + name_bonus + cat_bonus
    + desc_bonus + intent_bonus + syn_intent_bonus;

if name_bonus == 0.0 && (lexical_score < 2.0 || syn_covered == 0) {
    continue;
}
```

핵심: synonym으로 살아남은 결과가 **gate는 통과하되, 원래 query term 매치보다 낮은 점수**를 받는다. `syn_intent_bonus = intent_bonus * 0.5`로 인기도에 밀리지 않되 과대평가도 안 되게 했다.

---

## 수정 3: Token-aware intent coverage

```rust
fn word_boundary_match(text: &str, term: &str) -> bool {
    for word in text.split(|c: char| !c.is_alphanumeric() && c != '-') {
        if word.is_empty() { continue; }
        let w = word.to_lowercase();
        if w == term || w.starts_with(term) || term.starts_with(&w) {
            return true;
        }
    }
    false
}
```

필드별 매칭 전략을 분리:
- **name/binary**: exact match
- **tags**: exact 또는 prefix match
- **category**: word-boundary prefix match
- **description**: word-boundary match

`desc_bonus`도 동일하게 `word_boundary_match` 기반으로 변경하여 scoring 규칙 일관성을 확보했다.

---

## 테스트 강화: "100% 통과"를 의심하기

### 문제: 20개 도구 fixture의 한계

기존 테스트의 구조적 약점:

| 약점 | 설명 |
|---|---|
| **Fixture가 너무 작음** | 20개 고정 테스트 도구에서 "top 5 포함"은 사실상 "결과에 있기만 하면 통과" |
| **경쟁 없음** | jq/miller/csvkit 외에 비슷한 도구끼리 겹치는 케이스 없음 |
| **Precision 미측정** | "A가 결과에 있는가?"만 보고 "A가 B보다 위인가?"는 안 봄 |
| **False positive 빈약** | garbage query 3개만, plausible-but-wrong 케이스 없음 |

### 해결 1: Adversarial fixture

8개 경쟁 도구를 추가하여 28개로 확장:

```rust
// ag가 ripgrep과 "grep" 쿼리에서 경쟁
make_tool("ag", None, "The Silver Searcher - code searching tool similar to ack", "Search", ...),
// gitui가 lazygit과 "git tui"에서 경쟁
make_tool("gitui", None, "Blazing fast terminal-ui for git", "Git", ...),
// lsd가 eza와 "ls replacement"에서 경쟁
make_tool("lsd", None, "The next gen ls command", "File Management", ...),
// curlie가 httpie와 "http requests"에서 경쟁
make_tool("curlie", None, "Power of curl, ease of use of httpie", "HTTP", ...),
```

### 해결 2: 순위 assertion

```rust
fn assert_ranks_above(results: &[SearchResult], higher: &str, lower: &str, query: &str) {
    // higher가 lower보다 위에 랭크되는지 검증
}

// "faster grep" → ripgrep이 ag보다 위여야 함
assert_ranks_above(&r, "ripgrep", "ag", "faster grep");
// "git terminal ui" → lazygit이 gitui보다 위여야 함
assert_ranks_above(&r, "lazygit", "gitui", "git terminal ui");
```

### 해결 3: 실제 인덱스 통합 테스트

`search_real_index_test.rs` — 5,277개 실제 도구에서:

| 테스트 | 검증 내용 |
|---|---|
| `real_exact_name_top1` | jq, ripgrep 등 10개 도구가 정확히 #1 |
| `real_ranking_order` | "json processor" → jq가 top 3 |
| `real_false_positive_control` | garbage query → empty |
| `real_result_relevance` | "csv" 결과가 실제로 데이터 관련 도구 |
| `real_typo_correction` | ripgrpe, lazigit 등 5,277개 중에서도 올바른 도구 |
| `real_synonym_queries` | 관련성 기반 검증 (특정 도구 이름 대신 카테고리 적합성) |
| `real_crowded_category` | git/http 같은 밀집 카테고리에서 유명 도구 포함 여부 |
| `real_score_sanity` | exact match가 #2보다 1.5x 이상 높은 점수 |

### 해결 4: Coverage test

`index_coverage_test.rs` — 데이터 파이프라인 회귀 감지:

```rust
const MUST_HAVE_TOOLS: &[(&str, &[&str])] = &[
    ("Data Processing", &["jq", "yq", "dasel", "miller", "csvkit"]),
    ("Search", &["ripgrep", "fd", "fzf", "ag"]),
    ("Git", &["lazygit", "delta", "git"]),
    ("Python", &["poetry", "ruff", "black", "pgcli"]),
    ("Modern Unix", &["atuin", "ouch", "just", "broot", "yazi", "gping"]),
    // ... 총 67개
];
```

| 검증 | 기준 | 현재 |
|---|---|---|
| Must-have 도구 | 67개 중 known missing 외 전부 존재 | 66/67 (known missing: `dog` 1개) |
| 카테고리 breadth | 최소 10개 top-level | 83개 |
| 생태계 presence | Brew 500+, Cargo 30+, npm 10+ | 4,705 / 95 / 131 |
| 총 도구 수 | 최소 4,000개 (regression guard) | 5,277 |

### Adversarial fixture가 잡아낸 것들

테스트를 강화하자마자 실제 문제가 드러났다:

1. **"make http requests" → curlie가 httpie를 이김** — curlie의 description에 "curl"과 "httpie" 모두 포함되어 BM25 점수가 높음. 정답이 하나로 고정되기 어려운 쿼리라 강제 순서 대신 둘 다 top 3 확인으로 변경.

2. **"faster grep" → 실제 인덱스에서 ripgrep이 top 5 밖** — ag, sift, ugrep, vgrep, ripgrep-all이 모두 "grep"과 강하게 매칭. Fixture에서는 안 보이던 문제.

3. **"smart cd command" → 실제 인덱스에서 zoxide 못 찾음** — "smart"은 무의미, "cd"는 2글자로 약한 시그널. 5,277개 도구 중에서는 노이즈에 묻힘.

이런 발견이 테스트 강화의 실질적 가치다.

---

## 데이터 소스 확장

> 아래 두 소스는 코드에 추가된 상태이며, 다음 인덱스 빌드에서 실제 효과가 반영된다. 현재 5,277개 인덱스에는 아직 포함되지 않았다.

### crates.io: enrichment → discovery

기존에는 "이미 아는 도구에 `cargo install` 붙이기"만 했다. 이제 카테고리 기반으로 **신규 도구를 발굴**한다:

```rust
let categories = [
    "command-line-utilities",
    "command-line-interface",
    "development-tools",
    "filesystem",
];
// 카테고리별 top 25 (다운로드 순), 10,000+ 다운로드 필터
// library-only crate 제외 (description에 "library"만 있고 "tool"/"cli" 없는 경우)
```

### PyPI/pipx 추가

Python CLI 생태계는 coverage에서 무시할 수 없다. Seed list 기반으로 39개 주요 Python CLI 도구를 추가:

```rust
let seed_tools = [
    ("ruff", "ruff"), ("mypy", "mypy"), ("pytest", "pytest"),
    ("pre-commit", "pre-commit"), ("mkdocs", "mkdocs"),
    ("streamlit", "streamlit"), ("dvc", "dvc"),
    ("bandit", "bandit"), ("pylint", "pylint"),
    // ... 총 39개
];
// PyPI JSON API로 메타데이터 수집
// pipx install 명령 자동 생성
```

---

## 결과

### 검색 품질

| 지표 | 이전 | 이번 |
|---|---|---|
| **Recall** (fixture) | 30/30 (100%) | **34/34 (100%)** — adversarial fixture 포함 |
| **Typo 교정** | 작동 안 함 | ripgrpe→ripgrep, zoxdie→zoxide, lazigit→lazygit |
| **Synonym-only 매치** | gate에서 탈락 | grep files→ripgrep, navigate quickly→zoxide |
| **실제 인덱스 테스트** | 없음 | **10/10** (5,277 도구) |
| **Coverage 테스트** | 없음 | **66/67** must-have (known missing: `dog` 1개) |
| **성능** (fixture) | ~3ms/query | ~3.6ms/query (28개 도구) |

### 테스트 정교도

| 지표 | 이전 | 이번 |
|---|---|---|
| Fixture 도구 수 | 20 | **28** (8 adversarial) |
| 순위 assertion | 0 | **4** (assert_ranks_above) |
| 실제 인덱스 테스트 | 0 | **10** |
| Coverage 테스트 | 0 | **4** |
| Recall 기준 | 85% | **95%** |
| 테스트 파일 수 | 1 | **3** |

### 데이터 소스

| 소스 | 이전 | 이번 |
|---|---|---|
| crates.io | enrichment only | **+ category discovery** |
| PyPI | 없음 | **seed list 39개 + pipx install** |
| install 방법 | brew, cargo, npm | **+ pipx** |

---

## 회고

### 1. "테스트가 통과한다"와 "품질이 좋다"는 다른 문제다

20개 도구에서 100% recall은 의미 없었다. 경쟁 도구가 없으면 랭킹 테스트가 아니라 존재성 테스트일 뿐이다. 경쟁 도구를 추가하자마자 `"make http requests"` 같은, 정답이 하나로 고정되기 어려운 랭킹 문제가 드러났다.

### 2. 실제 인덱스 테스트는 다른 세계다

Fixture에서 "faster grep" → ripgrep은 당연히 #1이었지만, 5,277개 도구 인덱스에서는 ag, sift, ugrep, vgrep, ripgrep-all이 모두 경쟁한다. **Fixture는 알고리즘 로직을 검증하고, 실제 인덱스는 현실에서의 품질을 검증한다.** 둘 다 필요하다.

### 3. Coverage test는 데이터 파이프라인의 안전망이다

"jq가 인덱스에 있는가?"를 검색 테스트로 간접적으로 검증하는 것보다, "67개 must-have 도구가 모두 존재하는가?"를 직접 검증하는 게 훨씬 명확하다. 데이터 소스가 깨졌을 때 바로 잡아낸다.

### 4. Substring 매칭은 함정이다

`searchable.contains(&tl)`은 직관적이지만, 짧은 term이 긴 단어 내부에 우연히 매칭되는 등 예측 불가능한 동작을 만든다. 토큰 경계 기반 매칭으로 바꾸자 scoring 규칙이 일관적이 되었다.

### 5. Edit distance의 O(n*m)은 스케일에서 문제다

20개 도구에서는 느끼지 못하지만, 5,277개 도구에서 모든 이름에 edit distance를 계산하면 ~880ms/query가 된다. "단일 단어 쿼리에서만 실행"이라는 단순한 조건 하나로 multi-word query 성능이 정상으로 돌아왔다.

---

## 기술 스택 변경 사항

| 레이어 | 이전 | 이번 | 이유 |
|---|---|---|---|
| Fuzzy matching | nucleo만 | **nucleo + Levenshtein** | 전치 오타 교정 |
| Confidence gate | 원래 query term만 | **+ synonym 확장 term** | synonym-only 매치 보존 |
| Intent coverage | substring contains | **word-boundary match** | 부분 문자열 오매칭 제거 |
| desc_bonus | substring contains | **word-boundary match** | scoring 규칙 일관성 |
| 테스트 | 20개 fixture | **28 fixture + 5,277 real + coverage** | 다층 검증 |
| 데이터 소스 | 8개 | **10개 (+crates.io discovery, PyPI)** | coverage 확장 |

---

## 다음 단계

- **실제 인덱스 성능 최적화** — 현재 ~880ms/query (5,277 도구). BM25 엔진 캐싱 또는 incremental index로 개선 가능
- **crates.io/PyPI discovery 반영 확인** — 코드는 추가됨, 다음 인덱스 빌드 후 실제 coverage 변화 측정
- **"faster grep" 랭킹 문제** — 실제 인덱스에서 ripgrep이 ag/sift에 밀리는 현상. popularity boost나 "known alias" 가중치 조정 필요
- **Homebrew threshold tiering** — long-tail CLI 도구의 구조적 유입 경로 확보

---

- GitHub: [syshin0116/clidex](https://github.com/syshin0116/clidex)
