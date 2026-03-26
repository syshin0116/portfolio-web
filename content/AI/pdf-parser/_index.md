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

주요 PDF 파서들을 직접 설치하고, READoc 벤치마크(92개 arXiv 논문, GT Markdown 대비 Edit Similarity)로 성능을 측정하여 비교 분석하는 시리즈다.

## READoc 벤치마크 결과 요약

| 파서 | Edit Similarity | 속도 (문서당) | 성공률 | 라이선스 |
|---|---|---|---|---|
| MinerU (MPS) | 77.2% | 69초 | 100% | AGPL-3.0 |
| Marker (성공분) | 80.6% | 237초 | 37% | GPL-3.0 |
| Docling | 74.3% | 4.9초 | 100% | MIT |
| PyMuPDF4LLM | 73.4% | 1.9초 | 100% | AGPL-3.0 |
| LiteParse | 50.7% | 0.1초 | 100% | Apache 2.0 |

## 글 목록

### Tier 1 — ML 파이프라인 파서
- [[MinerU - PDF Parser|MinerU 1.x 소개]] — 초기 분석
- [[2026-03-23-MinerU-2x-파이프라인-분석|MinerU 2.x 파이프라인 분석]] — YOLOv10 + UniMERNet + SLANET+, CPU vs MPS 성능 비교
- [[2026-03-26-Docling-PDF-파서-분석|Docling]] — IBM MIT 라이선스, Heron RT-DETRv2 + TableFormer, 가성비 최강
- [[2026-03-26-Marker-PDF-파서-분석|Marker]] — Surya OCR 기반, 성공시 최고 품질 but 안정성 문제

### Tier 2 — 경량 파서
- [[2026-03-25-PyMuPDF4LLM-PDF-파서-분석|PyMuPDF4LLM]] — 경량 GNN + 규칙 기반, GPU 없이 최고 속도
- [[2026-03-26-LiteParse-PDF-파서-분석|LiteParse]] — LlamaIndex TypeScript 파서, 0.1초/문서

### 향후 추가 예정
- OpenDataLoader PDF v2
- DeepSeek-OCR 2
- olmOCR 2
- Dolphin v2
- 통합 비교 분석
