---
title: LLM Compiler for Parallel Function Calling
date: 2025-01-26
tags:
- AI
- PaperReview
- LLM
- ToolCalling
- Optimization
- ParallelProcessing
- Plan-and-Execute
draft: false
enableToc: true
description: LLM 기능 호출을 병렬로 처리하여 지연 시간과 비용을 줄이는 LLM Compiler 연구에 대한 검토
summary: "본 문서는 LLM Compiler 연구에 대한 검토로, 함수 호출을 병렬로 처리함으로써 지연 시간과 비용을 크게 줄일 수 있는 방법을 설명한다. 기존 ReAct 방식 대비 최대 3.7배 속도 향상, 6.7배 비용 절감, 9%의 정확도 향상 효과를 제공한다. Function Calling Planner, Task Fetching Unit, Executor의 세 구성요소를 통해 효율적인 병렬 처리를 구현하는 방식을 자세히 다룬다."
published: 2025-01-26
modified: 2025-01-26
---
- paper: [https://arxiv.org/abs/2312.04511](https://arxiv.org/abs/2312.04511)
- github: [https://github.com/SqueezeAILab/LLMCompiler](https://github.com/SqueezeAILab/LLMCompiler)
- youtube: [https://youtu.be/aoLtTIYAafY?si=9d4O99LWEWpX15Oc](https://youtu.be/aoLtTIYAafY?si=9d4O99LWEWpX15Oc)

## Abstract

#### **Problem**: 
현재 LLM 함수 호출 방법은 각 함수에 대해 순차적인 추론과 실행이 필요하여 **높은 지연 시간, 비용, 때로는 부정확한 동작**을 초래할 수 있다.

#### Key Question: 
여러 함수 호출을 통합하는 가장 효과적인 접근 방식은 무엇인가?

#### LLM Compiler
- 여러 함수 호출을 효율적으로 조정하기 위해 함수를 병렬로 실행한다
- 세 가지 구성 요소로 이루어진다:
  1. Function Calling Planner: 함수 호출을 위한 실행 계획 수립
  2. Task Fetching Unit: 함수 호출 작업 배포
  3. Executor: 이러한 작업을 병렬로 실행

**ReAct**와 비교한 관찰 결과:
- 최대 3.7배의 일관된 지연 시간 단축
- 최대 6.7배의 비용 절감
- 최대 약 9%의 정확도 향상

## Background information

- Funciton(Tool) Calling: LLM이 제공된 함수를 호출하고 함수 출력을 사용하여 작업 완료를 돕는 능력
- ReAct: LLM이 함수를 호출하고, 결과를 분석한 다음, 다음 작업에 대해 추론하는 방법으로, 이는 후속 함수 호출을 포함한다

### ReAct vs LLM Compiler

![](https://i.imgur.com/MXtRn9V.png)

## Evaluation

| **평가 작업**             | **데이터셋/벤치마크**                          | **관찰 결과**                                                          | **비교 대상**  |
| ------------------------------- | ---------------------------------------------- | ------------------------------------------------------------------------- | ---------------- |
| **명백한 병렬화**     | HotpotQA (Yang et al., 2018)                   | - 1.80배 속도 향상<br>- 3.37배 비용 절감                                 | ReAct            |
|                                 | Movie Recommendation (Srivastava et al., 2022) | - 3.74배 속도 향상<br>- 6.73배 비용 절감                                 | ReAct            |
| **복잡한 패턴**            | ParallelQA                                     | - 최대 2.27배 속도 향상<br>- 4.65배 비용 절감<br>- 9% 정확도 향상 | ReAct            |
| **동적 재계획**          | Game of 24 (Yao et al., 2023b)                 | - 2배 속도 향상                                                              | Tree-of-Thoughts |
| **대화형 의사 결정** | WebShop                                        | - 최대 101.7배 속도 향상<br>- 25.7% 성공률 향상                   | 기준선        |

### LLM의 지연 시간 최적화를 위한 최근 연구 및 비교

**모델 및 시스템 수준 최적화**
  - 연구는 모델 설계 및 시스템 효율성 최적화에 중점을 둔다
  - 한계: 
	  - 애플리케이션 수준 최적화에는 관심이 적다
	  - 모델 수정이 제한된 블랙박스 LLM에 중요함

**Skeleton-of-Thought (Ning et al., 2023)**
  - 접근 방식: 스켈레톤 생성 및 실행을 통한 병렬 디코딩
  - 한계: 작업이 독립적이라고 가정하여 코딩이나 수학과 같은 복잡한 문제에는 적합하지 않다

**OpenAI의 병렬 함수 호출**
  - 특징: 지연 시간을 줄이기 위한 동시 함수 호출 생성
  - 한계: OpenAI 독점 모델에서만 사용 가능

**ReWOO (Xu et al., 2023)**
  - ReAct에 비해 토큰 사용량과 비용을 줄이기 위해 추론, 실행 및 관찰 단계를 분리함
  - 한계: 병렬 함수 호출이나 동적 재계획을 지원하지 않음

**LLMCompiler의 발전**
  - 지연 시간과 비용을 줄이기 위한 병렬 함수 호출 허용
  - 결정되지 않은 실행 흐름이 있는 문제에 대한 동적 재계획 지원
  - 상호 의존적인 작업 처리, 복잡한 시나리오에서 더 넓은 적용 가능성 가능
  - 기존 접근 방식에 비해 더 나은 지연 시간 및 비용 효율성 달성

## Methodology

쿼리: Microsoft의 시가총액이 Apple의 시가총액을 초과하려면 얼마나 증가해야 하는가?

![](https://i.imgur.com/xOrVoXe.png)

1. `Function Calling Planner`는 작업의 상호 의존성을 가진 DAG(방향성 비순환 그래프)를 생성한다
2. 작업은 이후 의존성에 따라 Task Fetching Unit에 의해 Executor에 병렬로 배포된다
3. 작업 1과 작업 2는 두 개의 독립적인 검색 작업의 병렬 실행을 위해 함께 가져온다
4. 각 작업이 수행된 후, 결과는 자리 표시자 변수를 대체한 후 종속 작업의 차단을 해제하기 위해 `Task Fetching Unit`으로 다시 전달된다

---

## 1. LLMCompiler의 목적

- LLMCompiler는 에이전트를 위한 컴파일러를 만드는 첫 시도로, 다양한 기능 호출을 효율적으로 처리하는 것을 목표로 한다
- 발표자는 Seun, Sohung Moon, Ryan Tabrizy, Nicholas Lee, Michael Mahoney, Ker 등 여러 연구자들과 협력하여 진행했다

## 2. LLM의 기능 호출 발전

- LLM의 기능 호출은 최근 1년간 발전했으며, 특히 **컨텍스트 학습**과 같은 새로운 행동이 등장했다
- 예를 들어, LLM에 몇 가지 예시를 제공하면 이를 바탕으로 새로운 질문에 답변 가능하다
- 그러나 복잡한 수학 문제 해결이나 개인 데이터베이스 접근에는 한계가 있다

## 3. 도구 사용의 필요성

- LLM이 복잡한 계산을 수행할 때, 계산기 등의 도구를 사용할 수 있도록 하는 방법이 제안되었다
- LLM이 도구가 필요할 경우 특정 토큰을 출력하여 도구를 호출하도록 유도한다
- 이러한 접근 방식은 LLM의 성능을 크게 향상시킨다

## 4. React 프레임워크의 한계

- React 프레임워크에서는 LLM이 도구를 호출할 때 무한 루프에 빠지거나 중간 결과를 잊어버리는 등의 문제가 발생할 수 있다
- 이를 해결하기 위한 다양한 솔루션이 제안되었으나, 여전히 해결해야 할 과제가 많다

## 5. LLMCompiler의 설계

- LLMCompiler는 **LLM 플래너, 작업 가져오기 유닛, 실행기**의 세 가지 주요 구성 요소로 이루어진다
- LLM 플래너는 사용자 입력을 이해하고 이를 여러 작업으로 분해하여 실행 가능하도록 한다
- 사용자는 도구 정의와 예시를 제공하여 LLMCompiler를 구성할 수 있다

## 6. 평가 및 성과

- LLMCompiler는 **HAAQA, BigBench** 등의 벤치마크를 사용하여 평가되었다
- 기존 React 방법보다 **1.8배~3.7배** 빠른 성능을 보인다
- 정확도 또한 개선되었으며, 비용 절감 효과도 있다

## 7. 재계획 기능

- LLMCompiler는 **재계획 기능**을 통해 실행 중 발생하는 오류를 처리할 수 있다
- 예를 들어, 웹에서 아이템을 구매할 때 예상치 못한 결과가 발생하면 재계획이 필요하다

## 8. 미래 방향성

- 기존 컴파일러의 **최적화 기법**을 적용하여 다양한 모델을 효율적으로 사용할 수 있도록 발전할 계획이다
- 이를 통해 LLM의 자원 사용을 최적화하고, 복잡한 작업 처리에 기여할 것이다

## 9. 결론 및 Q&A

- 발표자는 LLMCompiler의 가능성과 향후 연구 방향을 설명하고 청중의 질문에 답변했다
- LLMCompiler는 다양한 응용 프로그램에서 유용하게 활용될 가능성이 크다 