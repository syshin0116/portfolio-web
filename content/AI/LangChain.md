---
title: LangChain
date: 2024-02-02
tags:
- ai
- deep-learning
- langchain
- llm
- openai
- llama2
- gemini-pro
- streamlit
draft: false
enableToc: true
description: LangChain 프레임워크의 기본 개념, 활용 방법 및 LLama2와 결합한 실전 프로젝트 구현 과정 설명
summary: "LangChain은 대규모 언어 모델을 활용한 애플리케이션 개발을 위한 프레임워크로, LLM을 다양한 데이터 소스 및 환경과 연결하는 도구를 제공한다. 이 문서는 LangChain의 기초부터 LLM(OpenAI, Llama2, Gemini Pro)과의 통합, PDF 쿼리 구현, 블로그 생성 애플리케이션 개발까지 실습 중심으로 다룬다. 특히 Llama2의 아키텍처, 훈련 세부사항, 하드웨어 요구사항 및 미세 조정 방법에 대한 연구 내용을 포함한다."
published: 2024-02-02
modified: 2024-02-02
---
## 개요

LangChain은 대규모 언어 모델(LLM)을 다양한 애플리케이션에 통합하기 위한 프레임워크다. 이 문서에서는 LangChain의 기본 개념부터 실제 프로젝트 구현까지 실습 중심으로 살펴본다.

### 학습 방법
LangChain 공식 문서는 내용이 방대하여, 처음부터 정독하기보다 먼저 실습 위주로 경험한 후 공식 문서를 체계적으로 학습하는 접근법을 채택했다.

### 참고자료
- **유튜브 튜토리얼**: [LangChain 입문 가이드](https://www.youtube.com/watch?v=aWKrL4z5H6w)

---

## LangChain 실습 아젠다

실습 중심의 LangChain 학습 계획은 다음과 같다:

1. **환경 설정 및 OpenAI API 연동**
2. **기본 애플리케이션 구축**
   - LLM 및 채팅 모델 활용
   - 프롬프트 템플릿 작성
   - 출력 파서 구현 (PromptTemplate + LLM + OutputParser)

> [!Note]
> requirements.txt에 ipykernel을 추가하지 않는 이유는 개발 단계에서만 필요하고 실제 배포 시에는 필요하지 않기 때문이다.

---

## PDF 쿼리 시스템 구현

LangChain을 활용한 PDF 쿼리 시스템 구축에 대해 알아본다.

### Apache Cassandra(Astra DB)
- 오픈 소스 NoSQL 데이터베이스
- 확장성과 고가용성 제공

### DATAX
- Cassandra DB 생성을 위한 도구

### 벡터 검색(Vector Search)
- 임베딩의 유사성 비교를 통해 머신러닝 모델 성능 향상
- Astra DB의 핵심 기능 중 하나

---

## Llama2 모델 활용

Llama2 모델의 특징과 활용 방법에 대해 살펴본다.

![Llama2 모델 구조](https://i.imgur.com/S4Ysuim.png)

### 연구 논문
[Llama2 연구 논문](https://arxiv.org/pdf/2307.09288.pdf)에서 소개된 주요 내용:

### 훈련 세부사항
- Llama1의 사전 훈련 설정과 모델 아키텍처 대부분 채택
- 표준 트랜스포머 아키텍처 사용
- RMSNorm을 이용한 사전 정규화
- SwiGLU 활성화 함수 적용
- 주요 하이퍼파라미터:
  - AdamW 옵티마이저
  - 코사인 학습률 스케줄, 2000 스텝 워밍업
  - 최대 학습률의 10%까지 감소하는 최종 학습률
  - 0.1의 가중치 감소
  - 1.0의 그래디언트 클리핑

### Llama1과의 비교
- 컨텍스트 길이 증가
- GQA(Grouped-Query Attention) 도입

![Llama1과 Llama2 비교](https://i.imgur.com/WmosUsb.png)

### 훈련 하드웨어 및 탄소 발자국
- Meta의 Research Super Cluster 및 내부 프로덕션 클러스터 활용
  - 두 클러스터 모두 **NVIDIA A100** GPU 사용

![훈련 하드웨어 구성](https://i.imgur.com/wquoJ3D.png)

### 미세 조정(Fine-tuning)
- 명령어 튜닝 및 RLHF(강화 학습 및 인간 피드백) 적용
- 지도 학습 기반 미세 조정(SFT) 수행

![미세 조정 프로세스](https://i.imgur.com/uFChR4F.png)

---

## 블로그 생성 LLM 애플리케이션 개발

Llama2 모델을 활용한 블로그 생성 애플리케이션 개발 과정을 단계별로 살펴본다.

### 구현 단계
1. Hugging Face에서 Llama2 모델 다운로드
2. 모델 로딩 및 초기화
3. 블로그 생성 프롬프트 템플릿 설계
4. Streamlit을 활용한 웹 인터페이스 구현
5. 사용자 입력 처리 및 블로그 콘텐츠 생성

---

## 결론

LangChain은 LLM 기반 애플리케이션 개발을 위한 강력한 프레임워크를 제공한다. 본 문서에서 살펴본 것처럼 PDF 쿼리 시스템부터 블로그 생성 애플리케이션까지 다양한 실용적 솔루션을 구현할 수 있다. 특히 Llama2와 같은 최신 모델과의 통합을 통해 더욱 강력한 AI 애플리케이션을 개발할 수 있다.

LangChain에 관한 더 깊은 이해를 위해서는 [[RAG+Groq]], [[LLM Chain Chatbot + RAG]], [[Agent 사용 RAG+Tavily]] 등의 관련 문서를 참조하자. 