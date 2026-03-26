---
title: Marker - 성공하면 최고, 하지만 안정성이 문제인 PDF 파서
date: 2026-03-26
tags:
  - pdf-parser
  - document-ai
  - rag
  - marker
  - surya-ocr
  - layout-analysis
draft: false
enableToc: true
description: Marker v1.10.1의 내부 구조를 분석하고 READoc 벤치마크로 성능을 평가한다. Surya OCR 기반의 ML 파서로, 성공한 문서에서 80.6% Edit Similarity(5개 파서 중 최고)를 달성하지만, 63%의 문서에서 에러가 발생하여 안정성에 문제가 있다.
summary: Marker는 Vik Paruchuri(Datalab)가 개발한 GPL-3.0 PDF 파서로, Surya OCR을 기반으로 레이아웃 감지, 텍스트 인식, 테이블/수식 처리를 수행한다. READoc 벤치마크에서 성공한 34개 문서에 대해 80.6%의 Edit Similarity(최고 점수)를 기록했지만, 92개 중 58개(63%)가 Surya 모델의 토큰 길이 제한으로 실패하여 전체 평균은 29.8%에 그쳤다.
published: 2026-03-26
modified: 2026-03-26
---

> [!summary]
>
> Marker는 Vik Paruchuri(Datalab)가 개발한 GPL-3.0 PDF 파서로, Surya OCR 기반이다. READoc 벤치마크에서 성공한 문서의 **80.6% Edit Similarity(5개 파서 중 최고)**를 기록했지만, 63%의 문서에서 에러가 발생하여 **안정성이 최대 약점**이다.

## 개요

| 항목 | 내용 |
|---|---|
| **개발자** | Vik Paruchuri / Datalab |
| **GitHub** | [datalab-to/marker](https://github.com/datalab-to/marker) |
| **최신 버전** | v1.10.1 (2026-01-31) |
| **라이선스** | **GPL-3.0** (상용 제한) |
| **GitHub Stars** | ~33,000+ |
| **Python** | 3.10+ |
| **GPU 필요** | 선택 (MPS/CUDA 가속 가능) |
| **모델 크기** | ~2GB+ (Surya 모델들) |
| **관련 프로젝트** | [Surya OCR](https://github.com/datalab-to/surya) (동일 개발자) |

Marker는 같은 개발자가 만든 **Surya OCR**을 핵심 엔진으로 사용하는 PDF-to-Markdown 파서다. 90개 이상 언어를 지원하며, 학술 논문이나 복잡한 문서에서 **구조 보존 품질이 가장 높다**. 다만 GPL-3.0 라이선스와 안정성 문제가 걸림돌이다.

---

## 내부 파이프라인

```
PDF 입력
  → Surya 레이아웃 감지 (텍스트/테이블/이미지/수식 영역 분류)
  → Surya OCR (텍스트 인식, 90개 언어)
  → 테이블 구조 인식
  → 수식/코드 블록 감지
  → 읽기 순서 결정
  → Markdown 생성 (헤딩 레벨, 볼드/이탤릭, 이미지 참조)
```

### Surya OCR

Marker의 모든 OCR/레이아웃 작업을 담당하는 핵심 엔진:
- **레이아웃 감지**: 텍스트, 테이블, 이미지, 헤더, 수식 등 영역 분류
- **텍스트 인식**: 90개 이상 언어 지원
- **읽기 순서 감지**: 다단 레이아웃에서 자연스러운 읽기 순서
- **테이블 인식**: 셀 구조 감지 및 재구성

### Marker의 차별점

다른 파서들과 비교했을 때 Marker의 독특한 점:
- **헤딩 레벨 구분**: `#` H1, `##` H2를 정확히 구분 (MinerU/Docling/PyMuPDF4LLM은 단일 레벨)
- **위첨자/아래첨자**: `<sup>`, `<sub>` HTML 태그 처리
- **이미지 참조**: `![](_page_1_Figure_1.jpeg)` 형태로 이미지를 인라인 참조
- **코드 블록 감지**: 코드 영역을 별도로 인식
- **링크/참조**: `[\[1\]](#page-9-0)` 형태의 내부 참조 처리

---

## 설치 및 사용법

```bash
uv venv marker-env --python 3.12
source marker-env/bin/activate
uv pip install marker-pdf
```

### Python API

```python
from marker.converters.pdf import PdfConverter
from marker.models import create_model_dict
from marker.config.parser import ConfigParser

# 모델 로딩 (최초 1회, 시간 소요)
config = ConfigParser({})
model_dict = create_model_dict()
converter = PdfConverter(
    config=config.generate_config_dict(),
    artifact_dict=model_dict
)

# 변환
rendered = converter("input.pdf")
markdown = rendered.markdown
images = rendered.images  # dict: filename → PIL.Image
```

### 주요 설정

| 파라미터 | 설명 |
|---|---|
| `force_ocr` | 모든 페이지에 OCR 강제 적용 |
| `output_format` | 출력 형식 (markdown, json, html) |
| `languages` | OCR 언어 지정 |

---

## READoc 벤치마크 결과

### 결과

| 메트릭 | 값 |
|---|---|
| **Edit Similarity (성공분)** | **80.6%** ★ 최고 |
| **Edit Similarity (전체)** | 29.8% |
| **처리 시간** | 9,139초 (92문서, 152분) |
| **문서당 평균 (성공분)** | 237초 |
| **성공률** | **37% (34/92)** |

### 실패 원인 분석

58개 문서가 동일한 에러 패턴으로 실패:
```
index 8192 is out of bounds: 2, range 0 to 4756
```

이는 **Surya 모델의 토큰 시퀀스 길이 제한**(8192)을 초과하는 문서에서 발생한다. 긴 논문이나 페이지 수가 많은 문서에서 주로 발생하며, Marker/Surya의 알려진 한계다.

### 성공한 문서의 품질

성공했을 때의 출력 품질은 5개 파서 중 최고:

```markdown
# 1 Introduction

## 1.1 A Richer Picture of Academic Mathematics

What do mathematicians do? Ask a pure mathematician...

![](_page_1_Figure_1.jpeg)

Figure 1: A "mathematical pyramid"...
```

- `#` / `##` / `###` 헤딩 레벨 정확
- 이미지 인라인 참조 포함
- 위첨자 `<sup>` 처리
- 문단 분리 정확

### 파서 비교 (READoc)

| 파서 | Edit Sim | 속도 | 성공률 | 라이선스 |
|---|---|---|---|---|
| MinerU (MPS) | 77.2% | 69초 | 100% | AGPL |
| **Marker** (성공분) | **80.6%** | 237초 | **37%** | GPL |
| Docling | 74.3% | 4.9초 | 100% | MIT |
| PyMuPDF4LLM | 73.4% | 1.9초 | 100% | AGPL |
| LiteParse | 50.7% | 0.1초 | 100% | MIT |

---

## 장단점 분석

### 장점

- **최고 품질**: 성공한 문서에서 80.6% Edit Similarity
- **헤딩 레벨 정확**: 유일하게 H1/H2/H3 구분 가능
- **풍부한 Markdown**: 위첨자, 이미지 참조, 코드 블록, 링크 처리
- **90개 언어**: Surya OCR 기반 다국어 지원
- **이미지 출력**: PIL.Image 객체로 직접 제공

### 단점

- **안정성 문제**: 63% 실패율 (토큰 길이 제한)
- **느린 속도**: 성공해도 237초/문서
- **GPL-3.0 라이선스**: 상용 서비스 포함시 소스 공개 의무
- **높은 메모리**: ~5.2GB RAM 사용
- **모델 로딩 시간**: 첫 실행 시 수 분 소요
- **수식 LaTeX**: 제한적 (MinerU보다 약함)

---

## 추천 사용처

| 사용처 | 적합도 | 이유 |
|---|---|---|
| 짧은 문서 (< 10페이지) | ★★★★☆ | 토큰 제한 회피, 최고 품질 |
| 학술 논문 (짧은 것) | ★★★★☆ | 헤딩/참조/이미지 구조 보존 |
| 대량 배치 처리 | ★★☆☆☆ | 63% 실패 + 느린 속도 |
| 상용 프로젝트 | ★★☆☆☆ | GPL-3.0 제약 |
| 긴 문서 (50+ 페이지) | ★☆☆☆☆ | 토큰 제한으로 거의 확실히 실패 |

---

## 정리

Marker는 **"성공하면 최고, 하지만 성공을 보장할 수 없는"** 파서다. 80.6%의 Edit Similarity는 테스트한 5개 파서 중 최고이며, 헤딩 레벨 구분, 이미지 참조, 위첨자 처리 등 Markdown 품질이 가장 풍부하다.

하지만 63% 실패율과 237초/문서의 처리 시간은 프로덕션 환경에서 치명적이다. **짧은 문서를 소량으로 처리하는 경우**에만 추천하며, 대량 처리나 안정성이 중요하다면 [[2026-03-26-Docling-PDF-파서-분석|Docling]](MIT, 100% 성공, 4.9초)이나 [[2026-03-23-MinerU-2x-파이프라인-분석|MinerU]](AGPL, 100% 성공, 69초)가 더 적합하다.

---


> 이 파서의 헤딩/테이블/수식/이미지 처리 결과를 다른 파서와 직접 비교한 글: [[2026-03-26-PDF-파서-5종-비교-분석|PDF 파서 5종 비교 분석]]

## 참고

- [Marker GitHub](https://github.com/datalab-to/marker)
- [Surya OCR GitHub](https://github.com/datalab-to/surya)
- [[2026-03-26-Docling-PDF-파서-분석]] — Docling 분석
- [[2026-03-23-MinerU-2x-파이프라인-분석]] — MinerU 2.x 분석
- [[2026-03-25-PyMuPDF4LLM-PDF-파서-분석]] — PyMuPDF4LLM 분석
- [[2026-03-26-LiteParse-PDF-파서-분석]] — LiteParse 분석
