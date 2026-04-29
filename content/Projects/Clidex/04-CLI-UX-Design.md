---
title: "Clidex CLI UX 설계: 좋은 엔진을 좋은 제품으로 바꾸는 마지막 20%"
date: 2026-04-07
modified: 2026-04-07
tags:
  - Projects
  - Rust
  - CLI
  - AI-Agent
  - UX
  - API-Design
draft: false
enableToc: true
description: "TTY 감지 기반 출력 전환, score 출력 스키마 설계, exit code 의미 분리, 자동 다운로드의 부작용 관리까지 - CLI에서 사용성은 기능 추가가 아니라 설계 규칙과 계약의 문제다."
summary: |
  [이전 글](/projects/clidex/03-search-quality-hardening)에서 검색 알고리즘의 구조적 문제를 수정하고, 5,277개 실제 인덱스 기반 테스트를 추가했다. 검색 엔진 자체의 품질은 올라갔지만, 실제로 써보면 다른 종류의 문제가 남아 있었다 - 첫 실행에서 에러로 끊기고, 출력 포맷이 사용자에 맞지 않고, 빈 결과에서 다음 행동을 모르고, 파이프라인에서 의도치 않게 중단된다.
  
  이 글은 CLI에서 사용성이 기능 목록이 아니라 **설계 규칙과 출력 계약**의 문제라는 관점에서, 네 가지 설계 판단을 기록한다.
published: 2026-04-07
---
---

## 문제 제기: 검색이 좋아도 못 쓰면 소용없다

03편까지의 작업은 검색 엔진 내부에 집중했다. BM25 가중치, fuzzy anchor threshold, synonym gate, edit distance. 결과적으로 5,277개 도구 인덱스에서 34/34 recall, 10/10 실제 인덱스 테스트를 달성했다.

하지만 검색 품질과 사용자 경험은 다른 축이다. 실제 사용 경로를 점검하면서 발견한 문제들:

1. **첫 실행이 끊긴다** - 설치 후 바로 `clidex "json"`을 치면, 인덱스 파일이 없다며 에러 메시지를 뿌리고 멈춘다. `clidex update`를 먼저 실행해야 한다는 걸 사용자가 알아서 파악해야 한다.

2. **사람과 에이전트가 같은 기본 출력을 쓴다** - YAML이 기본인데, 사람에게는 읽기 어렵고, 에이전트에게는 적절하다. 둘 다 만족시킬 수 없는 구조.

3. **빈 결과에서 멈춘다** - `No tools found for: csv` 한 줄이 끝이다. 다음에 뭘 해야 하는지 알 수 없다.

4. **파이프라인에서 예상치 못하게 중단된다** - 빈 결과가 exit code 1이라서, `set -e` 환경에서 스크립트가 깨진다.

이 문제들은 검색 알고리즘을 더 개선해도 해결되지 않는다. **CLI의 동작 규칙과 출력 계약**을 설계해야 한다.

---

## 사례 1: 사람과 에이전트의 출력 기본값 충돌

### 상황

Clidex의 tagline은 "CLI tool discovery **for AI agents**"다. 에이전트가 파싱할 수 있도록 YAML을 기본 출력으로 잡았다.

```bash
$ clidex "json processor"
- name: jq
  desc: JSON processor
  category: Data Manipulation > Processors
  tags:
  - json
  - processor
  - jq
  install:
    brew: brew install jq
  # ... 10개 결과 × 15줄 = 150줄의 YAML
```

문제: 사람이 터미널에서 이걸 읽고 싶지는 않다. `--pretty`를 붙여야 하지만, 그게 기본이 아니니까 첫 경험이 나쁘다.

그렇다고 pretty를 기본으로 바꾸면, `clidex "json" | jq ...` 같은 에이전트 파이프라인이 깨진다.

### 해결: stdout이 어디로 가는지 물어본다

```rust
fn get_format(pretty: bool, json: bool, yaml: bool) -> Format {
    if pretty {
        Format::Pretty
    } else if json {
        Format::Json
    } else if yaml {
        Format::Yaml
    } else if atty::is(atty::Stream::Stdout) {
        Format::Pretty // 터미널 → 사람이 보고 있다
    } else {
        Format::Yaml   // 파이프/리다이렉션 → 기계가 읽는다
    }
}
```

`atty::is(atty::Stream::Stdout)`로 stdout이 터미널인지 파이프인지 감지한다:
- **터미널에서 직접 실행** → pretty (사람에게 맞춤)
- **파이프로 연결** (`clidex "json" | jq`) → YAML (에이전트에게 맞춤)
- **명시적 플래그** (`--yaml`, `--json`, `--pretty`) → 항상 우선

이 패턴은 `ls`(터미널에서는 컬럼 출력, 파이프에서는 한 줄씩), `grep`(터미널에서는 색상, 파이프에서는 plain text)과 같은 UNIX 관례다. 새로운 아이디어가 아니라 검증된 규칙을 따른 것이다.

### 결과

```bash
# 터미널에서 - 사람이 읽기 좋은 포맷
$ clidex "json processor"
  jq                ★ 34.0k  Data Manipulation > Processors
  JSON processor
  $ brew install jq

# 파이프로 - 에이전트가 파싱할 수 있는 포맷
$ clidex "json processor" | head -3
- name: jq
  desc: JSON processor
  category: Data Manipulation > Processors
```

같은 명령어인데 출력이 다르다. 처음 보면 혼란스럽지만, 실제로 쓰면 각 상황에서 기대하는 것과 정확히 일치한다.

---

## 사례 2: score를 넣는 순간 생기는 출력 계약 문제

### 상황

AI 에이전트가 검색 결과를 받으면, "이 결과를 얼마나 신뢰할 수 있는가?"를 판단해야 한다. 10개 결과가 모두 같은 구조로 나오면, 순서만 보고 추측해야 한다. relevance score를 노출하면 이 판단이 정확해진다.

첫 번째 구현은 단순했다 - `--score` 플래그가 있으면 `Tool` 객체에 `score` 필드를 주입:

```rust
// 첫 번째 구현: Tool 객체에 score 주입
let mut v = serde_json::to_value(&r.tool).unwrap_or_default();
if let Some(obj) = v.as_object_mut() {
    obj.insert("score".to_string(), serde_json::json!(r.score));
}
```

### 문제: 출력 계약이 흔들린다

이렇게 하면 같은 검색 결과라도 `--score` 유무에 따라 스키마가 달라진다. 더 중요한 것은, `info`/`compare`/`trending`은 순수 `Tool` 스키마를 반환하는데, `search`만 `Tool + score` 혼합 스키마를 반환하게 된다.

에이전트 파서 입장에서는 이런 상황이 발생한다:

```python
# 이 코드가 search에서는 되고 info에서는 안 되는 건 왜?
result = yaml.safe_load(output)
for tool in result:
    if tool.get("score", 0) > 50:  # info 결과에는 score가 없다
        install(tool["install"]["brew"])
```

`score`는 `Tool`의 속성이 아니다. `Tool`은 도구의 정적 메타데이터고, `score`는 특정 쿼리에 대한 검색 엔진의 판단이다. 이 둘을 같은 객체에 섞으면 의미가 오염된다.

### 해결: SearchResult 래퍼로 분리

```rust
#[derive(serde::Serialize)]
struct SearchResultOutput<'a> {
    score: f64,
    #[serde(flatten)]
    tool: &'a Tool,
}
```

- `--score` 있으면: `{score: 67.8, name: "jq", desc: "...", ...}` - score가 최상위 필드로 먼저 나오고, Tool 필드가 flatten
- `--score` 없으면: `{name: "jq", desc: "...", ...}` - 순수 `Tool` 스키마, info/compare와 동일

```json
// --score 있을 때
[{"score": 67.8, "name": "jq", "desc": "JSON processor", ...}]

// --score 없을 때 (info, compare, trending과 동일한 스키마)
[{"name": "jq", "desc": "JSON processor", ...}]
```

규칙: **`--score`를 쓰지 않는 한, 모든 출력 경로에서 스키마가 동일하다.** 에이전트는 하나의 파서로 모든 명령의 결과를 처리할 수 있다.

---

## 사례 3: 빈 결과와 exit code는 무엇을 의미해야 하는가

### 상황

이전 코드에서 검색 결과가 없으면:

```rust
if results.is_empty() {
    eprintln!("No tools found for: {query}");
    std::process::exit(1);
}
```

exit code 1은 "에러"다. 하지만 `clidex "blockchain mining rig"`에서 빈 결과는 에러인가? 도구가 없다는 것 자체가 올바른 응답이다.

실제 문제는 파이프라인에서 발생한다:

```bash
set -e  # 대부분의 CI 스크립트에 있는 설정
RESULT=$(clidex "csv to json" --yaml)
# 결과가 비면 exit 1 → 스크립트 전체 중단
```

### 판단: 동작의 성격에 따라 나눈다

| 동작 | exit code | 이유 |
|------|-----------|------|
| `search` (빈 결과) | **0** | "검색했는데 없었다"는 정상적 응답 |
| `--category` (빈 결과) | **0** | 카테고리 브라우징도 마찬가지 |
| `trending` (빈 결과) | **0** | 조건에 맞는 도구가 없을 뿐 |
| `info foo` (도구 없음) | **1** | 정확한 조회 - "foo"라는 도구는 **있어야** 한다 |
| `compare foo bar` (둘 다 없음) | **1** | 마찬가지로 정확한 조회 |
| 인덱스 파일 없음 | **1** | 시스템 상태 에러 |

기준: **"결과 집합이 비었을 수 있는 동작"은 0, "특정 대상을 지목하는 동작"은 1.**

`grep`이 같은 규칙을 쓴다. `grep "pattern" file`에서 매칭 라인이 없으면 exit 1이지만, 이건 "파일을 열 수 없다"(exit 2)와 구분된다. 다만 `grep`의 exit 1은 논쟁이 많은 설계이고, 검색형 CLI에서는 빈 결과를 0으로 처리하는 쪽이 `jq`, `fd` 같은 현대 도구의 관례에 가깝다.

### 빈 결과에 다음 행동을 제안한다

exit code를 0으로 바꿨으면, 빈 결과 메시지가 "끝"이 아니라 "다음 단계"를 안내해야 한다:

```rust
fn suggest_on_empty(query: &str, tools: &[Tool]) {
    eprintln!("No tools found for: {query}");

    // multi-word 쿼리면 단어 하나씩 재검색 시도
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

```bash
$ clidex "nonexistent json tool"
# json이 매칭되므로 결과가 나옴

$ clidex "xyzzyplugh42"
No tools found for: xyzzyplugh42
  Tip: try broader terms or `clidex --categories` to browse
```

`info`에서는 fuzzy 검색으로 유사 도구를 제안한다:

```bash
$ clidex info ripgrpe
Tool not found: ripgrpe
  Did you mean: ripgrep
```

---

## 사례 4: 자동 다운로드는 편의인가, 부작용인가

### 상황

Clidex를 설치하고 바로 `clidex "json"`을 치면:

```
Error: Index not found at /home/user/.clidex/index.yaml.
Run `clidex update` to download it.
```

첫 경험이 에러 메시지다. README를 다시 읽어야 하고, `clidex update`를 먼저 실행해야 한다. 온보딩 실패의 전형적 패턴.

자연스러운 해결: **인덱스가 없으면 자동으로 다운로드한다.**

### 첫 번째 구현: 무조건 자동

```rust
async fn load_or_download() -> Result<Index, String> {
    match index::load_index() {
        Ok(i) => Ok(i),
        Err(_) if !config::index_path().exists() => {
            eprintln!("Index not found. Downloading...");
            let count = index::update_index().await?;
            eprintln!("Index downloaded: {count} tools");
            index::load_index()
        }
        Err(e) => Err(e),
    }
}
```

### 문제: 검색 명령이 상태를 바꾼다

겉으로 보면 `clidex "json"`은 읽기 명령이다. 하지만 이 구현에서는:
1. 네트워크 요청을 보내고
2. 파일 시스템에 ~2MB 파일을 쓰고
3. 디렉토리를 생성한다

**읽기처럼 보이는 명령이 쓰기 부작용을 가진다.** 이게 대화형 터미널에서는 편리하지만, CI나 파이프라인에서는 위험하다:

```bash
# CI에서 실행 - 인덱스 파일이 없으면 네트워크 호출 시도
# 네트워크 차단된 환경이면 타임아웃으로 빌드 지연
docker run --network=none myapp clidex "json"
```

### 해결: 대화형 여부에 따라 분기

```rust
async fn load_or_download() -> Result<Index, String> {
    match index::load_index() {
        Ok(i) => Ok(i),
        Err(_) if !config::index_path().exists() => {
            if atty::is(atty::Stream::Stdin) {
                // 대화형 터미널 - 자동 다운로드
                eprintln!("Index not found. Downloading...");
                let count = index::update_index().await?;
                eprintln!("Index downloaded: {count} tools");
                index::load_index()
            } else {
                // 비대화형 (CI, 파이프) - 에러 메시지만
                Err(format!(
                    "Index not found at {}. Run `clidex update` first.",
                    config::index_path().display()
                ))
            }
        }
        Err(e) => Err(e),
    }
}
```

판단 기준: **"사용자가 화면 앞에 있는가?"** `atty::is(atty::Stream::Stdin)`이 true면 대화형, false면 자동화 환경이다.

| 환경 | stdin TTY | 동작 |
|------|-----------|------|
| 터미널에서 직접 실행 | true | 자동 다운로드 + 진행 표시 |
| CI/Docker | false | 에러 메시지 + 명시적 `clidex update` 안내 |
| `echo "json" \| clidex` | false | 에러 메시지 |
| 스크립트 내 실행 | false | 에러 메시지 |

`git`도 비슷한 판단을 한다 - `git commit`이 에디터를 여는 건 대화형일 때만이고, 비대화형에서는 `-m` 플래그가 없으면 에러다.

---

## 보조 사례: category 필터를 false positive 없이 넓히기

category 필터는 코드 한 줄이지만, 세 번 진화했다.

### 1단계: substring (`contains`)

```rust
tools.filter(|t| t.category.to_lowercase().contains(&cat_lower))
```

"File"로 필터하면 "**File** Management"도 매치하지만 "Text **File**rs"도 매치한다. 사용자가 `--category File`을 쓸 때 "Text Filters"가 나오리라 기대하지는 않는다.

### 2단계: word-prefix 매칭

```rust
tool_cat == cat_lower
    || tool_cat.starts_with(&format!("{} > ", cat_lower))  // 계층 prefix
    || tool_cat.starts_with(&format!("{} ", cat_lower))    // 단어 prefix
```

"File" → "File Management"은 매치, "Text Filters"는 매치 안 됨. false positive 제거 완료.

하지만 `--category docker`로 "Development > Docker"를 찾을 수 없다. "docker"는 카테고리 이름의 시작이 아니라 끝이니까.

### 3단계: leaf segment 매칭 (CLI 테스트에서 발견)

```rust
tool_cat == cat_lower
    || tool_cat.starts_with(&format!("{} > ", cat_lower))
    || tool_cat.starts_with(&format!("{} ", cat_lower))
    // 3단계 추가: 마지막 세그먼트 매칭
    || tool_cat.ends_with(&format!(" > {}", cat_lower))
    || tool_cat.rsplit(" > ").next()
        .is_some_and(|leaf| leaf.starts_with(&cat_lower))
```

이 세 번째 조건은 단위 테스트에서는 발견할 수 없었다. **CLI로 직접 `--category docker`를 쳐보고 결과가 비어있는 걸 확인한 뒤** 추가한 것이다. 2단계에서 추가한 단위 테스트(`filter_category_no_false_positive`)가 이 변경이 기존 동작을 깨지 않는다는 걸 보장했다.

교훈: 단위 테스트는 "알고 있는 조건"을 검증하고, CLI 테스트는 "몰랐던 사용 패턴"을 발견한다. 둘 다 필요하다.

---

## 부수적 개선들

위 네 가지가 설계 판단의 핵심이고, 나머지는 같은 맥락에서 자연스럽게 따라온 것들이다:

### 검색 결과에 install 명령 노출

pretty 출력에서 install 명령을 직접 보여준다. 기존에는 `clidex info jq`를 추가로 쳐야 했다.

```
  jq                ★ 34.0k  Data Manipulation > Processors
  JSON processor
  $ brew install jq    ← 이 줄이 추가됨
```

### description 터미널 너비 제한

`terminal_size` crate로 터미널 너비를 감지하고, 긴 description을 truncation한다. 기존에는 200자짜리 description이 한 줄로 쏟아졌다.

### `search` 서브커맨드

`clidex "csv"`와 `clidex search "csv"`를 둘 다 지원한다. positional query는 축약형으로 유지하고, `search`는 `--category`와 조합할 때 더 명시적이다.

```bash
clidex search "monitor" --category system -n 5
```

### `categories` 서브커맨드

`clidex categories git`으로 카테고리 이름을 필터링할 수 있다. 173개 카테고리 전체 목록에서 원하는 것을 찾기 쉬워졌다.

### `trending --updated-since`

기존 `trending`은 전체 stars 순이라 "역대 인기 도구"였다. `--updated-since 2026-01-01`로 최근 활동 있는 도구만 필터링할 수 있다. 이름은 처음에 `--since`였지만, "인기 성장률"이 아니라 "repo 활동 날짜 필터"라는 실제 의미를 반영하여 `--updated-since`로 변경했다.

---

## 결과

### 변경 범위

| 파일 | 변경 | 핵심 |
|------|------|------|
| `main.rs` | 전면 재작성 | TTY 감지, 자동 다운로드, exit code, 서브커맨드 |
| `output.rs` | 전면 재작성 | SearchResultOutput 래퍼, install 노출, 너비 제한 |
| `search.rs` | category 필터 확장 | leaf segment 매칭, 단위 테스트 추가 |
| `Cargo.toml` | 의존성 추가 | `terminal_size`, `atty` |
| `README.md` | 재작성 | quickstart, 수치 통일, 새 기능 문서화 |

### exit code 규칙

| 동작 | exit code | 이전 |
|------|-----------|------|
| search 빈 결과 | **0** | 1 |
| category 빈 결과 | **0** | 1 |
| trending 빈 결과 | **0** | 1 |
| info 도구 없음 | **1** | 1 (동일) |
| compare 모두 없음 | **1** | 1 (동일) |
| 인덱스 파일 없음 (비대화형) | **1** | 1 (동일) |
| 인덱스 파일 없음 (대화형) | **0** (자동 다운로드) | 1 |

### 출력 스키마 규칙

| 조건 | 스키마 |
|------|--------|
| `--score` 없이 모든 명령 | `[Tool]` - 동일 |
| `--score` 있을 때 search | `[{score, ...Tool}]` - 래퍼 |

---

## 회고

### 1. TTY 감지는 "두 명의 사용자"를 한 번에 해결한다

사람과 에이전트의 기본값이 충돌할 때, 둘 중 하나를 고르는 대신 **"지금 누가 쓰고 있는가?"를 묻는다.** `isatty`는 30년 된 UNIX 함수지만, 이 결정 하나로 `--pretty` 플래그를 치는 빈도가 사실상 0이 된다.

### 2. 출력 스키마는 API 계약이다

CLI 도구의 stdout은 API의 response body와 같다. 플래그 하나에 따라 스키마가 바뀌면, 그걸 파싱하는 모든 코드가 분기를 추가해야 한다. `--score` 없이 `[Tool]`, 있으면 `[{score, ...Tool}]`이라는 규칙은 **"기본은 호환, 추가는 확장"** 원칙을 따른다.

### 3. exit code는 에러가 아니라 동작의 성격을 표현한다

"빈 결과가 에러인가?"라는 질문에 대한 답은, 명령이 "탐색"인지 "조회"인지에 따라 달라진다. 이걸 전역 규칙으로 잡으면 반드시 한쪽이 어색해진다. 명령별로 의미를 구분하는 게 맞다.

### 4. 자동 동작은 사용자가 보고 있을 때만 안전하다

"읽기 명령이 쓰기 부작용을 가진다"는 건 대화형에서는 편의지만, 자동화 환경에서는 장애 원인이 된다. `git`이 에디터를 여는 것, `npm`이 경고를 출력하는 것, 모두 대화형/비대화형을 구분하는 이유가 있다.

### 5. CLI 테스트는 단위 테스트와 다른 것을 발견한다

category 필터의 leaf segment 매칭은 단위 테스트에서 나올 수 없었다. 테스트 케이스를 쓰려면 먼저 문제를 알아야 하는데, 이 문제는 **`--category docker`를 직접 쳐보고 빈 결과를 보기 전에는 모르는 문제**였다.

---

## 다음 단계

- **build_index.rs 모듈 분리** - 2,464줄 단일 파일이 전체 코드의 61%. 데이터 소스별 모듈로 분리 필요
- **scoring 함수 분리** - 250줄 단일 함수에 12개 시그널이 혼재. 단위 테스트가 생겼으니 안전하게 분리 가능
- **`.expect()` 제거** - output.rs의 직렬화 `.expect()` 6개를 `Result` 전파로 교체
- **인덱스 로딩 성능** - 5,277개 도구 인덱스 YAML 파싱에 ~200ms. memory-mapped file이나 binary format 검토

---

- GitHub: [syshin0116/clidex](https://github.com/syshin0116/clidex)
