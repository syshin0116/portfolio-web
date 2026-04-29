---
title: "Transformer 아키텍처"
type: concept
tags:
  - transformer
  - attention
  - nlp
  - deep-learning
  - ai
  - seq2seq
  - python
  - tensorflow
summary: "Transformer는 RNN의 기울기 소실과 고정 크기 컨텍스트 벡터 문제를 Attention 메커니즘으로 해결한 아키텍처다. Q-K-V Attention으로 입력 시퀀스 전체에서 중요 정보를 동적으로 가중하며, Positional Encoding으로 위치 정보를 보완한다. 학습 시 Teacher Forcing을 사용해 수렴 속도를 높인다."
sources:
  - content/Study/SeSAC/2023-11-29-Transformers 강의 정리.md
  - content/Study/SeSAC/2023-11-30-Transformers 실습.md
created: 2026-04-26
updated: 2026-04-26
author: wiki-curator
draft: false
---

## Key Claims

- Seq2Seq의 두 가지 문제: (1) RNN 사용으로 긴 시퀀스에서 **기울기 소실** 발생, (2) 인코더가 가변 길이 입력을 **고정 크기 벡터**로 압축하는 과정에서 정보 손실.[^1]
- Attention Function: Q(Query, 현재 디코더 상태) · K(Key, 인코더 은닉 상태들) · V(Value, 인코더 은닉 상태들) 세 요소로 입력과 가장 관련 있는 정보를 동적으로 탐색한다.[^1]
- Transformer: 인코더는 문장 전체를 입력받고(최대 512 tokens), 디코더는 단어 하나씩 생성한다.[^1]
- **Teacher Forcing**: 학습 중 이전 예측 대신 실제 정답 토큰을 다음 입력으로 제공한다. 학습 속도·효율 향상이 장점이지만, 과도한 의존 시 추론 성능 저하 위험.[^1]
- Positional Encoding: 짝수 인덱스(2i)에 사인, 홀수 인덱스(2i+1)에 코사인 함수를 적용해 위치 정보를 임베딩에 주입한다.[^2]

## Examples / Code

Attention 예시 (한국어→영어 번역):
- Query: '나는'
- Key: 학습 데이터의 유사 구조/의미 요소들
- Value: 영어 문장 구조 요소 → 'I'

Positional Encoding (TensorFlow):

```python
class PositionalEncoding(tf.keras.layers.Layer):
    def get_angles(self, position, i, d_model):
        angles = 1 / tf.pow(10000, (2 * (i // 2)) / tf.cast(d_model, tf.float32))
        return position * angles

    def positional_encoding(self, position, d_model):
        angle_rads = self.get_angles(
            position=tf.range(position, dtype=tf.float32)[:, tf.newaxis],
            i=tf.range(d_model, dtype=tf.float32)[tf.newaxis, :],
            d_model=d_model)
        # 짝수 인덱스 → sin
        sines = tf.math.sin(angle_rads[:, 0::2])
        # 홀수 인덱스 → cos
        cosines = tf.math.cos(angle_rads[:, 1::2])
        angle_rads = np.zeros(angle_rads.shape)
        angle_rads[:, 0::2] = sines
        angle_rads[:, 1::2] = cosines
        return tf.cast(tf.constant(angle_rads)[tf.newaxis, ...], tf.float32)
```

## Connections

- [[object-detection]] - Transformer의 attention 개념은 이후 Vision Transformer(ViT) 등 컴퓨터 비전에도 적용됨

## Footnotes

[^1]: content/Study/SeSAC/2023-11-29-Transformers 강의 정리.md
[^2]: content/Study/SeSAC/2023-11-30-Transformers 실습.md
