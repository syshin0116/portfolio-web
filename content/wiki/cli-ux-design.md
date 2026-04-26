---
title: "CLI UX 설계 원칙"
type: pattern
tags:
  - cli
  - rust
  - backend
  - agent
  - ux
  - api-design
  - unix
  - pattern
sources:
  - content/Projects/Clidex/04-CLI-UX-Design.md
summary: "CLI 도구의 사용성은 기능 추가가 아니라 출력 계약과 동작 규칙의 설계 문제다. TTY 감지로 사람과 기계의 출력 기본값 충돌을 해결하고, 출력 스키마를 API 계약처럼 안정적으로 유지하고, 명령의 의미에 따라 exit code를 분리하면 인간과 에이전트 모두가 예측 가능하게 사용할 수 있는 도구가 된다."
created: 2026-04-25
updated: 2026-04-26
author: wiki-curator
draft: false
---

## Key Claims

- `atty::is(atty::Stream::Stdout)`로 stdout이 터미널인지 파이프인지 감지해 출력 형식을 자동 전환하면 사람과 에이전트 모두에게 기본값이 적합해진다. `ls`, `grep`이 30년간 써온 UNIX 관례와 같다.[^1]
- CLI stdout은 API response body와 같다. 플래그 하나에 따라 스키마가 바뀌면 파싱 코드에 분기가 생긴다. 추가 정보(score 등)는 래퍼 구조체로 분리해 "기본은 호환, 추가는 확장" 원칙을 유지해야 한다.[^1]
- 명령의 성격에 따라 exit code를 나눈다: "결과 집합이 빌 수 있는" 탐색형은 exit 0, "특정 대상을 지목하는" 조회형은 exit 1. `jq`, `fd` 같은 현대 도구는 빈 검색 결과를 0으로 처리한다.[^1]
- 읽기처럼 보이는 명령이 네트워크 요청이나 파일 쓰기 같은 부작용을 가지면 CI나 파이프라인에서 장애 원인이 된다. stdin TTY 감지로 대화형 환경에서만 부작용을 허용한다.[^1]
- 빈 결과 메시지는 "끝"이 아니라 "다음 단계"를 안내해야 한다. multi-word 쿼리를 단어 단위로 재검색해 힌트를 제시하는 방식이 효과적이다.[^1]
- category 필터 같은 기능은 단위 테스트로는 알 수 없는 사용 패턴이 직접 CLI를 써보면 드러난다. 단위 테스트는 "알고 있는 조건"을 검증하고, CLI 테스트는 "몰랐던 사용 패턴"을 발견한다.[^1]

## Examples / Code

**TTY 감지 출력 자동 선택 (from source)**

```rust
fn get_format(pretty: bool, json: bool, yaml: bool) -> Format {
    if pretty { Format::Pretty }
    else if json { Format::Json }
    else if yaml { Format::Yaml }
    else if atty::is(atty::Stream::Stdout) { Format::Pretty }
    else { Format::Yaml }
}
```

**exit code 결정 기준 (from source)**

| 동작 | exit code | 이유 |
|------|-----------|------|
| search 빈 결과 | 0 | 탐색형 — "없음"이 정상 응답 |
| category 빈 결과 | 0 | 탐색형 |
| info 도구 없음 | 1 | 조회형 — 대상이 있어야 한다 |
| compare 모두 없음 | 1 | 조회형 |
| 인덱스 파일 없음 | 1 | 시스템 상태 에러 |
| 인덱스 없음 (대화형) | 0 | 자동 다운로드 후 성공 |

**대화형 여부에 따른 자동 다운로드 분기 (from source)**

```rust
if atty::is(atty::Stream::Stdin) {
    // 대화형: 자동 다운로드
    eprintln!("Index not found. Downloading...");
    let count = index::update_index().await?;
    eprintln!("Index downloaded: {count} tools");
    index::load_index()
} else {
    // 비대화형 (CI, 파이프): 에러 메시지만
    Err(format!(
        "Index not found at {}. Run `clidex update` first.",
        config::index_path().display()
    ))
}
```

**빈 결과 힌트 제공 패턴 (from source)**

```rust
fn suggest_on_empty(query: &str, tools: &[Tool]) {
    eprintln!("No tools found for: {query}");
    let words: Vec<&str> = query.split_whitespace().collect();
    if words.len() > 1 {
        for word in &words {
            if word.len() <= 2 { continue; }
            let partial = search::search(tools, word, 3);
            if !partial.is_empty() {
                let names: Vec<&str> = partial.iter()
                    .map(|r| r.tool.name.as_str()).collect();
                eprintln!("  Tip: try `clidex \"{word}\"` → {}", names.join(", "));
                return;
            }
        }
    }
    eprintln!("  Tip: try broader terms or `clidex --categories` to browse");
}
```

## Connections

- [[clidex]] — 이 패턴들이 실제로 구현된 CLI 도구

## Footnotes

[^1]: content/Projects/Clidex/04-CLI-UX-Design.md
