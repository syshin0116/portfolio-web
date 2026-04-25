---
title: JS 함수 최적화
date: 2024-07-03
tags:
- javascript
- optimization
- code-refactoring
- web-development
draft: false
enableToc: true
description: 자바스크립트 함수 최적화 방법과 실제 코드 개선 사례를 분석하고, 코드 가독성과 성능을 향상시키는 기법 소개
summary: "자바스크립트 함수를 최적화하는 방법을 실제 코드 사례를 통해 알아본다. var/let/const의 적절한 사용, 불필요한 변수 제거, 간결한 조건문 작성 등의 기법을 적용하여 코드 가독성과 성능을 모두 향상시키는 방법을 소개한다. 추가로 자바스크립트의 동등 비교 연산자(===, ==)와 값 비교 방식에 대한 심층 분석도 다룬다."
published: 2024-07-03
modified: 2024-07-03
---
## 개요

코드 개선은 소프트웨어 개발에서 중요한 부분이다. 특히 자바스크립트와 같은 동적 언어에서는 작은 문법적 개선이 가독성과 성능에 큰 영향을 미칠 수 있다. 이 문서에서는 실제 코드를 분석하고 개선하는 과정을 통해 자바스크립트 함수 최적화 방법을 살펴본다.

---

## 원본 코드 분석

다음은 최적화가 필요한 원본 코드이다:

```javascript
var setFirstEmptyInput = function(new_value) {
	var found = false;
	var i = 1;
	var elem = document.getElementById('input' + i);
	while (elem !== null) {
	   if (elem.value === '') {
		  found = true;
		  break;
	   }
	   i++;
	   elem = document.getElementById('input' + i);
	}
	if (found) elem.value = new_value;
	return elem;
};
```

이 함수는 `input1`, `input2`, ... 형식의 ID를 가진 입력 요소들을 순차적으로 검사하여 값이 비어있는 첫 번째 입력 요소를 찾고, 해당 요소에 새 값을 설정한다.

### 코드의 문제점

1. **불필요한 변수 사용**: `found` 변수는 실제로 필요하지 않다
2. **비효율적인 로직**: 조건을 만족할 때 바로 반환하지 않고 루프를 계속 진행
3. **오래된 변수 선언 방식**: ES6에서 도입된 `let`과 `const` 대신 `var` 사용
4. **에러 처리 부족**: 모든 입력 요소가 값을 가질 경우의 처리가 명확하지 않음

---

## 코드 개선 사항

코드를 개선할 때 고려해야 할 주요 사항은 다음과 같다:

### 1. 변수 선언 방식 개선

- `var` 대신 `const`와 `let` 사용
  - `const`: 재할당이 필요 없는 변수
  - `let`: 값이 변경되는 변수

### 2. 불필요한 변수 제거

- `found` 변수는 제거하고 조건을 만족할 때 바로 값을 설정하고 반환

### 3. 코드 간결화

- 반복문 내에서 요소를 찾고 조건을 확인하는 로직을 더 간결하게 작성
- 템플릿 리터럴을 사용하여 문자열 연결 개선

### 4. 명확한 반환 값 설정

- 모든 입력 요소가 값을 가질 경우 `null`을 반환하여 실패를 명시적으로 표시

---

## 개선된 코드

위의 고려 사항을 반영한 개선된 코드는 다음과 같다:

```javascript
const setFirstEmptyInput = function(new_value) {
    let i = 1;
    let elem;
    while (elem = document.getElementById(`input${i++}`)) {
        if (elem.value === '') {
            elem.value = new_value;
            return elem;
        }
    }
    return null;
};
```

### 개선 사항 설명

1. **변수 선언 개선**:
   - 함수 자체는 `const`로 선언하여 재할당 방지
   - 반복 변수는 `let`으로 선언하여 변경 가능하게 설정

2. **로직 간결화**:
   - 조건을 만족하는 요소를 찾으면 바로 값을 설정하고 반환
   - `while` 조건에서 요소 할당과 `null` 체크를 동시에 수행

3. **템플릿 리터럴 사용**:
   - `'input' + i` 대신 ``input${i}`` 사용

4. **명확한 실패 처리**:
   - 모든 요소가 값을 가질 경우 `null` 반환

---

## 자바스크립트 비교 연산자 심층 분석

함수 최적화와 관련하여 자바스크립트의 비교 연산자에 대한 이해가 중요하다. 특히 `===`(엄격한 동등) 연산자와 관련된 주요 개념을 살펴보자.

### === 연산자(엄격한 동등 비교)

- **동작 방식**: 값과 타입 모두 비교
- **타입 변환**: 수행하지 않음
- **사용 예**: `5 === '5'` → `false` (숫자 5와 문자열 '5'는 다른 타입)

### 주요 값 비교 개념

#### 빈 문자열('')
- **타입**: `string`
- **불리언 평가**: `false`
- **비교 결과**: `'' === null` → `false`, `'' === undefined` → `false`

#### null
- **의미**: 값의 부재를 명시적으로 표시
- **타입**: `object` (자바스크립트의 역사적 버그)
- **불리언 평가**: `false`
- **비교 결과**: `null === undefined` → `false`

#### undefined
- **의미**: 값이 할당되지 않은 상태
- **타입**: `undefined`
- **불리언 평가**: `false`
- **비교 결과**: `undefined === null` → `false`

### 주요 비교 결과표

| 비교 | === | == |
|------|-----|-----|
| `null` vs `undefined` | `false` | `true` |
| `''` vs `null` | `false` | `false` |
| `''` vs `undefined` | `false` | `false` |
| `0` vs `''` | `false` | `true` |
| `false` vs `''` | `false` | `true` |

### 모범 코딩 사례

- **타입 안전성이 중요할 때**: `===` 사용 (권장)
- **값의 존재 여부 확인**: `null`과 `undefined` 구분 필요시 주의
- **빈 문자열 체크**: 명시적으로 `=== ''` 사용

---

## 대안적 구현 방식

다음은 또 다른 개선된 구현 방식으로, 더 명시적인 코드 구조를 가지고 있다:

```javascript
const setFirstEmptyInput = function(new_value) {
	for (let i = 1; ; i++) {
		const elem = document.getElementById(`input${i}`);
    
    if (elem === null) {
	    return null;
    }

    if (elem.value === '') {
	    elem.value = new_value;
      return elem;
    }
	}
};
```

### 특징

- 무한 `for` 루프 사용 (종료 조건은 내부에서 처리)
- 각 조건을 별도의 `if` 블록으로 명확하게 분리
- 요소가 없을 때와 값이 비어있을 때의 처리를 명시적으로 구분

---

## 결론

자바스크립트 함수 최적화는 코드의 가독성, 유지보수성, 그리고 성능을 모두 향상시킬 수 있다. 이 문서에서 살펴본 주요 최적화 기법을 요약하면:

1. **최신 문법 활용**: ES6+의 `const`, `let`, 템플릿 리터럴 등 사용
2. **불필요한 코드 제거**: 중복되거나 사용되지 않는 변수와 로직 제거
3. **간결하면서도 명확한 로직**: 조건 충족 시 즉시 결과 반환
4. **엄격한 비교 연산자 사용**: 타입 안전성을 위해 `===` 사용
5. **명확한 에러 처리**: 실패 시 명시적인 값(`null` 등) 반환

이러한 기법들을 일관되게 적용하면 더 견고하고 효율적인 자바스크립트 코드를 작성할 수 있다. 특히 [[Monkey Patching]]과 같은 다른 최적화 기법들과 함께 사용할 때 그 효과가 더욱 두드러진다. 