---
title: MinerU - 고품질 PDF 변환 및 데이터 추출 도구
date: 2025-04-03
tags:
- pdf-converter
- pdf-parser
- data-extraction
- markdown
- ocr
- ai
- PDF
- rag
- document-ai
- layout-analysis
draft: false
enableToc: true
description: MinerU는 PDF 문서를 Markdown과 JSON으로 고품질 변환해주는 오픈소스 데이터 추출 도구이다.
summary: MinerU는 복잡한 PDF 파일을 구조화된 Markdown과 JSON으로 고품질 변환하는 오픈소스 도구다. PDF-Extract-Kit,
  DocLayout-YOLO, StructEqTable, RapidTable 등 최신 문서 처리 기술을 통합하여 정교한 레이아웃 분석과 요소 추출을
  제공한다. PaddleOCR로 텍스트 인식, PyMuPDF로 PDF 처리, layoutreader로 구조 분석, fast-langdetect로
  언어 감지, pdfminer.six로 기본 파싱을 수행한다. 복잡한 레이아웃, 표, 수식, 이미지 등을 정확하게 인식하여 변환하며, CPU/GPU/NPU
  가속을 지원해 효율적인 처리가 가능하다. AGPL-3 라이센스 제약이 있지만 PDF 파싱 성능은 최고 수준이다.
published: 2025-04-03
modified: 2025-04-03
---

> [!summary]
>
> MinerU는 복잡한 PDF 파일을 구조화된 Markdown과 JSON으로 고품질 변환하는 오픈소스 도구다. PDF-Extract-Kit, DocLayout-YOLO, StructEqTable, RapidTable 등 최신 문서 처리 기술을 통합하여 정교한 레이아웃 분석과 요소 추출을 제공한다. PaddleOCR로 텍스트 인식, PyMuPDF로 PDF 처리, layoutreader로 구조 분석, fast-langdetect로 언어 감지, pdfminer.six로 기본 파싱을 수행한다. 복잡한 레이아웃, 표, 수식, 이미지 등을 정확하게 인식하여 변환하며, CPU/GPU/NPU 가속을 지원해 효율적인 처리가 가능하다. AGPL-3 라이센스 제약이 있지만 PDF 파싱 성능은 최고 수준이다.

## MinerU 소개

RAG(Retrieval-Augmented Generation) 시스템 구축을 위해 PDF 파서를 찾던 중 발견한 MinerU는 내가 찾던 대부분의 조건을 충족시키는 도구다. [[RAG용 PDF Loader 비교]] 문서에서 다룬 다른 PDF 로더들과 비교했을 때, 특히 레이아웃 분석과 문서 구조 이해 측면에서 뛰어난 성능을 보여준다. [[LayoutLM]]과 같은 최신 문서 이해 기술을 활용하여 복잡한 문서 구조도 정확하게 처리할 수 있다.

MinerU는 AGPL-3 라이센스를 사용하고 있어 이 점은 주의가 필요하지만, 그 외 모든 요구사항을 매우 뛰어난 품질로 충족시키는 오픈소스 도구다. OpenDataLab에서 개발한 이 도구는 PDF 문서를 Markdown 및 JSON 형식으로 변환하며, 단순한 텍스트 추출을 넘어 문서의 레이아웃, 표, 수식, 이미지 등 복잡한 요소들을 정확하게 인식하고 처리할 수 있다.

MinerU는 아래 라이브러리들은 활용한다:
- [PDF-Extract-Kit](https://github.com/opendatalab/PDF-Extract-Kit)
- [DocLayout-YOLO](https://github.com/opendatalab/DocLayout-YOLO)
- [StructEqTable](https://github.com/UniModal4Reasoning/StructEqTable-Deploy)
- [RapidTable](https://github.com/RapidAI/RapidTable)
- [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR)
- [PyMuPDF](https://github.com/pymupdf/PyMuPDF)
- [layoutreader](https://github.com/ppaanngggg/layoutreader)
- [fast-langdetect](https://github.com/LlmKira/fast-langdetect)
- [pdfminer.six](https://github.com/pdfminer/pdfminer.six)

---

## 주요 기능 및 특징

## Model Overview

|**Task Type**|**Description**|**Models**|
|---|---|---|
|**Layout Detection**|Locate different elements in a document: including images, tables, text, titles, formulas|`DocLayout-YOLO_ft`, `YOLO-v10_ft`, `LayoutLMv3_ft`|
|**Formula Detection**|Locate formulas in documents: including inline and block formulas|`YOLOv8_ft`|
|**Formula Recognition**|Recognize formula images into LaTeX source code|`UniMERNet`|
|**OCR**|Extract text content from images (including location and recognition)|`PaddleOCR`|
|**Table Recognition**|Recognize table images into corresponding source code (LaTeX/HTML/Markdown)|`PaddleOCR+TableMaster`, `StructEqTable`|
|**Reading Order**|Sort and concatenate discrete text paragraphs|Coming Soon!|

### 최신 업데이트 소식

MinerU의 핵심 엔진인 PDF-Extract-Kit은 지속적으로 발전하고 있다:

- **2024.10.22**: StructTable-InternVL2-1B 테이블 인식 모델이 통합되어 LaTeX, HTML, Markdown 형식의 출력을 지원
- **2024.10.17**: 더 정확하고 빠른 레이아웃 감지 모델인 DocLayout-YOLO가 공식 통합
- **2024.10.10**: 모듈화된 구조로 재설계되어 더 편리하고 유연한 모델 사용 가능

### 고품질 레이아웃 분석

MinerU는 DocLayout-YOLO, LayoutLMv3 등의 모델을 사용하여 문서의 레이아웃을 정밀하게 분석한다. 특히 PDF-Extract-Kit을 통해 다음과 같은 고급 기능을 제공한다:

- 논문, 교과서, 연구 보고서, 재무 보고서 등 다양한 유형의 PDF 문서 지원
- 흐림 효과나 워터마크가 있는 문서에서도 높은 견고성 유지
- 실제 현장에서 발생하는 다양한 문서 형식에 대한 안정적인 처리

### 수식 및 테이블 처리

- **수식 감지 및 인식**: 영어와 중국어 문서의 수식을 정확하게 감지하고 인식. UniMERNet 알고리즘을 통해 복잡한 긴 수식, 손글씨 수식, 노이즈가 있는 스크린샷 수식도 처리 가능
- **테이블 인식**: StructEqTable을 통해 테이블 이미지를 LaTeX/HTML/Markdown으로 변환. InternVL2-1B 기반 모델로 중국어 인식 정확도 향상 및 다중 형식 출력 지원

### 다양한 문서 요소 지원

- **테이블**: 복잡한 테이블을 HTML로 변환하여 Markdown에서도 원본과 유사한 형태로 표현
- **수식**: LaTeX 형식으로 수식을 정확하게 변환
- **이미지**: 별도 폴더에 추출하여 Markdown에서 링크로 참조
- **헤딩**: 문서의 구조를 나타내는 제목과 소제목 인식

### 불필요한 요소 자동 제거

PDF 문서에 있는 페이지 번호, 헤더/푸터 등 불필요한 요소들을 자동으로 제거하여 깔끔한 결과물을 생성한다.

### 다양한 하드웨어 가속 지원

- CPU 모드: 기본 모드로 특별한 하드웨어 없이도 동작
- GPU 가속: CUDA 지원 GPU에서 처리 속도 향상
- NPU 가속: Ascend NPU 하드웨어 지원
- MPS 가속: Apple Silicon 칩셋에서의 최적화 지원

---

## 설치 및 사용 방법

### 빠른 설치 (CPU 모드)

```bash
# 가상환경 생성 및 활성화
conda create -n mineru python=3.10
conda activate mineru

# MinerU 설치
pip install -U "magic-pdf[full]" --extra-index-url https://wheels.myhloli.com
```

### 모델 파일 다운로드

MinerU를 사용하기 위해서는 별도의 모델 파일 다운로드가 필요하다. 공식 문서에서 제공하는 방법을 따라 필요한 모델 파일을 다운로드할 수 있다.

### 명령줄 사용 예시

```bash
# PDF를 Markdown으로 변환
magic-pdf convert input.pdf -o output_folder

# 세부 설정 적용하여 변환
magic-pdf convert input.pdf -o output_folder --table.enable true --formula.enable true
```

### 파이썬 API 사용 예시

```python
from magic_pdf import MagicPDF

# MagicPDF 객체 생성
magic_pdf = MagicPDF()

# PDF 파일 로드
doc = magic_pdf.load_pdf("input.pdf")

# Markdown으로 변환
magic_pdf.convert(doc, output_path="output_folder")
```

---

## 실제 사용 후기

MinerU를 실제 PDF 문서 변환에 사용해본 결과, 다음과 같은 장점과 한계점을 확인할 수 있었다:

### 테스트 결과 화면

#### 테스트 해본 원본 PDF 파일:

![테스트 해본 원본 PDF 파일](https://i.imgur.com/8pefD1X.png)

#### 변환 결과:
![변환 결과 예시](https://i.imgur.com/qKrSCPS.png)
![파싱된 Markdown 결과](https://i.imgur.com/WkY3Iqp.png)

### 장점

- **테이블 처리**: HTML로 변환되어 복잡한 표도 원본과 유사하게 표현됨
- **수식 변환**: LaTeX 형식으로 정확하게 변환됨
- **이미지 처리**: 별도 폴더에 저장되고 markdown에 링크로 적절히 표현됨
- **불필요 요소 제거**: 헤더/푸터 등 불필요한 요소를 자동으로 제거함

### 개선 필요 사항

- **헤딩 레벨**: 헤딩을 인식하지만 모든 레벨을 동일하게 처리하는 한계가 있음
- **AGPL-3 라이센스**: 서비스에 포함할 경우 라이센스 조건을 고려해야 함

종합적으로 현재 사용 가능한 PDF 변환 도구 중에서 MinerU는 가장 뛰어난 성능을 보여주고 있으며, 특히 학술 논문이나 기술 문서 처리에 매우 유용하다.

---

## 알려진 한계 및 향후 개발 방향

MinerU는 지속적으로 개발 중이며, 현재 알려진 몇 가지 한계점이 있다:

- 극도로 복잡한 레이아웃에서 읽기 순서가 부정확할 수 있음
- 세로 텍스트 미지원
- 코드 블록 인식 기능 제한적
- 만화책, 예술 앨범, 초등학교 교과서 등의 특수 형태 문서 처리 어려움
- 복잡한 표에서 행/열 인식 오류 가능성
- 일부 언어의 OCR 인식 부정확 가능성

현재 MinerU는 고급 기능 구현을 위해 PyMuPDF를 사용하고 있는데, 이 라이브러리 역시 AGPL 라이센스를 따르고 있어 사용 시나리오에 제약이 있을 수 있다. 개발팀은 이러한 제약을 해소하기 위해 향후 더 유연한 라이센스의 PDF 처리 라이브러리로 대체할 계획을 가지고 있다고 한다.

향후 업데이트에서는 이러한 제한사항들을 개선하고 더 다양한 문서 유형을 지원할 예정이다. 특히 라이센스 문제 해결을 위한 PyMuPDF 대체 작업이 주목할 만한 변화가 될 것으로 보여 지속적인 관심이 필요하다.

---

## 결론

MinerU는 PDF 문서 데이터 추출 분야에서 현재 가장 뛰어난 오픈소스 도구 중 하나다. PDF-Extract-Kit이라는 강력한 엔진을 기반으로, 복잡한 레이아웃, 표, 수식, 이미지 등을 정확하게 처리하는 능력은 RAG 시스템 구축이나 LLM을 위한 데이터 전처리에 매우 유용하게 활용될 수 있다. [[RAG용 PDF Loader 비교]] 문서에서 다룬 다른 PDF 처리 도구들을 적절히 활용하는것으로 보였고, 특히 레이아웃 분석과 문서 구조 이해 측면에서 우수한 성능을 보여준다.

다만 AGPL-3 라이센스를 사용하고 있어 상업 서비스에 통합할 경우 라이센스 조건을 주의깊게 검토해야 한다. 이는 YOLO 코드와 PyMuPDF를 사용하기 때문인데, 이러한 의존성 컴포넌트들의 라이센스 요구사항을 준수하기 위해 전체 저장소가 AGPL-3.0 라이센스를 채택하게 되었다. 개인 연구나 내부 문서 처리 용도로는 이러한 제약 없이 자유롭게 활용할 수 있으며, 그 성능은 현존하는 다른 PDF 변환 도구들보다 우수하다.

향후 더 유연한 라이센스의 PDF 처리 라이브러리 도입과 함께 다양한 문서 형식 처리 기능이 추가된다고 하니, 더욱 강력한 문서 데이터 파이프라인 구축이 가능할 것으로 기대된다.

---

## 관련 도구

OpenDataLab에서는 [MinerU](https://github.com/opendatalab/MinerU) 외에도 다양한 문서 처리 도구를 제공하고 있다:

- [magic-html](https://github.com/opendatalab/magic-html): HTML 문서에서 주요 콘텐츠를 추출하는 도구. 일반 웹페이지, 포럼, 위챗 문서 등 다양한 HTML 형식을 지원하며 Apache-2.0 라이센스를 사용한다.

- [magic-doc](https://github.com/opendatalab/magic-doc): PPT, PPTX, DOC, DOCX 등 Microsoft Office 문서를 Markdown으로 변환하는 도구. 디지털 PDF는 초당 347페이지, OCR이 필요한 PDF는 초당 2.7페이지, DOCX는 초당 1482페이지 등 높은 처리 속도를 보여주며 Apache-2.0 라이센스를 사용한다.

- 앱: [https://mineru.net/client?source=github](https://mineru.net/client?source=github)
![MinerU 변환 예시](https://i.imgur.com/nEztY0h.png)
