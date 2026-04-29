---
title: OpenDataLoader PDF v2 - Java 기반 Apache 2.0 PDF 파서
date: 2026-03-27
tags:
  - pdf-parser
  - document-ai
  - rag
  - opendataloader
  - java
  - apache-license
draft: false
enableToc: true
description: OpenDataLoader PDF v2.1.1의 READoc 벤치마크 결과와 파싱 예시를 분석한다. Java 기반 Apache 2.0 파서로, 72.6% Edit Similarity에 ~3초/문서 속도를 보여주지만, 테이블 구조 보존과 수식 LaTeX 변환에 한계가 있다.
summary: "OpenDataLoader PDF v2는 Hancom이 개발한 Java 기반 Apache 2.0 PDF 파서다. READoc 72.6%, 91% 성공률, ~3초/문서. 이미지 추출 O, 하지만 테이블 구조 보존과 수식 LaTeX 변환은 미지원."
published: 2026-03-27
modified: 2026-03-27
---
## 개요

| 항목 | 내용 |
|---|---|
| **개발사** | Hancom (한컴) - 한글(HWP) 개발사, 한국 오피스 소프트웨어 1위 |
| **GitHub** | [opendataloader-project/opendataloader-pdf](https://github.com/opendataloader-project/opendataloader-pdf) |
| **GitHub Stars** | ~9,600 (2026.03 #1 Trending, 하루 1,394스타) |
| **최신 버전** | v2.1.1 (2026-03-26) |
| **라이선스** | **Apache 2.0** (v2.0부터, 이전 MPL 2.0) |
| **런타임** | Java 11+ (JAR 번들) + Python/Node.js/Maven wrapper |
| **GPU 필요** | X (local 모드), hybrid 모드는 AI 백엔드 필요 |
| **PyPI** | `pip install opendataloader-pdf` |

### 두 가지 모드

| 모드 | 방식 | 정확도 | 속도 | GPU |
|---|---|---|---|---|
| **Local** (기본) | PDF 내부 구조 직접 추출 | 0.72 | **0.05초/페이지** | X |
| **Hybrid** | Local + AI 백엔드 (Docling) | **0.90** | 0.43초/페이지 | 선택 |

이번 테스트는 **Local 모드만** 사용했다. Hybrid 모드는 별도 서버(`opendataloader-pdf-hybrid`) 실행이 필요하여 미테스트.

### 차별화 기능

- **XY-Cut++**: 개선된 읽기 순서 알고리즘 (0.94 정확도)
- **바운딩 박스**: 모든 요소에 `[left, bottom, right, top]` 좌표 제공
- **프롬프트 인젝션 감지**: 숨겨진 텍스트, 투명 폰트, 페이지 밖 콘텐츠 자동 필터 (기본 활성)
- **개인정보 마스킹**: `--sanitize` 옵션 (이메일, 전화번호, IP, 신용카드)
- **Tagged PDF 지원**: PDF 구조 태그 읽기 (접근성)
- **MCP 서버**: v2.1.1에서 AI 에이전트 통합용 MCP 추가

---

## 설치 및 사용법

```bash
# Java 필요
brew install openjdk  # macOS

# Python 패키지 설치 (JAR 번들 포함)
uv pip install opendataloader-pdf
```

### Python API

```python
from opendataloader_pdf import convert

# 기본 변환 (Markdown)
convert(input_path="input.pdf", output_dir="./output", format="markdown")

# JSON + Markdown
convert(input_path="input.pdf", output_dir="./output", format="json,markdown")

# 옵션
convert(
    input_path="input.pdf",
    output_dir="./output",
    format="markdown",
    reading_order="xycut",      # XY-Cut++ 읽기 순서
    table_method="cluster",     # 테이블 감지 방식
    image_output="embedded",    # 이미지 추출
    quiet=True,
)
```

### 주요 옵션

| 파라미터 | 설명 |
|---|---|
| `format` | `json`, `text`, `html`, `markdown`, `markdown-with-images` |
| `table_method` | `default` (border), `cluster` (border+cluster) |
| `reading_order` | `off`, `xycut` |
| `image_output` | 이미지 추출 설정 |
| `sanitize` | 개인정보 마스킹 (이메일, 전화번호, IP 등) |
| `content_safety_off` | hidden-text, off-page, tiny 등 안전 필터 |

---

### 파싱 결과 예시 (Attention Is All You Need)

#### 헤딩

![원본 PDF 1페이지](https://i.imgur.com/yGlyfRM.png)

```markdown
# arXiv:1706.03762v7[cs.CL]2 Aug 2023
#### Attention Is All You Need
###### Abstract
###### 1 Introduction
###### 2 Background
###### 3 Model Architecture
```

`####`(H4)를 제목에, `######`(H6)를 섹션에 사용하는 독특한 매핑. 계층은 구분되지만 관례적이지 않다.

#### 테이블 (Table 1)

![원본 Table 1](https://i.imgur.com/6G5zOeN.png)

```
Layer Type Complexity per Layer Sequential Maximum Path Length

Operations Self-Attention O(n2 · d) O(1) O(1) Recurrent O(n · d2) O(n) O(n)
Convolutional O(k · n · d2) O(1) O(logk(n)) Self-Attention (restricted) O(r · n · d) O(1) O(n/r)
```

**Markdown 테이블 구문 없이 텍스트로만 추출**. 테이블 구조가 완전히 손실됨 - 이 부분이 가장 큰 약점.

#### 수식

![원본 수식](https://i.imgur.com/1u67v7H.png)

```
QKT √dk
Attention(Q,K,V ) = softmax(         )V (1)
```

LaTeX 미지원. 텍스트로만 추출.

#### 이미지

```markdown
![image 1](04_complex_layout_images/imageFile1.png)
Figure 1: The Transformer - model architecture.
```

이미지 추출 O - `![image N]()` 형태로 Markdown에 참조. MinerU/Marker와 유사한 방식.

---

## READoc 벤치마크 결과

| 메트릭 | 값 |
|---|---|
| **Edit Similarity (전체)** | **66.1%** |
| **Edit Similarity (성공분)** | **72.6%** |
| **Median** | 75.9% |
| **성공률** | 91/100 |
| **속도 (중앙값)** | ~3초/문서 |

### 파서 비교

| 파서 | 성공률 | Sim(성공분) | 속도 | 라이선스 |
|---|---|---|---|---|
| MinerU | 92% | 77.2% | 69초 | AGPL |
| Marker | 34% | 80.6% | 237초 | GPL |
| Docling | 92% | 74.3% | 3.4초 | MIT |
| PyMuPDF4LLM | 92% | 73.4% | 1.9초 | AGPL |
| **OpenDataLoader** | **91%** | **72.6%** | **~3초** | **Apache 2.0** |
| LiteParse | 92% | 50.7% | 0.1초 | Apache 2.0 |

### 관찰

- Local 모드로만 테스트하여 Docling(74.3%)보다 약간 낮음 (72.6%)
- **Hybrid 모드를 사용하면 훨씬 높을 것으로 예상** (공식 벤치마크 0.90)
- 테이블이 텍스트로만 추출되는 것이 Local 모드의 가장 큰 약점
- Apache 2.0 라이선스 + 이미지 추출 지원은 Docling 대비 장점
- 일부 문서에서 Java StackOverflowError 발생 (긴 헤딩 체인 재귀)

### 공식 벤치마크 참고 (opendataloader-bench, 200문서)

| 파서 | Overall | 읽기 순서 | 테이블 | 헤딩 | 속도 |
|---|---|---|---|---|---|
| **OpenDataLoader hybrid** | **0.90** | **0.94** | **0.93** | 0.83 | 0.43s/p |
| Docling | 0.86 | 0.90 | 0.89 | 0.80 | 0.73s/p |
| OpenDataLoader local | 0.84 | 0.91 | 0.49 | 0.74 | **0.05s/p** |
| Marker | 0.83 | 0.89 | 0.81 | 0.80 | 53.9s/p |
| MinerU | 0.82 | 0.86 | 0.87 | 0.74 | 5.96s/p |
| PyMuPDF4LLM | 0.57 | 0.89 | 0.40 | 0.41 | 0.09s/p |

> 이 벤치마크는 OpenDataLoader 팀이 자체 제작한 것이므로, 객관성에 유의 필요. 다만 벤치마크 코드는 [opendataloader-bench](https://github.com/opendataloader-project/opendataloader-bench)에서 재현 가능.

---

## 장단점

### 장점
- **Apache 2.0 라이선스**
- **이미지 추출** 지원
- **XY-Cut++** 읽기 순서 알고리즘
- **개인정보 마스킹** (`sanitize` 옵션)
- **프롬프트 인젝션 감지** (보안 기능)
- GPU 불필요

### 단점
- **테이블 구조 손실** - Markdown 테이블 미생성
- **수식 LaTeX 미지원**
- **Java 런타임 필요** (Python/Node.js만으로 안 됨)
- 일부 문서에서 StackOverflowError
- 헤딩 레벨 매핑이 관례적이지 않음 (H4/H6 사용)

---

## 추천 사용처

| 사용처 | 적합도 | 이유 |
|---|---|---|
| Apache 2.0 필수 + 이미지 추출 | ★★★★☆ | Docling(MIT)과 달리 이미지 추출 지원 |
| 보안 문서 처리 | ★★★★☆ | 개인정보 마스킹, 프롬프트 인젝션 감지 |
| 테이블 중심 문서 | ★★☆☆☆ | 테이블 구조 손실 |
| 수식 많은 학술 논문 | ★☆☆☆☆ | LaTeX 미지원 |

---

## 참고

- [OpenDataLoader GitHub](https://github.com/opendataloader-project/opendataloader-pdf)
- [PyPI: opendataloader-pdf](https://pypi.org/project/opendataloader-pdf/)
- [[2026-03-26-PDF-파서-5종-비교-분석|PDF 파서 5종 비교]]
- [[2026-03-26-Docling-PDF-파서-분석|Docling 분석]] - 같은 Apache 2.0/MIT 진영

> 이 파서의 헤딩/테이블/수식/이미지 처리 결과를 다른 파서와 직접 비교한 글: [[2026-03-26-PDF-파서-5종-비교-분석|PDF 파서 5종 비교 분석]]
