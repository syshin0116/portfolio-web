---
title: PyMuPDF4LLM - 경량 GNN으로 GPU 없이 가장 빠른 PDF 파서
date: 2026-03-25
tags:
  - pdf-parser
  - document-ai
  - rag
  - pymupdf
  - ocr
  - markdown
draft: false
enableToc: true
description: PyMuPDF4LLM v1.27.2.2의 내부 구조를 분석하고, 4종 문서(영문 논문, 한국어 보고서, PPT 슬라이드, 복잡한 레이아웃)로 성능을 테스트한다. 경량 GNN 모델(ONNX)로 레이아웃을 분석하고 규칙 기반으로 텍스트를 추출하여, 페이지당 0.05~0.25초의 압도적 속도를 보여준다.
summary: "PyMuPDF4LLM은 Artifex Software의 MuPDF 엔진 위에 구축된 PDF-to-Markdown 변환기다. PDF 내부 구조를 직접 파싱하고, pymupdf-layout의 경량 GNN 모델(ONNX Runtime)로 레이아웃을 분석하여 페이지당 0.05~0.25초의 압도적 속도를 달성한다. GPU 불필요, 의존성 최소, 설치 즉시 사용 가능하지만, 수식 LaTeX 변환 불가, 스캔 문서 OCR 제한, 헤딩 레벨 부정확 등의 한계가 있다."
published: 2026-03-25
modified: 2026-03-25
---
## 개요

| 항목 | 내용 |
|---|---|
| **개발사** | Artifex Software (MuPDF 개발사) |
| **GitHub** | [pymupdf/pymupdf4llm](https://github.com/pymupdf/pymupdf4llm) |
| **최신 버전** | v1.27.2.2 (2026-03-20) |
| **라이선스** | AGPL-3.0 (상용 라이선스 별도 구매 가능) |
| **GitHub Stars** | ~1,465 (PyMuPDF 본체: ~9,300) |
| **Python** | 3.10+ |
| **GPU 필요** | X (ONNX Runtime CPU 추론) |
| **모델 다운로드** | pymupdf-layout에 GNN 모델 내장 (별도 다운로드 불필요) |
| **설치 크기** | ~84KB (pymupdf4llm) + PyMuPDF + pymupdf-layout |
| **상용 라이선스** | Artifex에서 별도 구매 가능 (AGPL 회피) |
[]()
PyMuPDF4LLM은 [[MinerU - PDF Parser|MinerU]]나 Docling 같은 대형 ML 파서와 다른 접근을 취한다. YOLO, Transformer 같은 무거운 모델 대신 PDF 내부의 텍스트 객체, 폰트 정보, 좌표 데이터를 직접 읽고, 레이아웃 분석에만 **경량 GNN 모델**(ONNX Runtime, CPU 추론)을 사용한다. 무거운 추론 단계가 없는 만큼 처리 속도가 다른 ML 파서들과 차원이 다르다.

---

## 기술 배경

### PyMuPDF / MuPDF / PyMuPDF4LLM 관계

```
MuPDF (C 라이브러리, Artifex)
  └── PyMuPDF (Python 바인딩)
       ├── pymupdf-layout (레이아웃 분석 모듈)
       └── PyMuPDF4LLM (LLM/RAG용 Markdown 변환)
```

- **MuPDF**: Artifex Software가 개발한 경량 PDF/XPS 렌더링 엔진 (C 언어)
- **PyMuPDF** (`fitz`): MuPDF의 Python 바인딩. PDF 읽기/쓰기/렌더링
- **pymupdf-layout**: PDF 텍스트 레이아웃 분석 확장 모듈 (다단 감지, 읽기 순서)
- **PyMuPDF4LLM**: 위 세 라이브러리를 활용하여 LLM/RAG에 최적화된 Markdown 출력 생성

### 핵심 특징: 경량 ML + 규칙 기반 하이브리드

PDF 내부 구조를 직접 활용하되, 레이아웃 분석에는 경량 ML을 사용한다:

- **텍스트 추출**: PDF 텍스트 객체에서 직접 추출 - 규칙 기반 (OCR 불필요, 텍스트 PDF인 경우)
- **레이아웃 분석**: `pymupdf-layout`의 **GNN(Graph Neural Network)** 모델 - 텍스트 박스를 노드, 공간 관계를 엣지로 처리하여 제목/단락/표/그림 패턴 학습. **ONNX Runtime**으로 CPU 추론 (GPU 불필요)
- **헤딩 감지**: 폰트 크기와 볼드 여부로 판별 - 규칙 기반
- **테이블 감지**: PDF 내부의 선(line) 객체와 텍스트 좌표로 테이블 구조 추론 - 규칙 기반
- **이미지 추출**: PDF 내장 이미지 객체 직접 추출 - 규칙 기반
- **다단 감지**: GNN 레이아웃 분석 + XY-Cut 알고리즘

> "Heuristics do the heavy lifting upfront, so the model doesn't have to" - 휴리스틱이 특성을 먼저 추출하고, GNN은 패턴 분류만 수행하는 구조다.

---

## 내부 파이프라인

```
PDF 입력
  → pymupdf.open() (PDF 파싱)
  → StructTreeRoot 제거 (성능 최적화)
  → 페이지별 처리:
      ├── OCR 필요 여부 판단 (analyze_page)
      ├── (필요시) OCR 실행 (Tesseract/PaddleOCR/RapidOCR)
      ├── pymupdf-layout으로 레이아웃 분석 (GNN + ONNX Runtime)
      │   ├── 텍스트 블록 → 그래프 노드/엣지 변환
      │   ├── GNN 모델로 블록 분류 (title/text/table/picture)
      │   ├── 다단 감지 (Stripe-based Column Clustering)
      │   └── 읽기 순서 결정
      ├── 폰트 크기 기반 헤딩 감지
      ├── 선(line) + 가상선(virtual line) 기반 테이블 감지
      └── 이미지 객체 추출
  → ParsedDocument 생성
  → to_markdown() / to_json() / to_text() 변환
```

### OCR 모드

PyMuPDF4LLM은 기본적으로 텍스트 PDF에서 직접 추출하지만, 스캔 문서를 위한 OCR 폴백을 지원한다:

| 모드 | 설명 |
|---|---|
| `SELECT_REMOVING_OLD` | (기본값) 페이지 분석 후 필요시에만 OCR, 기존 텍스트 제거 |
| `SELECT_PRESERVING_OLD` | 필요시 OCR, 기존 텍스트 보존 |
| `ALWAYS_REMOVING_OLD` | 모든 페이지 OCR, 기존 텍스트 제거 |
| `ALWAYS_PRESERVING_OLD` | 모든 페이지 OCR, 기존 텍스트 보존 |
| `NEVER` | OCR 사용 안 함 |

지원 OCR 엔진: Tesseract, PaddleOCR, RapidOCR

---

## 설치 및 사용법

```bash
uv venv pymupdf-env --python 3.12
source pymupdf-env/bin/activate
uv pip install pymupdf4llm

# OCR 기능 추가 시
uv pip install "pymupdf4llm[ocr]"       # Tesseract
uv pip install "pymupdf4llm[layout]"    # 레이아웃 분석 강화
```

### Python API

```python
import pymupdf4llm

# 기본 사용
md = pymupdf4llm.to_markdown("input.pdf")

# 이미지 추출 포함
md = pymupdf4llm.to_markdown("input.pdf", write_images=True, image_path="./images")

# 페이지별 청크
chunks = pymupdf4llm.to_markdown("input.pdf", page_chunks=True)

# JSON 출력
data = pymupdf4llm.to_json("input.pdf")

# OCR 강제 적용
md = pymupdf4llm.to_markdown("input.pdf", force_ocr=True, ocr_language="kor")
```

### 주요 파라미터

| 파라미터 | 기본값 | 설명 |
|---|---|---|
| `write_images` | False | 이미지를 파일로 저장 |
| `embed_images` | False | 이미지를 base64로 인라인 삽입 |
| `page_chunks` | False | 페이지별로 분리된 청크 반환 |
| `force_ocr` | False | 모든 페이지에 OCR 강제 적용 |
| `ocr_language` | "eng" | OCR 언어 |
| `dpi` | 150 | 이미지 추출 해상도 |
| `ocr_dpi` | 300 | OCR용 렌더링 해상도 |
| `pages` | None | 특정 페이지만 처리 |
| `show_progress` | False | 진행 표시 |
| `header` / `footer` | True | 헤더/푸터 포함 여부 |

---


### 파싱 결과 예시 (Attention Is All You Need)

#### 헤딩

![원본 PDF 1페이지](https://i.imgur.com/yGlyfRM.png)

출력 소스:
```markdown
# **Attention Is All You Need**
## **Abstract**
## **1 Introduction**
## **3 Model Architecture**
## **3.1 Encoder and Decoder Stacks**
## **3.2.1 Scaled Dot-Product Attention**
```

`#`(H1)은 제목에만, 나머지는 전부 `##`(H2). 하위 섹션(`3.2.1`)도 H2로 처리되어 **계층 구분이 안 됨**.

#### 테이블 (Table 1)

![원본 Table 1 (6페이지)](https://i.imgur.com/6G5zOeN.png)

출력 소스:
```markdown
|Layer Type|Complexity per Layer|Sequential|Maximum Path Length|
|---|---|---|---|
|||Operations||
|Self-Attention|_O_(_n_2 _· d_)|_O_(1)|_O_(1)|
```

렌더링 결과:

|Layer Type|Complexity per Layer|Sequential Operations|Maximum Path Length|
|---|---|---|---|
|Self-Attention|_O_(_n_2 _· d_)|_O_(1)|_O_(1)|
|Recurrent|_O_(_n · d_2)|_O_(_n_)|_O_(_n_)|
|Convolutional|_O_(_k · n · d_2)|_O_(1)|_O_(_logk_(_n_))|
|Self-Attention (restricted)|_O_(_r · n · d_)|_O_(1)|_O_(_n/r_)|

Markdown pipe 테이블. 수식은 이탤릭(`_O_(_n_2)`)으로 표현되고 **LaTeX 변환은 안 됨**.

#### 수식

![원본 수식 페이지 (4페이지)](https://i.imgur.com/1u67v7H.png)

출력:
```
**==> picture [286 x 26] intentionally omitted <==**
```

수식이 이미지로 인식되어 `picture intentionally omitted`으로 처리됨. **수식 LaTeX 변환을 지원하지 않음**.

#### 이미지

기본 설정에서는 `==> picture [W x H] intentionally omitted <==`으로 건너뜀. `write_images=True` 설정 시 PDF 내장 이미지를 직접 추출.

## 테스트 결과

### 테스트 환경

| 항목 | 스펙 |
|---|---|
| **머신** | Apple Silicon Mac |
| **PyMuPDF4LLM** | v1.27.2.2 |
| **Python** | 3.12 |
| **GPU** | 사용 안 함 (CPU only) |

### 속도 측정

| 문서 | 페이지 | default | with_images | page_chunks | 페이지당 |
|---|---|---|---|---|---|
| 영문 학술 논문 (18p) | 18 | 4.48초 | 4.49초 | 4.78초 | 0.25초 |
| 한국어 보고서 (80p) | 80 | 4.94초 | 5.18초 | 4.49초 | 0.06초 |
| PPT 슬라이드 (70p) | 70 | 3.58초 | 4.29초 | 3.36초 | 0.05초 |
| Attention 논문 (15p) | 15 | 1.81초 | 1.94초 | 1.67초 | 0.12초 |

**4개 문서 × 3설정 = 12회 테스트 총합: ~45초.** [[2026-03-23-MinerU-2x-파이프라인-분석|MinerU]]로 영문 논문 1개 파싱하는 시간(1분 50초)보다 12회 테스트 전체가 더 빠르다.

### 콘텐츠 추출 비교

| 문서 | 헤딩 | 테이블 | 이미지 | 문자수 |
|---|---|---|---|---|
| 영문 학술 논문 | 24 (H2 위주) | 15 | 16 (with_images) | 72,125 |
| 한국어 보고서 | 93 | 41 | 5 (with_images) | 129,788 |
| PPT 슬라이드 | 83 | 0 | 92 (with_images) | 39,798 |
| Attention 논문 | 27 (H2 위주) | 8 | 12 (with_images) | 42,272 |

### 헤딩 처리

PyMuPDF4LLM은 PDF의 **폰트 크기와 볼드 여부**를 기반으로 헤딩을 감지한다. PDF의 TOC(Table of Contents)도 참조한다.

```markdown
## **Abstract**                    ← H2로 처리
## **1 Introduction**              ← H2로 처리
## **2 Background**                ← H2로 처리
## **3 Model Architecture**        ← H2로 처리
## **3.1 Encoder and Decoder**     ← H2로 처리 (H3이어야 함)
```

MinerU가 전부 H1으로 처리하는 것과 달리 **H2를 기본으로 사용**하지만, 하위 섹션(3.1, 2.1.1 등)도 H2로 처리하여 **계층 구분이 안 되는 건 동일한 한계**다.

### 테이블 처리

Markdown pipe 테이블 형식으로 변환한다:

```markdown
|Layer Type|Complexity per Layer|Sequential|Maximum Path Length|
|---|---|---|---|
|||Operations||
|Self-Attention|_O_(_n_2 _· d_)|_O_(1)|_O_(1)|
```

HTML `<table>` 대신 순수 Markdown을 사용하므로 **rowspan/colspan은 지원하지 않는다**. 복잡한 병합 셀은 빈 셀이나 중복 텍스트로 대체된다.

### 수식 처리

**수식 LaTeX 변환을 지원하지 않는다.** 수식은 텍스트 그대로 추출된다:

```
# MinerU 출력 (LaTeX):
$$( \mathcal V _ { j } , \mathcal E _ { j } ) = R ( d _ { j } ^ { \mathrm { c h u n k } } )$$

# PyMuPDF4LLM 출력 (텍스트):
_O_(_n_2 _· d_)
divide each by √dk, and apply a softmax function
```

수식이 많은 학술 논문에서는 이 한계가 크다.

### 이미지 처리

기본 설정에서는 이미지를 건너뛰고 `==> picture [W x H] intentionally omitted <==` 메시지를 남긴다.

`write_images=True`로 설정하면 PDF 내장 이미지 객체를 직접 추출한다. OCR이나 레이아웃 감지로 이미지를 찾는 게 아니라 **PDF 내부 이미지 참조를 그대로 가져오므로** 추출 속도가 빠르고 원본 품질이 보존된다.

PPT 슬라이드에서는 92개의 이미지가 추출되었다 - 슬라이드 내 모든 다이어그램, 아이콘이 개별 이미지 객체로 분리되어 있기 때문.

### 한국어 처리

텍스트 기반 PDF의 경우 한국어 추출이 잘 된다 (OCR 불필요):

```markdown
## < 요 약 문 >
|사업명|사업명|...|KISTEP 일반사업|...|
```

한글 텍스트가 정상 추출되고, 테이블 구조도 보존된다. 단, 스캔 문서에서 한국어 OCR이 필요한 경우 Tesseract `ocr_language="kor"` 설정이 필요하다.

### PPT 슬라이드 처리

PPT 스타일 PDF에서 특이한 기능이 있다 - 이미지 내 텍스트를 `picture text`로 추출한다:

```markdown
**==> picture [849 x 287] intentionally omitted <==**
**----- Start of picture text -----**
Translation
The      protests  escalated    over         the      weekend
...
**----- End of picture text -----**
```

다이어그램 안의 텍스트까지 추출하는 건 독특한 장점이다.

---

## 생태계

### LangChain / LlamaIndex 연동

- **LlamaIndex**: `LlamaMarkdownReader` 내장 (pymupdf4llm에 포함)
- **LangChain**: `PyMuPDFLoader` 공식 지원

```python
# LlamaIndex
from pymupdf4llm import LlamaMarkdownReader
reader = LlamaMarkdownReader()
documents = reader.load_data("input.pdf")

# LangChain
from langchain_community.document_loaders import PyMuPDFLoader
loader = PyMuPDFLoader("input.pdf")
docs = loader.load()
```

### 출력 형식

- `to_markdown()` → Markdown 문자열 또는 페이지별 청크 리스트
- `to_json()` → JSON (레이아웃 정보 포함)
- `to_text()` → 순수 텍스트 (tabulate 포맷 테이블)

---

## 장단점 분석

### 장점

- **압도적 속도**: 0.05~0.25초/페이지, ML 파서 대비 10~100배 빠름
- **GPU 불필요**: CPU만으로 동작, 서버/CI 환경에서 유리
- **모델 다운로드 없음**: 설치 즉시 사용 가능 (~50MB)
- **원본 품질 보존**: PDF 내장 객체 직접 추출 (텍스트, 이미지)
- **한국어 지원**: 텍스트 PDF에서 즉시 한글 추출
- **PPT 이미지 텍스트**: 다이어그램 내 텍스트도 추출
- **LangChain/LlamaIndex 공식 연동**
- **상용 라이선스 구매 가능**: AGPL이 불편하면 상용 라이선스 옵션 존재

### 단점

- **수식 LaTeX 변환 불가**: 수식이 텍스트로만 추출됨
- **헤딩 레벨 부정확**: 모든 헤딩이 H2, 계층 구분 안 됨
- **rowspan/colspan 미지원**: 복잡한 테이블 구조 손실
- **스캔 문서 한계**: OCR 폴백은 있지만 Tesseract 기반이라 정확도가 ML 파서보다 낮음
- **레이아웃 분석 한계**: 규칙 기반이라 비정형 레이아웃에서 읽기 순서 오류 가능
- **AGPL-3.0 라이선스**: 기본은 AGPL (PyMuPDF 의존성)

---

## 추천 사용처

| 사용처 | 적합도 | 이유 |
|---|---|---|
| 대량 PDF 배치 처리 | ★★★★★ | 속도가 핵심인 경우 |
| 텍스트 기반 PDF (보고서, 매뉴얼) | ★★★★★ | 텍스트 직접 추출, OCR 불필요 |
| RAG 파이프라인 전처리 | ★★★★☆ | 빠른 인덱싱에 유리 |
| 학술 논문 (수식 포함) | ★★☆☆☆ | 수식 LaTeX 미지원 |
| 스캔 문서 | ★★☆☆☆ | OCR 품질이 ML 파서 대비 낮음 |
| 복잡한 레이아웃 (잡지, 연차보고서) | ★★★☆☆ | 기본적인 다단 감지는 가능 |

---

## MinerU와의 비교

| 항목 | PyMuPDF4LLM | [[2026-03-23-MinerU-2x-파이프라인-분석|MinerU]] |
|---|---|---|
| 속도 (18p 논문) | **4.5초** | 1분 50초 (MPS) |
| 수식 LaTeX | X | O (UniMERNet) |
| 테이블 형식 | Markdown pipe | HTML (rowspan/colspan) |
| 이미지 추출 | PDF 내장 직접 | 레이아웃 감지 기반 |
| 헤딩 레벨 | 전부 H2 | 전부 H1 |
| OCR | Tesseract 폴백 | PytorchPaddleOCR (109언어) |
| GPU | 불필요 | 선택 (MPS/CUDA) |
| 모델 크기 | 0 | ~2GB |
| 라이선스 | AGPL-3.0 | AGPL-3.0 |

---

## 정리

PyMuPDF4LLM은 품질과 속도의 균형이 잘 잡힌 파서다. 출력 품질이 ML 파서만큼 정밀하진 않지만, 일반 문서 수준에서는 충분하면서 속도는 비교가 안 될 만큼 빠르다. 수식 변환이나 복잡한 테이블 구조가 필요 없는 문서라면 굳이 무거운 ML 파서를 쓸 이유가 없다. 대량 PDF 배치 처리, CI/CD 파이프라인 내 문서 인덱싱, 서버 리소스가 제한된 환경에서 특히 유리하다.

다만 학술 논문의 수식, 복잡한 테이블 병합, 스캔 문서 OCR이 중요하다면 [[2026-03-23-MinerU-2x-파이프라인-분석|MinerU]]나 Docling 같은 ML 기반 파서가 필요하다.

---


> 이 파서의 헤딩/테이블/수식/이미지 처리 결과를 다른 파서와 직접 비교한 글: [[2026-03-26-PDF-파서-5종-비교-분석|PDF 파서 5종 비교 분석]]

## 참고

- [PyMuPDF4LLM GitHub](https://github.com/pymupdf/pymupdf4llm)
- [PyMuPDF 공식 문서](https://pymupdf.readthedocs.io/)
- [Artifex Software](https://artifex.com/)
- [[MinerU - PDF Parser]] - MinerU 1.x 분석
- [[2026-03-23-MinerU-2x-파이프라인-분석]] - MinerU 2.x 파이프라인 분석
