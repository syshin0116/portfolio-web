---
title: LlamaIndex 활용 가이드 온라인 세미나
date: 2024-05-30
tags:
- llamaindex
- llm
- rag
- deep-learning
- document-processing
- indexing
draft: false
enableToc: true
description: LlamaIndex의 장점과 실무 활용 방법을 다룬 온라인 세미나 정리
summary: "POSCO E&C 조우철 연구원의 LlamaIndex 활용 세미나 내용을 정리한 노트이다. LlamaIndex의 주요 장점(쉽고 간결한 코드, 빠른 프로토타이핑), LangChain과의 비교, Document Loaders와 Readers 활용, Indexing 전략, Query Engine 구성, 그리고 실무에서의 활용 사례와 팁을 포함한다."
published: 2024-05-30
modified: 2024-05-30
---
# Why I use LlamaIndex
- 조우철님 발표 
- Applied AI Researcer @POSCO E&C

## LlamaIndex 장점

- 코드가 쉽고 간결하다


![](https://i.imgur.com/AQVmP1u.png)

![](https://i.imgur.com/g6mdctg.png)

- 기본 RAG는 5 line code로 구현 가능할 정도로 간결하다
- Well Documented
- Well Maintained
- 빠른 업데이트

![](https://i.imgur.com/UZkzVgj.png)

# LLM-as-a-Judge: A Futuristic Way of Evaluation Foundational Models
- Jamin (Jay) Shin

## Background: Standard Methods of Text Evaluation

### Lexical-based Metrics
- reference의 단어가 얼마나 겹쳤는가
- semantic information을 고려하지 않음
- ex) Accuracy, ROUGE, BLUE, CiDER, METEOR

![](https://i.imgur.com/JIpK8QK.png)


### Embedding-based Metrics
- Cosine Similarity 비교
- Expressiveness Bottlenect
- ex) BERT-score, BART-score

![](https://i.imgur.com/Zd4g1Zm.png)

## Motivation: Why Evaluation is Hard
- brevity, creativity, tone, cultural sensitivities 등 평가할 항목이 다양하다
- NLP역사에 Human Evaluation가 항상 포함되어왔다
	- 하지만 Human Evaluation은 Bias에 취약할 수 밖에 없다
	- 비용이 너무 크고 재현하기 어렵다

![](https://i.imgur.com/Pf5QtEs.jpeg)

Human Evaluation이 어려운 예시:
- 우측 답변이 딱 봤을떄는 더 잘 써진 글 같지만, 사실은 왼쪽이 맞는 답변임


AI로 Evaluation을 대체하는 많은 시도가 있지만 한계가 있다
- 자기 자신이 쓴 글에 대해 bias 존재
- "좋은 답변" 자체가 모호하다


### Prometheus

![](https://i.imgur.com/CKRDNH8.png)


# Building RAG Applications with LlamaIndex

- Ravi Theja
	- developer advocate @ LlamaIndex

## Why is RAG Needed?

## Necessity of LlamaIndex

## RAG Components

## Use Cases

### QA, Summarization

### Document Comparisons

## Recursive Rretrieval

## Data Agents