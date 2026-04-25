---
title: Anomaly Detection
date: 2024-03-12
tags:
- anomaly-detection
- machine-learning
- deep-learning
- imbalanced-data
- classification
- autoencoder
draft: false
enableToc: true
description: 이상 탐지(Anomaly Detection)의 주요 방법론과 기법을 정리하고 각 접근법의 장단점을 비교한 글이다.
summary: "이상 탐지(Anomaly Detection)는 데이터에서 일반적인 패턴과 다른 비정상적인 샘플을 식별하는 기법이다. 지도학습, 준지도학습, 비지도학습 방식으로 나뉘며, 각 방식은 데이터와 문제 상황에 따라 선택적으로 적용할 수 있다."
published: 2024-03-12
modified: 2024-03-12
---
## 이상 탐지 개요

이상 탐지(Anomaly Detection)는 데이터셋에서 정상적인 패턴과 다른 이상 패턴을 식별하는 기술이다. 제조업의 결함 탐지, 금융 사기 탐지, 네트워크 침입 감지, 의료 진단 등 다양한 분야에서 활용된다.

---

## 데이터셋 예시

### Company Bankruptcy Prediction

[Kaggle의 Company Bankruptcy Prediction 데이터셋](https://www.kaggle.com/datasets/fedesoriano/company-bankruptcy-prediction)은 기업의 파산 여부를 예측하는 데 사용된다. 이는 심각한 불균형 데이터로, 파산 기업(소수 클래스)이 매우 적다.

#### 문제 정의

기업 파산은 기업뿐만 아니라 글로벌 경제에도 부정적인 영향을 미친다. 따라서 기업이 파산의 징후를 보이는지 예측하는 모델을 개발하는 것이 중요하다.

#### 데이터 특성

이 데이터는 1999년부터 2009년까지 대만 경제 저널에서 수집되었으며, 다음과 같은 다양한 재무 비율 열로 구성된다:

- 자산수익률(ROAs)
- 총이익
- 영업 및 순이익과 비용
- 현금 흐름
- 세금
- 성장률
- 부채
- 매출, 수익, 부채 등

모든 특성은 0에서 1 사이로 정규화되어 있다. 목표 열은 "Bankrupt?"(0: 아니오, 1: 예)이다.

이 데이터는 [[Imbalanced Data Prediction(Anomaly Detection)|불균형 데이터 처리]]가 필요한 전형적인 예시다.

---

## 이상 탐지 방법론

이상 탐지 방법론은 크게 세 가지로 나눌 수 있다:

### 1. 지도학습 기반 이상 탐지 (Supervised Anomaly Detection)

지도학습 방식은 정상과 비정상 샘플이 모두 레이블된 학습 데이터를 사용한다.

#### 특징
- 다른 방법 대비 **정확도가 높음**
- 비정상 샘플을 다양하게 보유할수록 더 높은 성능 달성 가능

#### 문제점
- 일반적인 산업 현장에서는 정상 샘플보다 비정상 샘플의 발생 빈도가 현저히 적어 **클래스 불균형(Class-Imbalance)** 문제가 발생한다

#### 해결 시도 방안
- 데이터 증강(Data Augmentation)
- 손실 함수 재설계(Loss function redesign)
- 배치 샘플링(Batch Sampling) 등

#### 장단점
- **장점**: 판정 정확도가 높다
- **단점**: 
  - 비정상 샘플을 취득하는 데 시간과 비용이 많이 든다
  - 클래스 불균형 문제를 해결해야 한다

---

### 2. 준지도학습 기반 이상 탐지 (Semi-supervised Anomaly Detection)

클래스 불균형이 매우 심한 경우, 정상 샘플만 이용해 모델을 학습시키는 방식이다. 이를 One-Class Classification이라고도 한다.

#### 핵심 아이디어
1. 정상 샘플들을 둘러싸는 판별 경계(discriminative boundary)를 설정
2. 경계를 최대한 좁혀 경계 밖에 있는 샘플들을 모두 비정상으로 간주

대표적인 방법론으로는:
- [**One-Class SVM**](http://www.jmlr.org/papers/volume2/manevitz01a/manevitz01a.pdf)
- [**Deep SVDD**](http://data.bit.uni-bonn.de/publications/ICML2018.pdf): 딥러닝 기반 One-Class Classification

![Deep SVDD 방법론 모식도](https://i.imgur.com/2xcDa9N.png)

#### 다른 접근법들
- **Energy-based 방법론**: Deep structured energy based models for anomaly detection, 2016
- **Deep Autoencoding Gaussian Mixture Model**: [DAGMM, 2018 ICLR](https://sites.cs.ucsb.edu/~bzong/doc/iclr18-dagmm.pdf)
- **GAN 기반 방법론**: [Anomaly detection with generative adversarial networks, 2018](https://arxiv.org/pdf/1809.04758.pdf)
- **자기지도학습(Self-Supervised Learning) 기반**: [Deep Anomaly Detection Using Geometric Transformations, 2018 NeurIPS](https://papers.nips.cc/paper/8183-deep-anomaly-detection-using-geometric-transformations.pdf)

#### 장단점
- **장점**: 정상 샘플만 있어도 학습이 가능하며, 비교적 활발하게 연구가 진행 중이다
- **단점**: 지도학습 방식에 비해 상대적으로 정확도가 떨어진다

---

### 3. 비지도학습 기반 이상 탐지 (Unsupervised Anomaly Detection)

대부분의 데이터가 정상 샘플이라는 가정 하에, 레이블 없이 학습을 진행하는 방식이다.

#### 주요 방식
- **PCA(주성분 분석)**: 차원을 축소하고 복원하는 과정에서 비정상 샘플 검출
- **Autoencoder**: 신경망 기반으로 가장 많이 사용되는 방식

Autoencoder는 두 단계로 작동한다:
1. **인코딩(Encoding)**: 입력을 잠재 공간(latent space)으로 압축
2. **디코딩(Decoding)**: 압축된 표현을 원본과 가깝게 복원

이는 데이터의 중요한 정보만 압축적으로 학습한다는 점에서 PCA와 유사하다.

![autoencoder 기반 unsupervised anomaly detection](https://i.imgur.com/ON4BC4F.png)

#### 성능 결정 요소
- **코드 크기(code size)**: 잠재 변수(latent variable)의 차원
- **차이 맵 계산 방식**: 입력과 출력의 차이를 정의하는 방법
- **손실 함수(loss function)**

#### 관련 논문
- [**Improving Unsupervised Defect Segmentation by Applying Structural Similarity to Autoencoders**](https://arxiv.org/pdf/1807.02011.pdf)
- [**Deep Autoencoding Models for Unsupervised Anomaly Segmentation in Brain MR Images**](https://arxiv.org/pdf/1804.04488.pdf)
- [**MVTec AD – A Comprehensive Real-World Dataset for Unsupervised Anomaly Detection**](https://www.mvtec.com/fileadmin/Redaktion/mvtec.com/company/research/mvtec_ad.pdf)

#### 장단점
- **장점**: 레이블링 과정이 필요 없다
- **단점**: 판정 정확도가 높지 않고 하이퍼파라미터에 매우 민감하다

![Anomaly Detection 관련 3가지 용어의 분류 방법 정리](https://i.imgur.com/C947qx3.png)

---

## 불균형 데이터 처리 기법

불균형 데이터를 처리하는 주요 기법으로는 오버샘플링과 언더샘플링이 있다.

![오버샘플링과 언더샘플링](https://i.imgur.com/IXz5Spf.png)

### 오버샘플링(Oversampling)

소수 클래스의 샘플 수를 인위적으로 늘려 클래스 간 불균형을 해소하는 방법이다.

#### SMOTE(Synthetic Minority Over-sampling Technique)

SMOTE는 가장 대표적인 오버샘플링 기법으로, 소수 클래스 데이터 포인트 사이를 보간하여 새로운 데이터를 생성한다.

##### 작동 원리
- 소수 클래스 데이터들의 최근접 이웃을 이용해 새로운 데이터 생성
- 완전히 동일한 특성을 가진 데이터를 복사하는 것이 아니라, 근접 데이터와 일정 거리를 두고 새 데이터를 생성

![SMOTE 작동 원리](https://blog.kakaocdn.net/dn/GaITt/btqGmTl4AeX/qkrQ3yl4LjsNyDorwyr5Gk/img.png)

##### 주의 사항
- 오버샘플링은 양성으로 예측하는 비율이 높아지기 때문에 정밀도가 감소하고 재현율은 증가하는 경향이 있다
- [[LangChain|고급 ML 파이프라인]]을 사용할 때 이러한 트레이드오프를 고려해야 한다

```python
# imbalanced-learn 패키지 사용 예시
from imblearn.over_sampling import SMOTE 
# 검증 데이터나 테스트 데이터가 아닌 학습데이터에서만 오버샘플링 사용
smote = SMOTE(random_state=11) 
X_train_over, y_train_over = smote.fit_sample(X_train, y_train)
```

### 언더샘플링(Undersampling)

다수 클래스의 샘플 수를 줄여 불균형을 해소하는 방법이다.

#### 특징
- 정보 손실이 발생할 수 있어 데이터 양이 많지 않을 때는 주의해서 사용
- 계산 비용을 줄이고 싶을 때 유용

---

## 최신 이상 탐지 모델

### 변분 오토인코더(Variational Autoencoders, VAEs)

VAE는 생성 모델로, 오토인코더의 잠재 공간에 확률적 특성을 부여한다. 이를 통해 더 견고한 이상 탐지가 가능하다.

### UniTS

[UniTS](https://zitniklab.hms.harvard.edu/projects/UniTS/)는 시계열 데이터에 특화된 이상 탐지 모델로, 다양한 도메인의 시계열 데이터에서 이상을 탐지할 수 있다.

- [GitHub 저장소](https://github.com/mims-harvard/UniTS)

## 결론

이상 탐지는 데이터 과학과 기계 학습의 중요한 영역으로, 다양한 방법론이 존재한다. 문제의 특성과 가용한 데이터에 따라 적절한 방법을 선택해야 한다.

지도학습 방식은 가장 높은 정확도를 제공하지만 레이블이 필요하고, 준지도학습은 정상 데이터만으로 학습이 가능하며, 비지도학습은 레이블이 전혀 필요하지 않다는 장점이 있다.

불균형 데이터 처리를 위한 오버샘플링과 언더샘플링, 그리고 최신 모델인 VAE와 UniTS와 같은 기법들은 이상 탐지의 성능을 더욱 향상시키는 데 기여하고 있다.

이상 탐지는 [[Imbalanced Data Prediction(Anomaly Detection)|불균형 데이터 예측]] 문제와 밀접하게 관련되어 있으며, [[차원 축소 (Dimensionality Reduction) 기법|차원 축소 기법]]을 함께 활용하면 더 효과적인 결과를 얻을 수 있다. 