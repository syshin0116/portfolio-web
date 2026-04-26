---
title: "AI 기초 개념: 기호주의 vs 연결주의"
type: concept
tags:
  - ai
  - machine-learning
  - deep-learning
  - symbolism
  - connectionism
  - neural-network
  - crisp-dm
  - data-science
summary: "AI 접근 방식은 규칙 기반 기호주의(Symbolism)와 뉴럴 네트워크 기반 연결주의(Connectionism)로 나뉜다. 기호주의는 1980년대 쇠락했고, 연결주의(퍼셉트론 → 딥러닝)가 현재 주류다. 데이터 분석 프로세스 표준인 CRISP-DM도 함께 정리한다."
sources:
  - content/Study/SeSAC/data-analysis/2023-07-28-SeSAC-인공지능.md
  - content/Study/SeSAC/data-analysis/2023-07-18-SeSAC-데이터 분석 기초-1일차.md
created: 2026-04-26
updated: 2026-04-26
author: wiki-curator
draft: false
---

## Key Claims

- **기호주의(Symbolism) AI**: 기호와 규칙 기반 AI. 체스·전문가 시스템에 적합. 1950~1980년대 전성기. 한계: 실세계 개념을 기호로 표현 불가 → 1980년대 쇠락.[^2]
- **연결주의(Connectionism) AI**: 뉴런 연결을 모방한 신경망 기반. 문자·영상·음성 패턴 인식에 적합. 로젠블렛의 퍼셉트론이 첫 공식 모델.[^2]
- **퍼셉트론**: 연결주의 AI의 첫 공식 구현 모델(Frank Rosenblatt, 1957). 특정 임계값 이상의 입력에서 0/1 출력.[^2]
- 데이터와 AI의 관계: 1990년대 인터넷 대중화 → 2000년대 사용자 생성 데이터 급증 → IT에서 DT(Data Technology)로 확장. 빅데이터는 발생 데이터를 전부 수용하는 것, 일부 선별은 빅데이터가 아님.[^1]
- **CRISP-DM**: 데이터 마이닝 표준 프로세스. 비즈니스 이해 → 데이터 이해 → 데이터 준비 → 모델링 → 평가 → 배포.[^1]
- ML에 필요한 선형대수 기초: 스칼라(숫자 1개), 벡터(숫자 여러 개), 행렬(벡터 집합), 텐서(같은 크기 행렬 여러 개).[^1]

## Connections

- [[transformer-architecture]] — 연결주의의 발전이 딥러닝을 거쳐 Transformer 아키텍처로 이어짐
- [[object-detection]] — 연결주의 기반 CNN이 객체 탐지의 핵심 기술

## Footnotes

[^1]: content/Study/SeSAC/data-analysis/2023-07-28-SeSAC-인공지능.md
[^2]: content/Study/SeSAC/data-analysis/2023-07-18-SeSAC-데이터 분석 기초-1일차.md
