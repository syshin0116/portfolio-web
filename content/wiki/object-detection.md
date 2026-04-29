---
title: "딥러닝 객체 탐지(Object Detection)"
type: concept
tags:
  - object-detection
  - deep-learning
  - computer-vision
  - ai
  - cnn
  - rcnn
  - yolo
  - ssd
  - python
summary: "객체 탐지는 Region Proposal → Feature Extraction → NMS 세 단계 파이프라인으로 구성된다. R-CNN에서 시작해 Fast R-CNN, Faster R-CNN(RPN), SSD, YOLO로 발전하며 속도와 정확도를 개선했다. 성능 지표는 mAP(클래스별 AP의 평균)를 사용한다."
sources:
  - content/Study/SeSAC/2023-11-17-딥러닝 영상처리.md
  - content/Study/SeSAC/2023-11-20-딥러닝 영상처리2.md
  - content/Study/SeSAC/2023-11-22-딥러닝 영상처리3.md
  - content/Study/SeSAC/2023-11-23-딥러닝 영상처리4.md
created: 2026-04-26
updated: 2026-04-26
author: wiki-curator
draft: false
---

## Key Claims

### 기초: LeNet-5와 System 1/2

- LeNet-5(LeCun, 1998): Conv → AvgPool → Conv → AvgPool → FC 구조. 레이어가 적어 tanh activation으로도 동작.[^1]
- NeurIPS 2019 System 1/2: Kahneman의 인지 심리학을 AI에 적용. System 1(빠르고 직관적) vs System 2(느리고 논리적) → 각각 다른 알고리즘 설계 방향.[^1]

### 탐지 파이프라인

- 일반 객체 탐지 프레임워크 3단계: (1) Region Proposal, (2) Feature Extraction + CNN 예측, (3) Non-Maximum Suppression(NMS).[^2]
- **NMS**: 중복 경계 상자 중 IoU(Intersection over Union)가 임계값 이상인 박스를 제거해 최적 박스 하나만 남긴다.[^3]
- **Selective Search**: 색상·질감 유사 영역을 병합하며 RoI 후보를 생성하는 2단계 방법. R-CNN에 사용.[^3]

### R-CNN 계열 진화

| 모델 | 방식 | 단점 |
|------|------|------|
| R-CNN | Selective Search → 각 영역마다 CNN | 매우 느림 |
| Fast R-CNN | 전체 이미지 CNN → RoI Pooling | Selective Search 병목 |
| Faster R-CNN | RPN으로 Selective Search 대체 | - |

[^3]

- **RPN(Region Proposal Network)**: Faster R-CNN에서 Selective Search를 대체. Anchor Box로 후보 영역을 빠르게 생성.[^3]
- **Anchor Box**: 각 위치에 미리 정의된 크기/비율의 박스들. Selective Search보다 계산량이 적어 추론 속도가 빠르다.[^3]

### SSD와 YOLO

- **SSD(Single Shot Detection)**: Selective Search 없이 Multi-Scale Feature Layer에서 Anchor Box를 직접 사용. 다양한 크기 객체를 하나의 패스로 탐지.[^4]
- SSD 분류기 노드 수: `3×3×(4×(classes+4))`. Anchor Box 4개, 좌표 4개.[^4]
- **YOLO**: 이미지를 S×S Grid로 분할, 각 셀이 Object Detection 수행. 속도 최우선 설계.[^4]

### 평가 지표

- **mAP(mean Average Precision)**: 클래스별 Precision-Recall 곡선 아래 면적(AP)을 평균. 모든 클래스에 걸친 성능 평균이다.[^4]
- **IoU**: 예측 박스와 실제 박스의 교집합/합집합 비율. NMS와 mAP 계산에 사용.[^2]

## Examples / Code

LeNet-5 Keras 구현:

```python
from keras.models import Sequential
from keras.layers import Conv2D, AveragePooling2D, Flatten, Dense

model = Sequential([
    Conv2D(6, kernel_size=(5,5), activation='tanh', input_shape=input_shape, padding='same'),
    AveragePooling2D(pool_size=(2,2), strides=2),
    Conv2D(16, kernel_size=(5,5), activation='tanh', padding='valid'),
    AveragePooling2D(pool_size=(2,2), strides=2),
    Conv2D(120, kernel_size=(5,5), activation='tanh', padding='valid'),
    Flatten(),
    Dense(84, activation='tanh'),
    Dense(num_classes, activation='softmax')
])
```

Selective Search 설치 및 사용:

```bash
pip install selectivesearch
```

## Connections

- [[transformer-architecture]] - Transformer의 attention 메커니즘은 이후 Vision Transformer(ViT)를 통해 객체 탐지에도 적용됨

## Footnotes

[^1]: content/Study/SeSAC/2023-11-17-딥러닝 영상처리.md
[^2]: content/Study/SeSAC/2023-11-20-딥러닝 영상처리2.md
[^3]: content/Study/SeSAC/2023-11-22-딥러닝 영상처리3.md
[^4]: content/Study/SeSAC/2023-11-23-딥러닝 영상처리4.md
