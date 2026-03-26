---
title: Docling - IBM의 MIT 라이선스 문서 파서, 가성비 최강
date: 2026-03-26
tags:
  - pdf-parser
  - document-ai
  - rag
  - docling
  - ibm
  - layout-analysis
  - ocr
draft: false
enableToc: true
description: Docling v2.81.0의 내부 구조를 분석하고 READoc 벤치마크로 성능을 평가한다. IBM Research가 개발한 MIT 라이선스 파서로, Heron 레이아웃 모델과 Granite-Docling VLM을 사용하며, GPU 없이 4.9초/문서에 74.3% Edit Similarity를 달성한다.
summary: Docling은 IBM Research가 개발한 MIT 라이선스 문서 변환 프레임워크다. Heron(RT-DETRv2 기반) 레이아웃 감지, TableFormer 테이블 인식, EasyOCR/Tesseract OCR, 그리고 Granite-Docling-258M VLM을 사용한다. GPU 없이 4.9초/문서에 74.3%의 Edit Similarity를 달성하여 속도 대비 품질(가성비)이 가장 뛰어나다. PDF뿐 아니라 DOCX, PPTX, HTML, 오디오, 비디오까지 지원하는 멀티포맷 파서다.
published: 2026-03-26
modified: 2026-03-26
---

> [!summary]
>
> Docling은 IBM Research가 개발한 MIT 라이선스 문서 변환 프레임워크다. Heron(RT-DETRv2 기반) 레이아웃 감지, TableFormer 테이블 인식, EasyOCR/Tesseract OCR을 사용한다. GPU 없이 4.9초/문서에 74.3%의 Edit Similarity를 달성하여 **속도 대비 품질(가성비)이 가장 뛰어나다**. PDF뿐 아니라 DOCX, PPTX, HTML, 오디오, 비디오까지 지원하는 멀티포맷 파서다.

## 개요

| 항목 | 내용 |
|---|---|
| **개발사** | IBM Research / docling-project |
| **GitHub** | [docling-project/docling](https://github.com/docling-project/docling) |
| **최신 버전** | v2.81.0 (2026-03-20) |
| **라이선스** | **MIT** (상용 자유) |
| **GitHub Stars** | ~37,000+ |
| **Python** | 3.10+ |
| **GPU 필요** | X (CPU만으로 동작, GPU 가속 선택) |
| **모델 크기** | ~500MB (Heron + TableFormer) |

Docling은 GitHub 스타 수 기준으로 가장 인기 있는 PDF 파서다. MIT 라이선스라 상용 프로젝트에 자유롭게 사용할 수 있고, [[MinerU - PDF Parser|MinerU]](AGPL)나 Marker(GPL)와 차별화된다.

---

## 기술 배경

### 아키텍처 변천

```
Docling 1.x → DocLayNet 기반 레이아웃 감지
Docling 2.x → Heron 레이아웃 모델 (RT-DETRv2, 23.5% mAP 향상)
           → Granite-Docling-258M VLM (SmolDocling 후속)
           → DocTags 통합 마크업 포맷
```

### 핵심 모델

| 모델 | 역할 | 아키텍처 | 라이선스 |
|---|---|---|---|
| **Heron** | 레이아웃 감지 | RT-DETRv2 | Apache 2.0 |
| **TableFormer** | 테이블 구조 인식 | Transformer | Apache 2.0 |
| **EasyOCR** | 텍스트 인식 (OCR) | CRAFT + CRNN | Apache 2.0 |
| **Granite-Docling-258M** | VLM 기반 전체 파싱 (옵션) | SigLIP2 + Granite 3 LLM | Apache 2.0 |

### Heron 레이아웃 모델

2025년 12월 도입된 차세대 레이아웃 감지 모델:
- **RT-DETRv2** 아키텍처 (Real-Time DEtection TRansformer)
- 이전 DocLayNet 모델 대비 **23.5% mAP 향상**
- YOLO 계열이 아닌 Transformer 기반 감지

### Granite-Docling-258M

IBM과 Hugging Face가 공동 개발한 초경량 VLM:
- **258M 파라미터** (MinerU의 모델들 합계보다 작음)
- **SigLIP2** 비전 인코더 + **Granite 3** LLM 백본
- **0.35초/페이지** (소비자 GPU 기준)
- **500MB VRAM** 이하
- SmolDocling(2025.03 실험) → Granite-Docling(2025.09 프로덕션)
- **DocTags** 유니버설 마크업 포맷으로 출력

### DocTags 포맷

Docling만의 독자적 중간 표현 포맷. 모든 페이지 요소(텍스트, 테이블, 수식, 이미지)를 위치 정보와 함께 통합적으로 표현한다.

---

## 내부 파이프라인

```
문서 입력 (PDF/DOCX/PPTX/HTML/이미지/오디오/비디오)
  → 포맷 감지 → 적절한 백엔드 선택
  → PDF인 경우:
      ├── 페이지 렌더링
      ├── Heron (RT-DETRv2)로 레이아웃 감지
      │   ├── Title, Section-header, Text, Table, Figure, ...
      │   └── 영역 좌표(bbox) + 클래스 분류
      ├── TableFormer로 테이블 구조 인식 → HTML
      ├── EasyOCR로 텍스트 인식 (필요시)
      └── 수식 감지 및 LaTeX 변환 (제한적)
  → DoclingDocument 생성 (통합 문서 모델)
  → export_to_markdown() / export_to_dict() / export_to_doctags()
```

### 지원 입력 포맷

Docling의 가장 큰 차별점 중 하나 — PDF만이 아니라 다양한 포맷을 지원한다:

- **문서**: PDF, DOCX, PPTX, XLSX
- **웹**: HTML, XHTML
- **이미지**: PNG, JPG, TIFF, BMP
- **오디오**: WAV, MP3 (v2.x 추가)
- **비디오**: MP4, AVI, MOV (v2.x 추가)

### 지원 출력 포맷

- Markdown
- JSON (DoclingDocument dict)
- DocTags
- HTML
- 텍스트

---

## 설치 및 사용법

```bash
uv venv docling-env --python 3.12
source docling-env/bin/activate
uv pip install docling
```

### Python API

```python
from docling.document_converter import DocumentConverter

# 기본 사용
converter = DocumentConverter()
result = converter.convert("input.pdf")

# Markdown 출력
md = result.document.export_to_markdown()

# JSON 출력
doc_dict = result.document.export_to_dict()

# 여러 문서 배치 처리
results = converter.convert_all(["doc1.pdf", "doc2.pdf", "doc3.docx"])
```

### CLI 사용

```bash
docling input.pdf --output output/
docling input.pdf --format markdown
```

---

## READoc 벤치마크 결과

### 테스트 환경

| 항목 | 스펙 |
|---|---|
| **Docling** | v2.81.0 |
| **Python** | 3.12 |
| **GPU** | 사용 안 함 (CPU) |
| **테스트 문서** | READoc arXiv 논문 92개 |

### 결과

| 메트릭 | 값 |
|---|---|
| **Edit Similarity (전체)** | **68.3%** |
| **Edit Similarity (성공분)** | **74.3%** |
| **Median** | 77.9% |
| **처리 시간 (median)** | 3.37초/문서 |
| **성공률** | 92/100 |
| **측정** | 3회 반복 + 워밍업, median 사용 |

### 파서 비교 (READoc 벤치마크)

| 파서 | 성공률 | Sim(전체) | Sim(성공분) | 속도 | 라이선스 |
|---|---|---|---|---|---|
| MinerU (MPS) | 92/100 | 71.1% | 77.2% | 69초 | AGPL-3.0 |
| **Docling** | **92/100** | **68.3%** | **74.3%** | **3.4초** | **MIT** |
| PyMuPDF4LLM | 92/100 | 67.6% | 73.4% | 1.9초 | AGPL-3.0 |
| LiteParse | 92/100 | 46.6% | 50.7% | 0.1초 | Apache 2.0 |

**Docling이 가성비 최강인 이유:**
- MinerU보다 3%p 낮지만 **14배 빠름**
- PyMuPDF4LLM보다 1%p 높고 속도는 2.5배 느리지만 **MIT 라이선스**
- 테이블, 수식, 이미지 등 **구조 인식 품질이 상위권**

### 출력 품질 예시

Docling의 Markdown 출력은 `##` 헤딩을 사용하고 문단 구분이 정확하다:

```markdown
## Math That Matters:

Enhancing Academic Mathematics' Impact on Society
Plenary address to 2019 ICAPTA Conference, Abuja Nigeria

## 1 Introduction

## 1.1 A Richer Picture of Academic Mathematics
```

다만 수식 LaTeX 변환은 제한적이고 (`\(k\)` → `k`), 헤딩 레벨이 전부 `##`(H2)로 처리되는 한계가 있다.

---

## 생태계

### LangChain / LlamaIndex 연동

```python
# LangChain
from langchain_docling import DoclingLoader
loader = DoclingLoader(file_path="input.pdf")
docs = loader.load()

# LlamaIndex
from llama_index.readers.docling import DoclingReader
reader = DoclingReader()
docs = reader.load_data(file_path="input.pdf")
```

### RAG-Anything 연동

[[2026-03-22-RAG-Anything-파헤치기|RAG-Anything]]에는 `DoclingParser`가 대안 파서로 내장되어 있다 (`parser.py:1355`).

---

## 장단점 분석

### 장점

- **MIT 라이선스**: 상용 프로젝트에 자유롭게 사용 가능 (AGPL/GPL 파서들과 차별화)
- **가성비 최고**: 74.3% 품질에 4.9초/문서, GPU 불필요
- **멀티포맷**: PDF, DOCX, PPTX, HTML, 오디오, 비디오까지
- **안정성 100%**: 92개 문서 전부 성공
- **IBM Research 지원**: 대규모 팀, 지속적 업데이트 (2주 간격 릴리스)
- **LangChain/LlamaIndex 공식 연동**
- **GitHub 최다 스타** (~56K)

### 단점

- **수식 LaTeX 변환 제한**: MinerU의 UniMERNet보다 약함
- **헤딩 레벨 부정확**: 전부 H2로 처리 (MinerU와 동일한 한계)
- **OCR 품질**: EasyOCR 기반이라 PaddleOCR보다 약할 수 있음
- **첫 실행 느림**: 모델 다운로드 및 초기화 시간 필요
- **한국어 OCR**: EasyOCR 한국어 지원은 있지만 정확도는 미확인

---

## 추천 사용처

| 사용처 | 적합도 | 이유 |
|---|---|---|
| 상용 RAG 프로젝트 | ★★★★★ | MIT 라이선스, 안정성, 가성비 |
| 멀티포맷 문서 처리 | ★★★★★ | PDF+DOCX+PPTX+HTML 통합 |
| 엔터프라이즈 문서 파이프라인 | ★★★★★ | IBM 지원, 배치 처리 |
| 학술 논문 (수식 중심) | ★★★☆☆ | 수식 LaTeX 변환 제한 |
| 스캔 문서 OCR | ★★★☆☆ | EasyOCR 기반, ML 파서보다 약함 |

---

## 정리

Docling은 **"상용 프로젝트에서 쓸 수 있는 최고의 오픈소스 PDF 파서"**다. MIT 라이선스, 74.3% 품질, 4.9초/문서, 100% 안정성, 멀티포맷 지원 — 이 조합을 제공하는 파서는 Docling뿐이다.

MinerU(AGPL)가 3%p 더 높은 품질을 제공하지만 14배 느리고 상용 제약이 있다. PyMuPDF4LLM(AGPL)은 2.5배 빠르지만 역시 AGPL이다. **라이선스가 중요한 프로젝트라면 Docling이 현재 최선의 선택이다.**

---


> 이 파서의 헤딩/테이블/수식/이미지 처리 결과를 다른 파서와 직접 비교한 글: [[2026-03-26-PDF-파서-5종-비교-분석|PDF 파서 5종 비교 분석]]

## 참고

- [Docling GitHub](https://github.com/docling-project/docling)
- [Docling 공식 문서](https://docling.io/)
- [Granite-Docling-258M (HuggingFace)](https://huggingface.co/ibm-granite/granite-docling-258M)
- [Heron Layout Model](https://huggingface.co/docling-project/heron)
- [[2026-03-23-MinerU-2x-파이프라인-분석]] — MinerU 2.x 분석
- [[2026-03-25-PyMuPDF4LLM-PDF-파서-분석]] — PyMuPDF4LLM 분석
- [[2026-03-26-LiteParse-PDF-파서-분석]] — LiteParse 분석
