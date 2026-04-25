---
title: Monkey Patching
date: 2024-03-17
tags:
- python
- programming
- monkey-patching
- code-modification
- runtime
- debugging
draft: false
enableToc: true
description: 몽키 패칭(Monkey Patching)의 개념, 장단점, 활용 사례를 설명하고 런타임에 코드를 수정하는 기법의 실제 적용
  방법 소개
summary: "몽키 패칭(Monkey Patching)은 프로그램 실행 중에 코드를 동적으로 수정하거나 확장하는 강력한 기법이다. 라이브러리나 모듈의 함수를 직접 수정하지 않고도 그 동작을 변경할 수 있어 버그 수정, 기능 추가, 테스트 등에 유용하지만, 코드 가독성과 유지보수성을 해칠 수 있어 신중하게 사용해야 한다."
published: 2024-03-17
modified: 2024-03-17
---
## 개요

[google-play-scraper](https://github.com/JoMingyu/google-play-scraper) 사용법을 익히다가 해당 라이브러리의 문제점을 유저들이 `Monkey Patching` 기법을 사용해 피해가는 걸 보았다. 최근 진행중인 프로젝트에서도 라이브러리에서 제공하지 않는 기능들을 직접 추가해야 했는데, 몽키 패치를 사용하면 좀 더 간단하게 추가할 수 있었을 것 같다. 이 문서에서는 몽키 패칭의 개념, 사용법, 장단점을 살펴본다.

---

## Monkey Patch란?

몽키 패치(Monkey Patch)란 런타임에 기존의 코드를 수정하거나 확장하는 기법이다. 이를 통해 라이브러리나 모듈의 함수, 메서드, 속성 등을 직접 수정하지 않고도 동적으로 변경할 수 있다. 

### 몽키 패칭의 정의와 유래

'몽키 패치'라는 용어는 원래 'Guerrilla Patch'(게릴라 패치)에서 파생되었다. 이는 정규 업데이트 채널을 통하지 않고 코드를 변경하는 것을 의미했다. 시간이 지나면서 'Guerrilla'가 'Gorilla'로 잘못 발음되었고, 결국 'Monkey'로 변경되어 현재의 용어가 되었다.

### 언어별 지원 현황

몽키 패칭은 주로 동적 타입 언어에서 가능하며, 다음과 같은 언어들이 이를 지원한다:

- **Python**: 가장 널리 사용되며 런타임에 모든 객체를 수정할 수 있다
- **JavaScript**: 프로토타입 기반 언어로 객체와 함수를 쉽게 수정할 수 있다
- **Ruby**: 메타프로그래밍 기능을 통해 클래스와 메서드를 동적으로 수정할 수 있다
- **Objective-C**: 런타임에 메서드를 교체할 수 있는 메서드 스와핑(Method Swizzling) 지원

반면, Java나 C++ 같은 정적 타입 언어에서는 몽키 패칭이 훨씬 제한적이거나 불가능하다.

---

## 몽키 패치 활용 예시

### 기본 예시 (Python)

다음은 Python에서 몽키 패칭을 사용하는 간단한 예시다:

```python
# some_module.py에 있는 함수
def greet():
    return "안녕하세요, 세상!"

# 원본 함수 사용
print(greet())  # 출력: 안녕하세요, 세상!

# 몽키 패치를 사용한 함수 변경
def custom_greet():
    return "안녕하세요, 우주!"

# 함수를 몽키 패치로 교체
greet = custom_greet

# 변경된 함수 사용
print(greet())  # 출력: 안녕하세요, 우주!
```

### 클래스 메서드 패치하기

클래스의 메서드를 패치하는 예시:

```python
class Calculator:
    def add(self, a, b):
        return a + b
    
    def subtract(self, a, b):
        return a - b

# 원래 메서드 저장
original_add = Calculator.add

# 로깅 기능이 추가된 새로운 메서드
def add_with_logging(self, a, b):
    print(f"더하기 연산: {a} + {b}")
    return original_add(self, a, b)

# 메서드 패치
Calculator.add = add_with_logging

# 패치된 메서드 사용
calc = Calculator()
result = calc.add(5, 3)  # 출력: "더하기 연산: 5 + 3"
print(result)  # 출력: 8
```

### 서드파티 라이브러리 패치하기

외부 라이브러리의 버그를 수정하는 예시:

```python
# 예: requests 라이브러리의 세션 타임아웃 문제를 패치
import requests

# 원래 함수 저장
original_get = requests.get

# 타임아웃 값을 추가한 새 함수
def get_with_timeout(*args, **kwargs):
    if 'timeout' not in kwargs:
        kwargs['timeout'] = A10
    return original_get(*args, **kwargs)

# 함수 패치
requests.get = get_with_timeout

# 이제 모든 requests.get 호출은 자동으로 타임아웃이 설정됨
response = requests.get('https://example.com')
```

---

## 몽키 패칭의 장단점

### 장점

- **유연성**: 실행 중인 프로그램의 동작을 변경할 수 있어 다양한 상황에 대응할 수 있다.
- **버그 수정**: 서드파티 라이브러리의 버그를 임시로 수정할 때 유용하다.
- **기능 추가**: 기존 코드베이스에 새로운 기능을 추가하고 싶을 때 사용할 수 있다.
- **테스트 용이성**: 테스트를 위해 특정 부분의 동작을 변경하고자 할 때 활용된다.

### 단점

- **코드 추적 어려움**: 디버깅이 어려워지고 코드 흐름을 이해하기 어려워질 수 있다.
- **유지보수 문제**: 패치된 코드는 라이브러리 업데이트 시 작동하지 않을 수 있다.
- **예상치 못한 부작용**: 다른 코드에 의존성이 있는 경우 예상치 못한 문제가 발생할 수 있다.
- **가독성 저하**: 다른 개발자들이 코드를 이해하기 어렵게 만들 수 있다.

> [!Note]
> 몽키 패칭은 강력한 도구이지만, "권력에는 책임이 따른다"는 원칙을 항상 명심해야 한다. 특히 프로덕션 환경에서는 신중하게 사용해야 한다.

---

## 실용적인 활용 사례

### 테스트에서의 활용

테스트 코드에서는 몽키 패칭이 특히 유용하다:

```python
# 외부 API 호출을 시뮬레이션하는 테스트
import my_module
import unittest

class TestAPI(unittest.TestCase):
    def setUp(self):
        # 원래 함수 저장
        self.original_api_call = my_module.api_call
        
        # 테스트용 모의 함수
        def mock_api_call(endpoint, data):
            return {"status": "success", "data": "test data"}
        
        # 몽키 패치 적용
        my_module.api_call = mock_api_call
    
    def tearDown(self):
        # 테스트 후 원래 함수 복원
        my_module.api_call = self.original_api_call
    
    def test_process_data(self):
        result = my_module.process_data("test")
        self.assertEqual(result, "processed: test data")
```

### 성능 모니터링 추가

기존 함수에 성능 측정 코드 추가:

```python
import time
import important_module

# 원래 함수 저장
original_process = important_module.process_data

# 성능 측정 기능이 추가된 함수
def process_with_timing(*args, **kwargs):
    start_time = time.time()
    result = original_process(*args, **kwargs)
    elapsed = time.time() - start_time
    print(f"처리 시간: {elapsed:.4f}초")
    return result

# 몽키 패치 적용
important_module.process_data = process_with_timing
```

### 호환성 문제 해결

다른 환경에서의 호환성 문제 해결:

```python
# 특정 환경에서만 나타나는 라이브러리 호환성 문제 해결
import sys
import problematic_library

if sys.platform == 'win32':
    # Windows에서만 발생하는 문제를 패치
    original_function = problematic_library.function
    
    def fixed_function(*args, **kwargs):
        # Windows 환경에 맞게 수정된 로직
        # ...
        return modified_result
    
    problematic_library.function = fixed_function
```

---

## 안전한 몽키 패칭을 위한 가이드라인

몽키 패칭을 사용할 때는 다음 가이드라인을 따르는 것이 좋다:

1. **문서화**: 모든 몽키 패치는 명확하게 문서화하여 다른 개발자들이 이해할 수 있게 한다.
2. **범위 제한**: 패치의 범위를 최소한으로 유지하고, 필요한 부분만 변경한다.
3. **원본 보존**: 원본 함수나 메서드를 항상 저장해두고, 필요시 복원할 수 있게 한다.
4. **상황 제한**: 테스트나 개발 환경 등 특정 상황에서만 패치를 적용한다.
5. **임시 해결책**: 몽키 패칭은 영구적인 해결책이 아닌 임시 해결책으로 생각한다.

> [!Note]
> [[JS 함수 최적화]]에서 다루는 함수 최적화 기법은 코드 구조를 직접 개선하는 방식으로, 몽키 패칭과는 다른 접근법이다. 상황에 맞는 적절한 기법을 선택하는 것이 중요하다.

---

## 결론

몽키 패치는 런타임에 코드를 동적으로 수정할 수 있는 강력한 기법이다. 버그 수정, 기능 추가, 테스트 등 다양한 상황에서 유용하게 사용될 수 있지만, 코드의 가독성과 유지보수성을 해칠 수 있다. 따라서 몽키 패칭은 임시 해결책으로 신중하게 사용하고, 가능한 한 정식 개발 프로세스를 통해 코드를 개선하는 것이 바람직하다.

실무에서는 [[JS 함수 최적화]]나 [[통합 프로젝트 기술]]과 같은 체계적인 접근 방식과 함께, 몽키 패칭을 상황에 맞게 전략적으로 활용하는 것이 효과적이다. 특히 개발 과정에서 외부 라이브러리의 제한사항을 빠르게 우회해야 할 때 유용한 도구로 활용할 수 있다. 