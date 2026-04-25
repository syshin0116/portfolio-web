---
title: 차원 축소 (Dimensionality Reduction) 기법
date: 2023-09-12
tags:
- dimensionality-reduction
- pca
- t-sne
- umap
- machine-learning
- visualization
draft: false
enableToc: true
description: 데이터의 복잡성을 줄이는 주요 차원 축소 기법인 PCA, t-SNE, UMAP의 개념과 활용법을 정리한 글이다.
summary: "차원 축소는 고차원 데이터를 저차원으로 변환하여 데이터의 핵심 정보를 보존하면서 복잡성을 줄이는 기법이다. 선형 방법인 PCA와 비선형 방법인 t-SNE, UMAP의 특징과 활용법을 설명한다."
published: 2023-09-12
modified: 2023-09-12
---
## 차원 축소의 필요성

고차원 데이터는 분석과 시각화에 어려움을 주고, 계산 비용이 높으며, '차원의 저주'라 불리는 문제를 일으킨다. 차원 축소는 이러한 문제를 해결하면서 데이터의 핵심 패턴을 보존하는 방법이다.

차원 축소는 머신러닝의 전처리 단계에서 중요한 역할을 하며, [[Anomaly Detection|이상 탐지]]와 [[Imbalanced Data Prediction(Anomaly Detection)|불균형 데이터 처리]]에도 효과적으로 활용된다.

---

## PCA (Principal Component Analysis)

PCA는 가장 널리 사용되는 선형 차원 축소 방법이다.

### 작동 원리

- 데이터의 분산을 최대화하는 주성분(Principal Component) 방향으로 데이터를 투영한다.
- 주성분은 데이터의 공분산 행렬의 고유벡터로부터 얻어진다.
- 고유값이 큰 순서대로 주성분을 선택하여 차원을 축소한다.

### 활용 분야

- 노이즈 제거
- 데이터 시각화
- 특징 추출
- 데이터 압축

### 코드 예시

```python
from sklearn.decomposition import PCA  
import matplotlib.pyplot as plt

# PCA 모델 생성 (2차원으로 축소)
pca = PCA(n_components=2) 

# 데이터 변환
reduced_data = pca.fit_transform(data)

# 설명된 분산 비율 확인
print(f"설명된 분산 비율: {pca.explained_variance_ratio_}")

# 결과 시각화
plt.figure(figsize=(10, 8))
plt.scatter(reduced_data[:, 0], reduced_data[:, 1], alpha=0.7)
plt.xlabel('First Principal Component')
plt.ylabel('Second Principal Component')
plt.title('PCA Result')
plt.show()
```

> [!Note]
> PCA는 선형 방법이므로 데이터에 비선형 관계가 있을 경우 효과적으로 차원을 축소하지 못할 수 있다.

---

## t-SNE (t-Distributed Stochastic Neighbor Embedding)

t-SNE는 비선형 차원 축소 방법으로, 특히 데이터 시각화에 많이 사용된다.

### 작동 원리

- 고차원에서의 데이터 포인트 간 유사성을 저차원에서도 보존하려고 노력한다.
- 고차원에서는 가우시안 분포를, 저차원에서는 t-분포를 사용하여 점들 간의 거리를 모델링한다.
- 국소적인 구조(가까운 점들 간의 관계)를 잘 보존하는 특징이 있다.

### 장단점

#### 장점
- 복잡한 비선형 데이터의 구조를 잘 시각화한다.
- 군집(클러스터)을 직관적으로 파악하기 좋다.

#### 단점
- 계산 비용이 높다 (O(n²))
- 결과가 하이퍼파라미터(perplexity 등)에 민감하다.
- 글로벌 구조 보존이 상대적으로 약하다.

### 코드 예시

```python
from sklearn.manifold import TSNE  
import matplotlib.pyplot as plt

# t-SNE 모델 생성
tsne = TSNE(n_components=2, perplexity=30, n_iter=1000, random_state=42) 

# 데이터 변환
reduced_data = tsne.fit_transform(data)

# 결과 시각화
plt.figure(figsize=(10, 8))
plt.scatter(reduced_data[:, 0], reduced_data[:, 1], c=labels, cmap='viridis', alpha=0.7)
plt.colorbar()
plt.title('t-SNE Visualization')
plt.show()
```

---

## UMAP (Uniform Manifold Approximation and Projection)

UMAP은 최근에 개발된 비선형 차원 축소 방법으로, t-SNE의 장점을 가지면서도 일부 단점을 보완한다.

### 작동 원리

- 리만 기하학과 대수적 위상수학 이론을 기반으로 한다.
- 데이터의 매니폴드(manifold) 구조를 학습하고 이를 저차원에 투영한다.
- 국소적 구조와 글로벌 구조 모두를 잘 보존하려고 노력한다.

### 장점

- t-SNE보다 계산 효율성이 높다.
- 글로벌 구조를 더 잘 보존한다.
- 시각화뿐만 아니라 일반 차원 축소 작업에도 효과적이다.
- 대규모 데이터셋에도 적용 가능하다.

### 코드 예시

```python
import umap
import matplotlib.pyplot as plt

# UMAP 모델 생성
reducer = umap.UMAP(n_neighbors=15, min_dist=0.1, n_components=2, random_state=42) 

# 데이터 변환
reduced_data = reducer.fit_transform(data)

# 결과 시각화
plt.figure(figsize=(10, 8))
plt.scatter(reduced_data[:, 0], reduced_data[:, 1], c=labels, cmap='viridis', alpha=0.7)
plt.colorbar()
plt.title('UMAP Visualization')
plt.show()
```

---

## 세 가지 방법의 비교

| 방법 | 유형 | 장점 | 단점 | 적합한 사용 사례 |
|------|------|------|------|-----------------|
| PCA | 선형 | 빠르고 직관적, 데이터 압축에 효과적 | 비선형 관계 포착 불가 | 데이터 압축, 노이즈 제거, 빠른 시각화 |
| t-SNE | 비선형 | 복잡한 데이터 구조 시각화에 탁월 | 계산 비용 높음, 글로벌 구조 보존 약함 | 데이터 클러스터 시각화, 패턴 탐색 |
| UMAP | 비선형 | t-SNE보다 빠르고, 글로벌 구조 보존 | 이론적 배경 복잡, 하이퍼파라미터 튜닝 필요 | 대규모 데이터셋 차원 축소, 일반 머신러닝 파이프라인 |

[[T-SNE|t-SNE에 대한 자세한 분석]]과 [[LangChain|LangChain을 활용한 응용]]을 참고하면 더 깊은 이해가 가능하다.

## 결론

차원 축소는 고차원 데이터를 다루는 데 필수적인 기법이다. 데이터의 특성과 목적에 따라 적절한 방법을 선택하는 것이 중요하다.

PCA는 빠르고 직관적인 선형 방법으로 기본적인 차원 축소에 적합하다. t-SNE는 복잡한 비선형 관계를 시각화하는 데 탁월하지만 계산 비용이 높다. UMAP은 t-SNE의 장점을 유지하면서 더 효율적이고 글로벌 구조를 더 잘 보존한다.

각 방법의 특성을 이해하고 데이터 특성에 맞는 적절한 차원 축소 기법을 선택하면 데이터 분석과 머신러닝 모델링의 효율성과 성능을 크게 향상시킬 수 있다. 


$\mathbf{b} = (X^T X)^{-1} X^T \mathbf{y}$

