---
title: Tensorflow Deep-Learning Computer-Vision Guide Notes 2
date: 2022-08-11
tags:
- deep-learning
- computer-vision
- tensorflow
- object-detection
- localization
- region-proposal
draft: false
enableToc: true
description: 컴퓨터 비전에서 객체 탐지(Object Detection)와 위치 찾기(Localization) 개념 및 Region Proposal
  방식에 대해 설명한 글이다.
summary: "객체 탐지(Object Detection)와 객체 위치 찾기(Localization)의 개념과 차이점을 설명하고, Bounding Box 학습 방법과 Region Proposal 기법을 다룬다. 특히 여러 객체를 동시에 감지하는 방법과 슬라이딩 윈도우 접근법의 원리와 한계에 대해 살펴본다."
published: 2022-08-11
modified: 2022-08-11
---
## 객체 위치 찾기와 탐지의 이해

컴퓨터 비전 분야에서 객체를 인식하는 두 가지 주요 기술인 객체 위치 찾기(Localization)와 객체 탐지(Detection)에 대해 알아본다.

### 객체 위치 찾기(Object Localization) 개요

객체 위치 찾기는 하나의 이미지에 하나의 주요 객체가 있을 때, 해당 객체의 위치와 클래스를 동시에 예측하는 기술이다.

#### 핵심 개념
- **FC Layer**: Fully Connected Layer로, 특징 맵에서 추출한 정보를 바탕으로 클래스 분류 및 위치 정보 추출
- **Annotation 파일**: 라벨과 유사하게 객체 정보를 담고 있는 파일
  - Bounding Box의 꼭지점 좌표값 포함
  - YOLO의 경우 Bounding Box의 중앙점 좌표값 사용

#### Bounding Box 학습
객체 위치 찾기에서는 클래스 분류와 함께 Bounding Box Regression을 동시에 진행한다. 특징 맵에서 특정 특성이 감지되면 해당 위치에 대한 경계 상자 회귀를 수행한다.

<br>
<p align="center">
<img width="827" alt="Bounding Box 학습 과정" src="https://user-images.githubusercontent.com/99532836/184108231-3712ea60-416d-4895-bf35-b3de4aca67f9.png">
</p>
<br>

- **Class Confidence Score**: 예측된 객체가 특정 클래스에 속할 확률 (예: 객체가 자동차일 확률 0.9)

---

### 객체 탐지(Object Detection)
객체 탐지는 이미지 내에 있는 두 개 이상의 객체를 동시에 감지하고 분류하는 기술이다. 단순히 경계 상자만 모델에 입력하면 추론 자체가 어려워지기 때문에, 객체가 있을 만한 위치를 먼저 찾은 후 해당 영역의 객체를 예측하는 방법을 사용한다.

- **Region Proposal**: 객체가 있을 만한 위치를 제안하는 기법

객체 탐지는 [[Tensorflow Deep-Learning Computer-Vision Guide Notes1|이전 글]]에서 설명한 기본 개념을 확장하여, 실제 응용 분야에서 활용된다. 특히 [[Anomaly Detection|이상 탐지]]와 결합될 때 산업 현장의 결함 감지 등에 유용하게 사용된다.

---

## Region Proposal(영역 추정)의 이해

객체 탐지에서는 원본 이미지에서 특징 추출 레이어를 통해 추상화된 특징 레이어를 생성한 후, 객체가 있을 만한 영역을 추정하는 과정이 필요하다.

### 슬라이딩 윈도우 방식

슬라이딩 윈도우는 가장 기본적인 영역 추정 방식으로, 다음과 같은 특징이 있다:

- 다양한 형태의 윈도우를 한 칸씩 이동하면서 윈도우 내의 객체를 찾음
- 왼쪽 상단에서 오른쪽 하단까지 순차적으로 탐색
- **단점**: 
  - 윈도우 크기와 객체 크기, 형태에 따라 감지가 어려울 수 있음
  - 모든 영역을 순차적으로 탐색하기 때문에 처리 시간이 오래 걸림

> [!Note]
> 슬라이딩 윈도우 방식은 간단하지만 계산 비용이 높아 실시간 객체 탐지에는 적합하지 않다. 이를 개선하기 위해 선택적 검색(Selective Search)과 같은 더 효율적인 Region Proposal 기법이 개발되었다.

---

## 고급 객체 탐지 알고리즘

슬라이딩 윈도우의 단점을 극복하기 위해 개발된 고급 객체 탐지 알고리즘들에 대해 알아본다.

### R-CNN 계열
R-CNN(Region-based Convolutional Neural Network)은 Region Proposal과 CNN을 결합한 알고리즘으로, 다음과 같은 발전 과정을 거쳤다:

1. **R-CNN**: 
   - 선택적 검색을 통해 약 2,000개의 영역 후보 생성
   - 각 영역을 동일한 크기로 변환 후 CNN에 입력
   - 각 영역에 대해 개별적으로 특징 추출 및 분류
   - **단점**: 계산 비용이 높고 속도가 느림

2. **Fast R-CNN**: 
   - 전체 이미지를 한 번만 CNN으로 처리하여 특징 맵 생성
   - RoI(Region of Interest) 풀링 적용으로 효율성 증가
   - 분류와 경계 상자 회귀를 동시에 수행
   - **장점**: R-CNN보다 20배 이상 빠름

3. **Faster R-CNN**: 
   - Region Proposal Network(RPN)을 도입하여 선택적 검색 대체
   - 특징 맵에서 직접 영역 제안을 생성하는 end-to-end 학습 가능
   - **장점**: Fast R-CNN보다 10배 이상 빠르며, 정확도도 향상

### YOLO(You Only Look Once)
YOLO는 이미지를 한 번만 보고 객체의 위치와 클래스를 동시에 예측하는 실시간 객체 탐지 알고리즘이다.

#### YOLO의 주요 특징:
- 이미지를 고정된 크기의 그리드로 나눔
- 각 그리드 셀에서 경계 상자와 클래스 확률을 예측
- 단일 네트워크로 전체 감지 과정을 완료
- **장점**: 매우 빠른 속도(45-155 FPS), 전체 이미지의 컨텍스트 활용
- **단점**: 작은 객체 탐지에 상대적으로 취약

```python
# YOLO v3 구현 예시 (TensorFlow)
from tensorflow.keras.models import load_model
import cv2
import numpy as np

# 모델 로드
model = load_model('yolov3.h5')

# 이미지 전처리
def preprocess_image(img_path, img_size=416):
    image = cv2.imread(img_path)
    image = cv2.resize(image, (img_size, img_size))
    image = image / 255.0  # 정규화
    image = np.expand_dims(image, axis=0)
    return image

# 예측 및 결과 처리
def detect_objects(image):
    predictions = model.predict(image)
    # 예측 결과 처리 로직...
    return processed_results
```

---

## 객체 탐지의 평가 지표

객체 탐지 모델의 성능을 평가하기 위한 주요 지표들은 다음과 같다:

### IoU(Intersection over Union)
- 예측된 경계 상자와 실제 경계 상자의 겹치는 정도를 측정
- 수식: IoU = 겹치는 영역 / 합집합 영역
- 일반적으로 0.5 이상이면 올바른 탐지로 간주

### mAP(mean Average Precision)
- 각 클래스별 Average Precision의 평균
- Precision-Recall 곡선 아래 면적으로 계산
- COCO 데이터셋에서는 다양한 IoU 임계값(0.5:0.05:0.95)에서의 mAP를 평균하여 사용

### FPS(Frames Per Second)
- 초당 처리할 수 있는 프레임 수
- 실시간 응용에서 중요한 지표
- YOLO와 같은 One-stage detector가 일반적으로 높은 FPS를 보임

---

## 결론

객체 위치 찾기와 객체 탐지는 컴퓨터 비전 분야의 핵심 기술로, 자율주행차, 얼굴 인식, 의료 영상 분석 등 다양한 응용 분야에서 활용된다. 특히 Region Proposal 기법과 슬라이딩 윈도우 접근법은 객체 탐지 알고리즘의 기본 개념으로, 이를 이해하는 것이 고급 객체 탐지 모델을 이해하는 데 중요하다.

최근에는 [[T-SNE|t-SNE]]와 같은 차원 축소 기법을 활용하여 특징 공간을 시각화하고 분석하는 연구도 진행되고 있다. 또한 [[차원 축소 (Dimensionality Reduction) 기법|다양한 차원 축소 방법]]을 통해 모델의 복잡도를 줄이면서도 성능을 유지하는 방법이 연구되고 있다.

객체 탐지 기술은 계속해서 발전하고 있으며, 더 정확하고 빠른 알고리즘의 개발이 기대된다. 