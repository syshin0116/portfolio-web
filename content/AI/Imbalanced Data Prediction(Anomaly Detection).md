---
title: Imbalanced Data Prediction(Anomaly Detection)
date: 2024-03-18
tags:
- anomaly-detection
- imbalanced-data
- classification
- clustering
- machine-learning
- deep-learning
draft: false
enableToc: true
description: 불균형 데이터에서의 이상치 탐지를 위한 다양한 모델과 기법을 비교 분석한 글이다.
summary: "불균형 데이터에서 이상치를 탐지하는 다양한 방법론을 비교한다. 지도학습 분류 모델과 비지도학습 이상 탐지 모델의 성능을 평가하고, 샘플링 기법의 효과를 분석한다."
published: 2024-03-18
modified: 2024-03-18
---
## 이상치 탐지 모델 성능 비교

이상치 탐지(Anomaly Detection)는 데이터셋에서 비정상적인 패턴이나 행동을 식별하는 프로세스다. 특히 금융 사기 탐지, 네트워크 침입 감지, 제조업 결함 검출 등 많은 실제 상황에서 중요한 역할을 한다. 이 글에서는 다양한 이상치 탐지 모델의 성능을 비교한다.

---

## 차원 축소 및 클러스터링

이상치 탐지를 위한 첫 번째 접근법으로 차원 축소와 클러스터링 기법을 살펴볼 수 있다. 고차원 데이터에서는 [[차원 축소 (Dimensionality Reduction) 기법|차원 축소 기법]]이 효과적이다.

### 주요 차원 축소 기법

1. **PCA(Principal Component Analysis)**: 데이터의 분산을 최대화하는 방향으로 차원을 축소한다.
2. **t-SNE([[T-SNE|T-Distributed Stochastic Neighbor Embedding]])**: 고차원 데이터의 유사성을 보존하며 2D 또는 3D로 시각화한다.
3. **UMAP(Uniform Manifold Approximation and Projection)**: t-SNE보다 계산 효율성이 높고 글로벌 구조를 더 잘 보존한다.

### 클러스터링 기반 접근법

클러스터링은 데이터 포인트를 유사한 그룹으로 나누며, 이상치는 주요 클러스터에서 멀리 떨어진 포인트로 간주된다:

```python
from sklearn.cluster import DBSCAN
import numpy as np

# DBSCAN 클러스터링을 사용한 이상치 탐지
dbscan = DBSCAN(eps=0.5, min_samples=5)
clusters = dbscan.fit_predict(X)

# -1로 레이블된 포인트는 이상치로 간주
outliers = np.where(clusters == -1)[0]
```

---

## 모델 성능 비교 평가

### 지도학습 분류 모델

#### 평가 방식

지도학습 기반 이상치 탐지의 성능을 평가하기 위해 다음 단계를 따른다:

- PyCaret 모델 테스트 후 상위 3개 모델 선정
- Stratified K-Fold: 5-fold 교차검증 평가 점수

> [!Note]
> 불균형 데이터에서는 정확도(Accuracy)보다 F1-score, Precision, Recall 등의 지표가 더 중요하다.

#### 평가 모델 리스트

총 16개의 분류 모델을 테스트했다:

1. Random Forest Classifier
2. Extra Trees Classifier
3. Extreme Gradient Boosting
4. CatBoost Classifier
5. Linear Discriminant Analysis
6. Logistic Regression
7. Ada Boost Classifier
8. Decision Tree Classifier
9. Gradient Boosting Classifier
10. Ridge Classifier
11. K Neighbors Classifier
12. Dummy Classifier
13. SVM - Linear Kernel
14. Light Gradient Boosting Machine
15. Naive Bayes
16. Quadratic Discriminant Analysis

#### CatBoost - 샘플링 기법 비교

PyCaret에서 가장 성능이 좋았던 CatBoost 모델을 사용하여 다양한 샘플링 기법을 비교했다:

1. **Base(원본 데이터)**: 불균형 상태 그대로 학습
2. **UnderSampling(과소표집)**: 다수 클래스 샘플을 줄여 균형을 맞춤
3. **OverSampling(과대표집)**: SMOTE 등을 활용해 소수 클래스 샘플을 증가시킴

각 방법의 장단점:

| 방법 | 장점 | 단점 |
|------|------|------|
| Base | 원본 데이터 보존 | 소수 클래스에 편향됨 |
| UnderSampling | 학습 속도 향상 | 정보 손실 가능성 |
| OverSampling | 정보 보존 | 과적합 위험 |

---

### 비지도학습 이상 탐지 모델

비지도학습 방식은 레이블이 없는
데이터에서도 이상치를 탐지할 수 있는 장점이 있다.

![Scaled minmax threshold estimation](https://i.imgur.com/JlLa3Ms.png)

#### PyOD 라이브러리

PyOD는 파이썬 기반의 이상치 탐지 툴킷으로, 다양한 알고리즘을 제공한다:

```python
from pyod.models.iforest import IForest
from pyod.models.knn import KNN

# Isolation Forest를 사용한 이상치 탐지
clf_if = IForest()
clf_if.fit(X_train)
y_pred_if = clf_if.predict(X_test)

# KNN을 사용한 이상치 탐지
clf_knn = KNN()
clf_knn.fit(X_train)
y_pred_knn = clf_knn.predict(X_test)
```

PyOD에서 사용된 주요 알고리즘:
- Isolation Forest
- Local Outlier Factor (LOF)
- One-Class SVM
- CBLOF (Cluster-Based Local Outlier Factor)

#### DeepOD 라이브러리

DeepOD는 딥러닝 기반 이상치 탐지를 위한 라이브러리다. [[LangChain|신경망 기반 접근법]]을 사용하여 복잡한 패턴을 학습할 수 있다:

- DeepSVDD: 하이퍼스피어 경계를 학습
- DevNet: 정상 샘플과 이상치의 차이를 학습
- GOAD: 자기지도학습으로 정상 패턴 학습

#### PyThresh 라이브러리

PyThresh는 임계값 계산에 특화된 라이브러리로, 이상치 점수의 최적 임계값을 찾는 데 도움을 준다:

- SPOT/DSPOT: 극단 값 이론 기반 임계값 계산
- 앙상블 기반 임계값 선택
- 동적 임계값 업데이트

## 결론

이상치 탐지는 다양한 접근법을 통해 수행할 수 있으며, 문제의 특성과 데이터에 따라 적합한 모델을 선택해야 한다. 지도학습 방법은 레이블이 있는 데이터에서 효과적이고, 비지도학습 방법은 레이블이 없는 데이터에서도 사용할 수 있다.

실험 결과, CatBoost와 같은 앙상블 모델이 지도학습에서 좋은 성능을 보였으며, 과대표집(OverSampling)을 적용했을 때 성능이 더욱 향상되었다. 비지도학습에서는 Isolation Forest와 DeepSVDD가 좋은 성능을 보였다.

실제 애플리케이션에서는 [[Anomaly Detection|이상 탐지 시스템]]을 구축할 때 여러 모델의 앙상블과 함께 도메인 지식을 결합하는 것이 효과적이다. 또한 데이터의 특성에 따라 [[차원 축소 (Dimensionality Reduction) 기법|차원 축소 기법]]을 적절히 활용하는 것이 중요하다. 