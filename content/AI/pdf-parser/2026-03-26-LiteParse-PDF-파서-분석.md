---
title: LiteParse - LlamaIndex가 오픈소스로 공개한 초경량 PDF 파서
date: 2026-03-26
tags:
  - pdf-parser
  - document-ai
  - rag
  - llamaindex
  - typescript
  - ocr
draft: false
enableToc: true
description: LiteParse는 LlamaIndex가 LlamaParse의 오픈소스 코어로 공개한 TypeScript 기반 PDF 파서다. PDF.js + Tesseract.js로 구현되어 ML 모델 없이 0.1초/문서의 극한 속도를 달성하지만, Markdown 구조화 없이 순수 텍스트만 추출하는 한계가 있다. READoc 벤치마크 결과 50.7%로 구조화 파서 대비 낮은 품질.
summary: LiteParse는 LlamaIndex가 2026년 3월 공개한 TypeScript PDF 파서로, LlamaParse의 경량 오픈소스 코어다. PDF.js로 텍스트를 추출하고 Tesseract.js로 OCR을 수행한다. ML 모델 없이 순수 좌표 기반 공간 배치(spatial grid)로 텍스트를 재구성하며, 0.1초/문서의 극한 속도를 보여준다. 다만 헤딩/테이블/수식 등의 Markdown 구조화를 하지 않아 READoc 벤치마크에서 50.7%의 Edit Similarity를 기록했다.
published: 2026-03-26
modified: 2026-03-26
---

> [!summary]
>
> LiteParse는 LlamaIndex가 2026년 3월 공개한 TypeScript PDF 파서로, LlamaParse의 경량 오픈소스 코어다. PDF.js로 텍스트를 추출하고 Tesseract.js로 OCR을 수행한다. ML 모델 없이 순수 좌표 기반 공간 배치(spatial grid)로 텍스트를 재구성하며, 0.1초/문서의 극한 속도를 보여준다. 다만 헤딩/테이블/수식 등의 Markdown 구조화를 하지 않아 READoc 벤치마크에서 50.7%의 Edit Similarity를 기록했다.

## 개요

| 항목 | 내용 |
|---|---|
| **개발사** | LlamaIndex (Run-Llama) |
| **GitHub** | [run-llama/liteparse](https://github.com/run-llama/liteparse) |
| **npm** | [@llamaindex/liteparse](https://www.npmjs.com/package/@llamaindex/liteparse) |
| **최신 버전** | v1.3.0 (2026-03-25) |
| **라이선스** | Apache 2.0 (Python wrapper는 MIT) |
| **런타임** | Node.js (TypeScript) — Python 아님 |
| **GPU 필요** | X |
| **ML 모델** | 없음 (PDF.js + Tesseract.js) |

LiteParse는 LlamaIndex의 상용 파서 **LlamaParse**의 핵심 파싱 로직을 오픈소스로 공개한 것이다. 2026년 3월에 출시되어 가장 최신 파서 중 하나다.

핵심 컨셉은 **"PDF를 이미지로 렌더링하지 않고, 텍스트 좌표를 공간 그리드에 투영하여 레이아웃을 재구성"**하는 것이다. ML 모델 없이 순수 좌표 기반이라 극한의 속도를 달성한다.

### LlamaParse vs LiteParse

| | LlamaParse | LiteParse |
|---|---|---|
| 유형 | 클라우드 API (유료) | 로컬 오픈소스 (무료) |
| 정확도 | 높음 (서버 ML 모델) | 기본 (좌표 기반) |
| 속도 | 네트워크 의존 | 극한의 로컬 속도 |
| 라이선스 | 프로프라이어터리 | MIT |
| 오프라인 | X | O |

---

## 내부 파이프라인

```
PDF 입력 (파일/Buffer/Uint8Array)
  → PDF.js로 텍스트 + 좌표 추출
  → (비PDF 입력시) 포맷 변환 → PDF 변환 후 파싱
  → 페이지별 처리:
      ├── 텍스트 아이템 좌표(x, y, width, height) 추출
      ├── 공간 그리드(Spatial Grid)에 텍스트 투영
      ├── 읽기 순서 결정 (좌→우, 위→아래)
      └── (OCR 활성시) Tesseract.js로 이미지 기반 텍스트 인식
  → 텍스트 결합 → 출력
```

### 핵심 특징: Spatial Text Extraction

일반적인 PDF 파서들이 **"PDF → 이미지 렌더링 → ML로 구조 감지"** 하는 것과 달리, LiteParse는 **"PDF 내부 텍스트 좌표를 직접 읽어 공간적으로 배치"**한다.

```
기존 ML 파서:  PDF → 이미지 → YOLO/Transformer → 구조 감지 → 텍스트 추출
LiteParse:     PDF → PDF.js → 텍스트 좌표 → 공간 그리드 투영 → 텍스트 출력
```

이 접근의 장점은 속도고, 단점은 **구조적 의미를 이해하지 못한다**는 것이다. 폰트 크기가 큰 텍스트가 제목인지, 테이블의 셀 경계가 어디인지 판별하지 않는다.

---

## 설치 및 사용법

```bash
# Node.js 환경 (Python이 아님!)
npm install @llamaindex/liteparse

# CLI 사용
npx liteparse document.pdf
```

### JavaScript/TypeScript API

```typescript
import { LiteParse } from "@llamaindex/liteparse";

// 기본 사용
const parser = new LiteParse();
const result = await parser.parse("document.pdf");
console.log(result.text);

// Buffer 입력
const buffer = fs.readFileSync("document.pdf");
const result = await parser.parse(buffer);

// JSON 출력 (바운딩 박스 포함)
const parser = new LiteParse({ outputFormat: "json", dpi: 300 });
const result = await parser.parse("document.pdf");
for (const page of result.json.pages) {
  console.log(`Page ${page.page}: ${page.boundingBoxes.length} boxes`);
}

// OCR 활성화
const parser = new LiteParse({
  ocrEnabled: true,
  ocrLanguage: "eng",
});

// HTTP OCR 서버 사용
const parser = new LiteParse({
  ocrServerUrl: "http://localhost:8828/ocr",
});
```

### 주요 설정

| 파라미터 | 기본값 | 설명 |
|---|---|---|
| `outputFormat` | `"text"` | 출력 형식 (text, json) |
| `ocrEnabled` | `true` | OCR 활성화 |
| `ocrLanguage` | `"eng"` | OCR 언어 |
| `ocrServerUrl` | - | 외부 OCR 서버 URL |
| `dpi` | 150 | 렌더링 해상도 |

---

## READoc 벤치마크 결과

### 테스트 환경

| 항목 | 스펙 |
|---|---|
| **LiteParse** | v1.3.0 |
| **Node.js** | v24.14.0 |
| **테스트 문서** | READoc arXiv 논문 92개 |
| **평가 메트릭** | Edit Similarity (GT Markdown 대비) |

### 결과

| 메트릭 | 값 |
|---|---|
| **Edit Similarity** | **50.7%** |
| **처리 시간** | 9.4초 (92문서) |
| **문서당 평균** | 0.10초 |
| **성공률** | 100% (92/92) |

### 다른 파서와 비교

| 파서 | Edit Similarity | 속도 (문서당) | 배수 |
|---|---|---|---|
| MinerU (MPS) | 77.2% | 69초 | 1x (기준) |
| Docling | 74.3% | 4.9초 | 14x |
| PyMuPDF4LLM | 73.4% | 1.9초 | 36x |
| **LiteParse** | **50.7%** | **0.1초** | **690x** |

LiteParse는 MinerU보다 **690배 빠르지만** 품질은 26.5%p 낮다.

### 왜 50.7%인가?

LiteParse의 출력은 **순수 텍스트**다. Markdown 구조화(헤딩, 테이블, 수식 LaTeX)를 하지 않으므로 GT Markdown과의 Edit Distance가 크다.

**LiteParse 출력:**
```
Math That Matters:
Enhancing Academic Mathematics' Impact on Society
Plenary address to 2019 ICAPTA Conference, Abuja Nigeria
Christopher Thron
```

**GT Markdown:**
```markdown
# Math That Matters: Enhancing Academic Mathematics' Impact on Society
_Plenary address to 2019 ICAPTA Conference, Abuja Nigeria_

Christopher Thron
```

텍스트 내용 자체는 정확하게 추출되지만, `#`, `_`, `**`, `$$` 같은 Markdown 구문이 없어서 Edit Distance가 벌어진다.

---

## 장단점 분석

### 장점

- **극한의 속도**: 0.1초/문서, 모든 파서 중 최고속
- **MIT 라이선스**: 상용 프로젝트에 자유롭게 사용 가능
- **GPU/ML 모델 불필요**: Node.js만 있으면 동작
- **Zero Python 의존성**: TypeScript/Node.js 네이티브
- **바운딩 박스 제공**: JSON 출력 시 모든 텍스트의 좌표 정보 포함
- **OCR 지원**: Tesseract.js 내장, 외부 OCR 서버 연동 가능
- **Buffer 입력 지원**: 디스크 I/O 없이 메모리에서 직접 파싱
- **2026년 3월 출시**: 가장 최신, 활발한 개발

### 단점

- **Markdown 구조화 없음**: 헤딩, 테이블, 수식 등을 구분하지 못함
- **순수 텍스트 출력**: `#`, `**`, `$$`, `<table>` 등 구문 없음
- **Node.js 전용**: Python 생태계와 분리됨
- **OCR 품질**: Tesseract.js는 ML 기반 OCR 대비 정확도가 낮음
- **레이아웃 이해 한계**: 다단 칼럼, 사이드바 등 복잡한 레이아웃에서 읽기 순서 오류 가능

---

## 추천 사용처

| 사용처 | 적합도 | 이유 |
|---|---|---|
| 대량 텍스트 추출 (전처리) | ★★★★★ | 속도가 핵심인 경우 |
| 검색 인덱싱 (전문 검색) | ★★★★☆ | 텍스트 내용만 필요 |
| TypeScript/Node.js 프로젝트 | ★★★★★ | Python 의존성 없음 |
| RAG 전처리 (빠른 인덱싱) | ★★★☆☆ | 구조 정보 손실 |
| 학술 논문 파싱 | ★★☆☆☆ | 수식/테이블 구조화 불가 |
| 구조화된 문서 분석 | ★☆☆☆☆ | Markdown 구조 없음 |

---

## 정리

LiteParse는 **"텍스트 내용만 빠르게 뽑으면 되는"** 사용 사례에 최적화된 파서다. Markdown 구조화가 필요하면 [[2026-03-25-PyMuPDF4LLM-PDF-파서-분석|PyMuPDF4LLM]]이나 [[2026-03-23-MinerU-2x-파이프라인-분석|MinerU]]를 사용해야 한다.

하지만 LlamaParse의 오픈소스 코어라는 점, MIT 라이선스, Node.js 네이티브라는 점에서 프론트엔드/풀스택 프로젝트에서는 유용할 수 있다. 특히 LlamaIndex 생태계와의 연동을 고려하면 LiteParse(로컬 빠른 전처리) + LlamaParse(정밀 파싱)의 조합도 가능하다.

---

## 참고

- [LiteParse GitHub](https://github.com/run-llama/liteparse)
- [LiteParse npm](https://www.npmjs.com/package/@llamaindex/liteparse)
- [LlamaIndex 블로그 — LiteParse 소개](https://www.llamaindex.ai/blog/liteparse-local-document-parsing-for-ai-agents)
- [[2026-03-25-PyMuPDF4LLM-PDF-파서-분석]] — PyMuPDF4LLM 분석
- [[2026-03-23-MinerU-2x-파이프라인-분석]] — MinerU 2.x 분석
