---
title: "Clidex"
type: tool
tags:
  - cli
  - rust
  - ai
sources:
  - content/Projects/Clidex/03-Search-Quality-Hardening.md
  - content/Projects/Clidex/04-CLI-UX-Design.md
created: 2026-04-25
updated: 2026-04-25
author: wiki-curator
draft: false
coverage: medium
---

## Summary

Clidex는 AI 에이전트와 인간 모두를 위한 CLI 도구 발견(discovery) 도구로, Rust로 구현된 BM25 기반 검색 엔진을 갖는다. 5,277개 도구 인덱스를 대상으로 퍼지 매칭, 동의어 확장, edit distance 오타 교정을 지원하며, TTY 감지 기반 출력 형식 자동 전환으로 사람과 에이전트가 동일 명령을 공유할 수 있다.

## Key Claims

- BM25 검색 알고리즘의 세 가지 구조적 버그가 확인됐다: fuzzy anchor가 오타 교정을 막고(substring 포함 요구), synonym gate가 확장 결과를 원래 query term만으로 재검증해 탈락시키고, intent_coverage가 토큰 경계 없이 substring 검색해 false positive를 만들었다.[^1]
- Levenshtein edit distance를 다층 조기 종료 조건(단일 단어 쿼리에서만 실행, 길이 차이 사전 검사, 길이별 허용 거리 1~2)과 결합해 5,277개 인덱스에서도 실용적 성능을 유지한다.[^1]
- 테스트는 세 층이 필요하다: 알고리즘 로직 검증을 위한 fixture(28개, adversarial 8개 포함), 현실 품질 검증을 위한 실제 인덱스 테스트(5,277개), 데이터 파이프라인 회귀 감지를 위한 coverage 테스트(67개 must-have).[^1]
- stdout이 터미널인지 파이프인지를 `atty::is(atty::Stream::Stdout)`로 감지해 사람은 pretty 출력, 에이전트는 YAML 출력을 자동으로 선택한다. `ls`, `grep`과 같은 UNIX 관례를 따른다.[^2]
- `--score` 플래그 사용 시 Tool 객체에 score를 주입하면 명령마다 출력 스키마가 달라진다. `SearchResult` 래퍼로 분리하면 score 없을 때 모든 명령이 동일한 `[Tool]` 스키마를 반환한다.[^2]
- "결과 집합이 빌 수 있는" 탐색형 명령(search, category browse, trending)은 exit 0, "특정 대상을 지목하는" 조회형 명령(info, compare)은 exit 1이다.[^2]
- 자동 인덱스 다운로드는 stdin이 TTY일 때만 실행한다. CI나 파이프라인에서 읽기 명령이 네트워크 요청 및 파일 쓰기 부작용을 가지는 것을 방지한다.[^2]

## Examples / Code

**edit distance 조기 종료 조건 (from source)**

```rust
let is_single_word_query = !query_lower.contains(' ');
let max_edit = if !is_single_word_query { 0 }
    else if qlen >= 6 { 2 }
    else if qlen >= 4 { 1 }
    else { 0 };

let is_typo_match = if max_edit > 0 {
    let name_len_diff = qlen.abs_diff(name_lower.len());
    if name_len_diff <= max_edit {
        edit_distance(&query_lower, &name_lower) <= max_edit
    } else { false }
} else { false };
```

**synonym gate 수정 — 확장 term으로 재검증 (from source)**

```rust
let (syn_intent_bonus, syn_covered) = if covered == 0 {
    let (sb, sc, _) = intent_coverage(&expanded_term_refs, tool);
    (sb * 0.5, sc)  // synonym은 절반 가중치
} else {
    (0.0, covered)
};
```

**TTY 감지 출력 분기 (from source)**

```rust
fn get_format(pretty: bool, json: bool, yaml: bool) -> Format {
    if pretty { Format::Pretty }
    else if json { Format::Json }
    else if yaml { Format::Yaml }
    else if atty::is(atty::Stream::Stdout) { Format::Pretty }
    else { Format::Yaml }
}
```

**SearchResult 래퍼 (from source)**

```rust
#[derive(serde::Serialize)]
struct SearchResultOutput<'a> {
    score: f64,
    #[serde(flatten)]
    tool: &'a Tool,
}
```

**테스트 층 구성 (from source)**

| 층 | 파일 | 목적 | 규모 |
|---|---|---|---|
| Fixture | search_test.rs | 알고리즘 로직 검증 | 28개 도구 |
| 실제 인덱스 | search_real_index_test.rs | 현실 품질 검증 | 5,277개 도구 |
| Coverage | index_coverage_test.rs | 데이터 파이프라인 회귀 | 67개 must-have |

## Connections

- [[cli-ux-design]] — Clidex에서 실천한 CLI UX 설계 원칙들(TTY 감지, 출력 계약, exit code)을 일반 패턴으로 정리

## Footnotes

[^1]: content/Projects/Clidex/03-Search-Quality-Hardening.md
[^2]: content/Projects/Clidex/04-CLI-UX-Design.md
