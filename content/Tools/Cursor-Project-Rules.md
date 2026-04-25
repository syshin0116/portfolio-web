---
title: Cursor Project Rules로 AI 코딩 어시스턴트 맞춤화하기
date: 2025-04-07
tags:
- cursor
- ai
- coding-assistant
- project-rules
- cursor-ai
draft: false
enableToc: true
description: Cursor에서 Project Rules 기능을 활용하여 AI 응답을 프로젝트별로 맞춤화하는 방법을 알아본다.
summary: "Cursor의 Project Rules 기능을 통해 AI 코딩 어시스턴트의 행동을 맞춤 설정할 수 있다. 프로젝트별 규칙, 글로벌 규칙을 통해 AI가 코드를 생성하고 이해하는 방식을 정밀하게 제어할 수 있다."
published: 2025-04-07
modified: 2025-04-07
---
## Cursor Rules 소개

Cursor는 AI 기반 코딩 에디터로, 개발자가 코드를 작성하고 이해하는 과정을 돕는다. Cursor의 핵심 기능 중 하나는 AI의 행동을 사용자의 필요에 맞게 조정할 수 있는 'Rules for AI' 시스템이다. 이 시스템을 통해 사용자는 LLM(대규모 언어 모델)이 코드를 생성하고 이해하는 방식에 대한 지침을 제공할 수 있다.

Cursor에서 Rules for AI를 구현하는 방법은 크게 두 가지가 있다:

1. **Project Rules** - 프로젝트 특화 규칙으로, `.cursor/rules` 디렉토리에 저장
2. **Global Rules** - 모든 프로젝트에 적용되는 전역 규칙

이전에는 프로젝트 루트에 `.cursorrules` 파일을 사용하는 방법도 있었지만, Cursor 팀은 가장 유연하고 강력한 Project Rules 사용을 권장한다.

---

## Project Rules 시스템 이해하기

Project Rules 시스템은 경로별 구성을 통해 강력하고 유연한 시스템을 제공한다. 이 규칙들은 `.cursor/rules` 디렉토리에 저장되며, 프로젝트의 다양한 부분에서 AI 동작을 세밀하게 제어할 수 있게 해준다.

### Project Rules의 주요 특징

- **의미론적 설명**: 각 규칙은 적용되어야 하는 시점에 대한 설명을 포함할 수 있다
- **파일 패턴 매칭**: glob 패턴을 사용하여 규칙이 적용될 파일/폴더를 지정
- **자동 첨부**: 매칭되는 파일을 참조할 때 규칙이 자동으로 포함됨
- **파일 참조**: 규칙이 적용될 때 컨텍스트로 포함될 파일을 `@file`로 참조 가능
- **여러 규칙 연결**: `@file`을 사용하여 여러 규칙을 연결할 수 있음
- **버전 제어 가능**: 일반 파일이므로 Git 등의 버전 관리 시스템에서 관리 가능

### 새 Project Rule 생성 방법

새 규칙을 만들려면 명령 팔레트(Command Palette)를 사용한다:

1. `Cmd + Shift + P` 단축키로 명령 팔레트 열기
2. "New Cursor Rule" 명령 선택
3. 규칙 내용 작성 및 저장

---

## Project Rules 활용 사례

Project Rules는 다양한 상황에서 유용하게 활용될 수 있다:

### 1. 프레임워크별 맞춤 설정

특정 프레임워크에 맞는 코드 생성을 위해 파일 유형별로 규칙을 설정할 수 있다:

```
// .cursor/rules/react-components.md
다음 파일 패턴에 적용: *.tsx, *.jsx

React 컴포넌트를 작성할 때 다음 규칙을 따라야 한다:
1. 함수형 컴포넌트만 사용한다
2. React.memo()를 활용하여 성능을 최적화한다
3. 모든 props는 명시적 타입을 가져야 한다
4. hooks는 컴포넌트 상단에 배치한다
```

### 2. 자동 생성 파일 처리

자동 생성된 파일에 대한 특별한 처리를 지정할 수 있다:

```
// .cursor/rules/proto-files.md
다음 파일 패턴에 적용: *.proto

protobuf 파일은 자동 생성되므로 직접 수정하지 말고, 
원본 스키마를 수정한 후 재생성해야 한다.
```

### 3. UI 개발 패턴

일관된 UI 개발을 위한 패턴을 정의할 수 있다:

```
// .cursor/rules/ui-components.md
다음 파일 패턴에 적용: components/ui/*.tsx

UI 컴포넌트 개발 시 다음 패턴을 따른다:
1. 컴포넌트는 atomic design 원칙을 따른다
2. 모든 스타일은 tailwind CSS를 사용한다
3. 접근성(a11y) 지침을 준수한다
4. 다크 모드 지원을 위한 색상 변수를 사용한다
```

### 4. 코드 스타일 및 아키텍처 선호도

특정 폴더에 대한 코드 스타일과 아키텍처 선호도를 설정할 수 있다:

```
// .cursor/rules/backend-code.md
다음 파일 패턴에 적용: api/*, server/*

백엔드 코드 작성 시 다음 규칙을 따른다:
1. Repository 패턴을 사용한다
2. 의존성 주입을 활용한다
3. 예외 처리는 try-catch 블록으로 명시적으로 처리한다
4. 모든 외부 API 호출은 재시도 메커니즘을 구현한다
```

---

## 이 블로그를 위한 Project Rules 예시

이 Quartz 기반 블로그에서 사용할 수 있는 Project Rules 예시를 살펴보자. 이 규칙은 일관된 블로그 포스트 형식과 스타일을 유지하는 데 도움이 된다.

```markdown
// .cursor/rules/blog-posts.md
다음 파일 패턴에 적용: content/**/*.md

이 블로그 포스트 작성 시 다음 형식과 규칙을 따라야 한다:

1. 프론트매터 형식:
```yaml
---
title: [제목] (한국어)
date: YYYY-MM-DD
tags: 관련-키워드, 소문자-하이픈-구분
draft: false
enableToc: true
description: 본문 내용 간결 요약(문장형식)
published: YYYY-MM-DD
modified: YYYY-MM-DD
---
```

2. 시작 부분에 summary 블록 추가:
```markdown
> [!summary]
>
> Cursor의 Project Rules 기능을 통해 AI 코딩 어시스턴트의 행동을 맞춤 설정할 수 있다. 프로젝트별 규칙, 글로벌 규칙을 통해 AI가 코드를 생성하고 이해하는 방식을 정밀하게 제어할 수 있다.

3. 본문 구조:
- 내용에 맞는 자연스러운 섹션 구성
- 주요 섹션은 ## 사용
- 하위 섹션은 ### 사용
- 본문 중간중간 연관된 부분에 [[파일명]] 형식으로 백링크 추가
- 관련된 다른 글이나 개념에 [[파일명]] 형식으로 백링크 추가
- 필요시 코드 블록은 ```언어명 형식
- 중요 참고사항은 >[!Note] 블록
- 이미지는 ! 형식
- 각 주요 섹션 사이 --- 구분선 사용

4. 말투:
- '-입니다' 스타일 대신 '-이다' 스타일로 작성

5. 결론 섹션 포함:
- 내용 요약
- 활용 방안 제시
- 관련 문서 백링크

6. 카테고리별 문서 연결:
- 관련 주제가 있는 경우 content/AI/, content/Dev/, content/Tools/ 등의 관련 문서에 백링크 연결
```

```markdown
// .cursor/rules/code-examples.md
다음 파일 패턴에 적용: content/Dev/**/*.md, content/Tools/**/*.md

코드 예제 작성 시 다음 규칙을 따른다:

1. 모든 코드 블록은 언어 명시: ```javascript, ```python 등
2. 코드에 충분한 주석 포함
3. 실행 가능한 완전한 예제 제공
4. 복잡한 코드는 단계별로 설명
5. 코드 실행 결과도 함께 제시
```

> [!Note]
> Project Rules는 단순히 코드 스타일을 넘어 문서 형식, 블로그 포스트 구조 등 다양한 측면에 적용할 수 있다.

---

## Global Rules 활용하기

Global Rules는 모든 프로젝트에 적용되는 규칙으로, Cursor 설정에서 구성할 수 있다. 이는 출력 언어, 응답 길이 등 항상 포함되어야 하는 규칙을 지정할 때 유용하다.

### Global Rules 설정 방법

1. Cursor 설정 열기
2. 'General' > 'Rules for AI' 섹션으로 이동
3. 원하는 규칙 추가

### Global Rules 예시

```
항상 다음 규칙을 따른다:
1. 코드는 항상 한글 주석을 포함한다
2. 응답은 간결하게 작성한다
3. 솔루션을 제시할 때 항상 최소한 하나의 대안도 함께 제공한다
4. 최신 ECMAScript 문법을 사용한다
```

---

## .cursorrules 파일 (구버전 호환)

이전 버전의 Cursor와의 호환성을 위해 프로젝트 루트에 `.cursorrules` 파일을 사용할 수도 있었다. 하지만 이 방식은 미래에 제거될 예정이므로, 더 유연하고 제어력이 높은 Project Rules 시스템으로 마이그레이션하는 것이 좋다.

> [!Note]
> `.cursorrules` 파일은 곧 지원이 중단될 예정이므로, 새 프로젝트에서는 Project Rules 시스템을 사용하는 것이 좋다.

---

## 커뮤니티 리소스

Cursor 규칙에 관한 커뮤니티 리소스도 많이 있다. 그 중 하나는 [awesome-cursorrules](https://github.com/PatrickJS/awesome-cursorrules) 저장소로, 다양한 기술 스택과 프레임워크에 맞춘 `.cursorrules` 파일 모음을 제공한다.

이 저장소는 다음과 같은 카테고리의 규칙을 포함한다:

- 프론트엔드 프레임워크 및 라이브러리 (React, Next.js, Vue, Svelte 등)
- 백엔드 및 풀스택 개발 (Node.js, FastAPI, Django 등)
- 모바일 개발 (React Native, Flutter, SwiftUI 등)
- CSS 및 스타일링 (Tailwind, Chakra UI 등)
- 상태 관리 (Redux, MobX 등)
- 언어별 설정 (JavaScript, TypeScript, Python, Go 등)

이러한 커뮤니티 규칙을 참고하여 자신의 프로젝트에 맞는 규칙을 작성할 수 있다.

---

## 결론

Cursor의 Project Rules 시스템은 AI 코딩 어시스턴트의 동작을 세밀하게 제어할 수 있는 강력한 도구다. 프로젝트별, 파일 패턴별로 다양한 규칙을 설정함으로써 일관된 코드 스타일을 유지하고, 프로젝트의 특성에 맞는 코드 생성을 지원할 수 있다.

Project Rules를 효과적으로 활용하면 다음과 같은 이점을 얻을 수 있다:

1. 프로젝트 전반에 걸쳐 일관된 코딩 스타일 유지
2. 팀 내 코딩 관행 표준화
3. 반복적인 작업 자동화
4. 신규 팀원의 온보딩 시간 단축
5. 코드 품질 향상

Cursor를 사용한다면, Project Rules 시스템을 적극적으로 활용하여 AI 코딩 어시스턴트를 자신의 프로젝트에 맞게 최적화해보자.
