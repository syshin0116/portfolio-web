---
title: LayoutLM
date: 2024-04-04
tags:
- document-ai
- nlp
- deep-learning
- computer-vision
- multimodal
- layout-analysis
- ocr
draft: false
enableToc: true
description: LayoutLM의 발전 과정과 시각적으로 풍부한 문서 이해를 위한 다양한 버전별 특징 및 성능 분석
summary: "LayoutLM은 시각적으로 풍부한 문서 이해(VrDU)를 위한 멀티모달 프레임워크로, 텍스트뿐만 아니라 레이아웃과 시각적 정보를 함께 활용한다. V1부터 V3까지 발전하면서 문서 이미지에서 정보 추출, 양식 이해, 영수증 분석, 문서 분류 등 다양한 작업에서 우수한 성능을 보이고 있다."
published: 2024-04-04
modified: 2024-04-04
---
## 개요

시각적으로 풍부한 문서(Visually-rich Document)는 텍스트만으로는 완전히 이해할 수 없는 구조적 정보와 레이아웃을 포함하고 있다. LayoutLM은 이러한 문서에서 텍스트, 시각적 요소, 레이아웃 정보를 모두 활용하여 문서를 이해하는 멀티모달 프레임워크다. 이 문서에서는 LayoutLM의 V1부터 V3까지의 발전 과정과 주요 특징을 살펴본다.

[[문서(pdf 등) 내 시각 자료와 텍스트의 추출 및 활용 연구]]와 밀접한 관련이 있으며, OCR 기술의 발전과 함께 문서 이해의 핵심 기술로 자리잡고 있다.

---

## 배경

### 시각적으로 풍부한 문서 이해(VrDU)

시각적으로 풍부한 문서 이해(Visually-rich Document Understanding, VrDU)는 다음과 같은 특징을 가진다:

- 스캔된 이미지나 PDF 형태의 비즈니스 문서에서 필요한 정보를 추출하는 과정
- 텍스트(Text), 시각(Visual), 레이아웃(Layout) 정보를 모두 다루는 멀티모달 접근 방식 필요
- 전통적인 OCR 기반 방식을 넘어 문서의 구조와 컨텍스트를 이해하는 능력 요구

![VrDU 개념도](https://i.imgur.com/LsfvFEU.png)

---

## 학습 데이터셋

LayoutLM의 개발과 평가에 사용된 주요 데이터셋들을 알아보자.

### 사전학습 데이터셋

#### IIT-CDIP
- Illinois Institute of Technology Complex Document Information Processing Test Collection
- 6백만 개의 스캔된 문서와 11백만 개의 스캔된 문서 이미지로 구성
- 다양한 형식과 레이아웃의 비즈니스 문서 포함

![IIT-CDIP 예시](https://i.imgur.com/Ed06F9e.png)

### 양식 이해 데이터셋

#### FUNSD (Form Understanding in Noisy Scanned Documents)
- 목표: 스캔된 양식 이미지에서 키-값 쌍 추출
- 주요 작업:
  1. 시맨틱 라벨링: 시맨틱 엔티티 식별 (질문, 답변, 헤더, 기타)
  2. 시맨틱 링킹: 시맨틱 엔티티 간의 관계 예측
- 평가 지표: F1 점수

![FUNSD 예시](https://i.imgur.com/ZDa5luO.png)

#### Kleister-NDA
- 내용: 비밀유지계약서(NDA) 문서
- 작업: 시맨틱 라벨링
- 라벨: 당사자(party), 관할권(jurisdiction), 효력 발생일(effective_date), 기간(term)
- FUNSD보다 문서 길이가 길고 레이아웃이 복잡한 특징

### 영수증 이해 데이터셋

영수증 이해 작업은 미리 정의된 시맨틱 슬롯을 예측하는 것이 목표다.

#### SROIE (Scanned Receipts OCR and Key Information Extraction)
- 스캔된 영수증에서 주요 정보(회사명, 주소, 총액 등) 추출

#### CORD (A Consolidated Receipt Dataset for Post-OCR Parsing)
- 다양한 형태의 영수증 데이터 포함
- 보다 세밀한 정보 추출 지원

### 문서 이미지 분류 데이터셋

#### RVL-CDIP (Ryerson Vision Lab Complex Document Information Processing)
- 작업: 문서 이미지 카테고리 예측
- 16개의 클래스 분류(편지, 양식, 이메일, 손글씨, 광고, 과학 보고서 등)
- 평가 지표: 정확도

![RVL-CDIP 예시](https://i.imgur.com/tE1OE9Z.png)

### 시각적 질의응답 데이터셋

#### DocVQA
- 작업: 문서 이미지에 대한 질문에 답변
- 평가 지표: Levenshtein 유사도(ANLS)

> [!Note]
> Levenshtein Similarity는 다음과 같이 계산된다:
> $$Similarity = 1 - \frac{Levenshtein Distance} {max(\text{length of string})}$$
> 
> Levenshtein Distance는 문자열 간의 "편집" 유사성을 측정하는 반면, Cosine Similarity는 벡터 간의 "방향적" 유사성을 측정한다. 문서 VQA 작업에서는 정확한 문자열 일치가 중요하기 때문에 Levenshtein 측정법이 사용된다.

---

## LayoutLM 모델 발전 과정

### LayoutLM V1

LayoutLM V1은 사전학습 과정에서 텍스트 정보와 레이아웃 정보를 모두 반영한 최초의 모델이다.

**주요 특징:**
- BERT 아키텍처를 기반으로 2D 위치 임베딩 추가
- 텍스트 토큰의 경계 상자 좌표를 활용한 레이아웃 정보 통합
- 문서 이미지 분류, 양식 이해 등의 작업에서 기존 모델 대비 우수한 성능 달성

**한계점:**
- 사전학습 과정에서 시각적 정보를 완전히 활용하지 못함
- 이미지 특징은 미세조정 단계에서만 사용

> [!Note]
> LayoutLM V1의 접근 방식은 표 특화 사전학습(Table-Specific Pre-training)과 유사하다. PDF 문서에서 테이블 구조를 인식하고 처리하는 문제는 복잡한 레이아웃을 다루는 LayoutLM의 핵심 과제 중 하나다.

---

## 응용 분야 및 실제 활용

LayoutLM은 다음과 같은 다양한 분야에서 활용될 수 있다:

1. **자동 문서 처리**: 청구서, 송장, 계약서 등 비즈니스 문서의 자동 처리
2. **정보 추출**: 양식에서 주요 필드와 값 추출
3. **문서 분류**: 대량의 문서를 적절한 카테고리로 자동 분류
4. **시각적 질의응답**: 문서 이미지에 관한 질문에 답변

[[RAG용 PDF Loader 비교]] 문서에서 다룬 PDF 처리 기술과 결합하면 더 효과적인 문서 이해 시스템을 구축할 수 있다.

---

## 결론

LayoutLM은 문서 이해 분야에 텍스트, 레이아웃, 시각적 정보를 통합한 혁신적인 접근 방식을 제시했다. V1부터 V3까지의 발전 과정을 통해 다양한 문서 이해 작업에서 성능이 지속적으로 향상되었으며, 실제 비즈니스 환경에서 문서 자동화의 핵심 기술로 자리잡고 있다.

향후 연구에서는 더 적은 학습 데이터로도 효과적인 성능을 발휘할 수 있는 모델 개발과, 복잡한 표와 그래프를 포함한 문서의 이해력 향상이 주요 과제로 남아있다.

LayoutLM에 대한 추가 정보는 [[문서(pdf 등) 내 시각 자료와 텍스트의 추출 및 활용 연구]]와 [[RAG용 PDF Loader 비교]] 문서를 참조하고, 관련 논문과 구현 코드를 확인하는 것이 좋다. 