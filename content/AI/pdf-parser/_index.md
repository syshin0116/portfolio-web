---
title: PDF 파서 비교 분석 시리즈
date: 2026-03-23
tags:
  - pdf-parser
  - document-ai
  - rag
draft: false
enableToc: true
description: 주요 PDF 파서 9종을 직접 설치하고, READoc 벤치마크(92개 arXiv 논문)로 성능을 측정하여 비교 분석하는 시리즈.
---

주요 PDF 파서들을 직접 설치하고, 두 가지 벤치마크로 성능을 측정하여 비교 분석하는 시리즈다.

- **READoc** — 92개 arXiv 논문 PDF를 파싱하여 GT Markdown과 비교 (전체 텍스트 유사도)
- **OmniDocBench** — 93개 이미지를 파싱하여 텍스트/테이블/수식/읽기순서를 **요소별** 평가

## 메트릭 읽는 법

| 메트릭 | 범위 | 방향 | 의미 | 예시 |
|---|---|---|---|---|
| **Edit Similarity** | 0~100% | 높을수록 좋음 | GT와 얼마나 같은가 | 77.2% = 77.2% 일치 |
| **Edit Distance** | 0~1 | 낮을수록 좋음 | GT와 얼마나 다른가 | 0.073 = 7.3%만 다름 (92.7% 정확) |
| **TEDS** | 0~1 | 높을수록 좋음 | 테이블 HTML 트리 구조 유사도 | 0.633 = 63.3% 구조 일치 |
| **성공률** | 0~100% | 높을수록 좋음 | 에러 없이 파싱 완료한 비율 | 34/100 = 34% |

## READoc 벤치마크 결과 요약

| 파서 | 성공률 | Sim(전체) | Sim(성공분) | Median | 속도(문서당) | 라이선스 |
|---|---|---|---|---|---|---|
| MinerU (MPS) | 92/100 | 71.1% | **77.2%** | 78.9% | 69초 | AGPL-3.0 |
| Marker | 34/100 | 27.4% | **80.6%** | 80.8% | 237초 | GPL-3.0 |
| Docling | 92/100 | 68.3% | **74.3%** | 77.9% | 3.4초 | MIT |
| PyMuPDF4LLM | 92/100 | 67.6% | **73.4%** | 75.8% | 1.9초 | AGPL-3.0 |
| LiteParse | 92/100 | 46.6% | **50.7%** | 45.6% | 0.1초 | Apache 2.0 |

> **측정 방법**: READoc arXiv 논문 100개 샘플 (92개 PDF 다운로드 성공, 8개 arXiv 404). GT Markdown 대비 Normalized Edit Distance. PyMuPDF4LLM/Docling은 3회 반복+워밍업 median, MinerU/Marker는 1회 측정 (문서당 69~237초로 반복 비현실적). 상세 방법론은 [METHODOLOGY.md](https://github.com/syshin0116/pdf-parser-comparison/blob/main/METHODOLOGY.md) 참고.

## OmniDocBench 요소별 파싱 성능 (이미지 기반, 93 샘플)

| 요소 | 메트릭 | MinerU | Marker | Docling | 해석 |
|---|---|---|---|---|---|
| **텍스트** | Edit Dist ↓ | **0.073** | 0.220 | 0.607 | MinerU 92.7% 정확 |
| **수식** | Edit Dist ↓ | 0.421 | **0.258** | - | Marker 74.2% 정확 |
| **테이블** | TEDS ↑ | **0.633** | 0.562 | 0.300 | MinerU 63.3% 구조 일치 |
| **읽기 순서** | Edit Dist ↓ | **0.092** | 0.230 | 0.395 | MinerU 90.8% 정확 |

> PyMuPDF4LLM/LiteParse는 이미지 입력 불가(PDF 텍스트 추출 방식)로 OmniDocBench 대상 아님.

자세한 분석: [[2026-03-26-OmniDocBench-파싱-성능-비교|OmniDocBench 파싱 성능 비교]]

## 글 목록

### Tier 1 — ML 파이프라인 파서
- [[MinerU - PDF Parser|MinerU 1.x 소개]] — 초기 분석
- [[2026-03-23-MinerU-2x-파이프라인-분석|MinerU 2.x 파이프라인 분석]] — YOLOv10 + UniMERNet + SLANET+, CPU vs MPS 성능 비교
- [[2026-03-26-Docling-PDF-파서-분석|Docling]] — IBM MIT 라이선스, Heron RT-DETRv2 + TableFormer, 가성비 최강
- [[2026-03-26-Marker-PDF-파서-분석|Marker]] — Surya OCR 기반, 성공시 최고 품질 but 안정성 문제

### Tier 2 — 경량 파서
- [[2026-03-25-PyMuPDF4LLM-PDF-파서-분석|PyMuPDF4LLM]] — 경량 GNN + 규칙 기반, GPU 없이 최고 속도
- [[2026-03-26-LiteParse-PDF-파서-분석|LiteParse]] — LlamaIndex TypeScript 파서, 0.1초/문서

### 벤치마크 비교
- [[2026-03-26-OmniDocBench-파싱-성능-비교|OmniDocBench 요소별 파싱 성능 비교]] — 텍스트/테이블/수식/읽기순서 분리 평가

### 향후 추가 예정
- OpenDataLoader PDF v2
- DeepSeek-OCR 2
- olmOCR 2
- Dolphin v2
- 통합 비교 분석
