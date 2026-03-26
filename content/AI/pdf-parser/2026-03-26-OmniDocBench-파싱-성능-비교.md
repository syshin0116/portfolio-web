---
title: OmniDocBench로 측정한 PDF 파서별 파싱 성능 - 텍스트, 테이블, 수식, 읽기 순서
date: 2026-03-26
tags:
  - pdf-parser
  - benchmark
  - omnidocbench
  - document-ai
  - rag
  - mineru
  - docling
  - marker
draft: false
enableToc: true
description: OmniDocBench(CVPR 2025)로 MinerU, Docling, Marker 3개 파서의 요소별 파싱 성능을 측정한다. 텍스트 정확도, 테이블 TEDS, 수식 인식, 읽기 순서를 분리하여 평가하며, MinerU가 텍스트/테이블/읽기순서에서 압도적 1위, Marker는 수식에서 강점을 보인다.
summary: OmniDocBench(CVPR 2025, 1355페이지, 9종 문서)에서 93개 샘플로 MinerU, Docling, Marker의 요소별 파싱 성능을 측정했다. MinerU가 텍스트(Edit Dist 0.073), 테이블(TEDS 0.633), 읽기 순서(Edit Dist 0.092)에서 압도적 1위를 기록했고, Marker는 수식 인식(Edit Dist 0.258)에서 MinerU(0.421)를 앞섰다. Docling은 이미지 기반 파싱에서 OCR 한계로 전반적으로 낮은 점수를 보였다.
published: 2026-03-26
modified: 2026-03-26
---

> [!summary]
>
> OmniDocBench(CVPR 2025)에서 93개 샘플로 MinerU, Docling, Marker의 요소별 파싱 성능을 측정했다. MinerU가 텍스트, 테이블, 읽기 순서에서 1위, Marker는 수식에서 강점. Docling은 이미지 기반 파싱에서 OCR 한계.

## 왜 OmniDocBench인가

[[2026-03-23-MinerU-2x-파이프라인-분석|이전 글들]]에서 READoc 벤치마크(Edit Similarity)로 파서를 비교했지만, 이 메트릭은 **전체 텍스트 유사도만 측정**한다. 테이블 구조가 정확한지, 수식이 LaTeX로 변환되었는지, 읽기 순서가 맞는지는 알 수 없다.

OmniDocBench(CVPR 2025)는 이 한계를 해결한다:
- **텍스트**: Normalized Edit Distance
- **테이블**: TEDS (Tree Edit Distance-based Similarity) — HTML 트리 구조 비교
- **수식**: Edit Distance (LaTeX 비교)
- **읽기 순서**: 요소 순서 Edit Distance

### 벤치마크 데이터

| 항목 | 내용 |
|---|---|
| **데이터셋** | [OmniDocBench v1.5](https://huggingface.co/datasets/opendatalab/OmniDocBench) |
| **전체** | 1,355 페이지, 9종 문서, 영어+중국어 |
| **샘플** | 93개 (문서 유형별 균등 샘플링, seed=42) |
| **입력** | JPG 페이지 이미지 (PDF 아님) |
| **GT** | JSON (텍스트, 테이블 HTML, 수식 LaTeX, 읽기 순서) |
| **평가 도구** | [OmniDocBench 공식 evaluator](https://github.com/opendatalab/OmniDocBench) |

### 이미지 기반 = OCR 필수

OmniDocBench는 **PDF가 아닌 이미지**를 입력으로 사용한다. 따라서:
- PyMuPDF4LLM, LiteParse → 이미지 파싱 불가 (PDF 텍스트 추출 방식)
- **MinerU, Docling, Marker** → 이미지 OCR 가능 (이 3개만 테스트)

---

## 테스트 환경

| 항목 | 스펙 |
|---|---|
| **머신** | Apple Silicon Mac |
| **MinerU** | v2.7.6, pipeline 백엔드, MPS — 70/93 성공 (파일명 충돌로 23개 누락) |
| **Docling** | v2.81.0, CPU — 91/93 성공 |
| **Marker** | v1.10.1, CPU — 90/93 성공 (단일 이미지라 토큰 제한 문제 거의 없음) |
| **평가** | OmniDocBench 공식 evaluator (quick_match) |

---

## 메트릭 설명

결과를 보기 전에 각 메트릭의 의미를 이해해야 한다.

### Normalized Edit Distance (텍스트, 수식, 읽기 순서)

```
Edit Distance = Levenshtein Distance(예측, 정답) / max(len(예측), len(정답))
```

- **범위**: 0.0 ~ 1.0
- **0.0 = 완벽** (예측과 정답이 동일)
- **1.0 = 최악** (완전히 다름)
- **0.073** = 텍스트의 7.3%만 틀림 → 매우 좋음
- **0.607** = 텍스트의 60.7%가 틀림 → 매우 나쁨

직관적으로 `1 - Edit Distance`를 정확도로 생각할 수 있다: 0.073이면 **92.7% 정확**.

### TEDS (Tree Edit Distance-based Similarity) — 테이블

테이블의 HTML 트리 구조를 비교한다. 단순 텍스트 비교가 아니라 `<tr>`, `<td>`, `rowspan`, `colspan` 등의 **트리 구조적 유사도**를 측정한다.

- **범위**: 0.0 ~ 1.0
- **1.0 = 완벽** (테이블 구조+내용 완전 일치)
- **0.0 = 최악**
- **0.633** = 테이블의 63.3%를 정확히 재현 → 괜찮음
- **0.300** = 30%만 맞음 → 나쁨

### TEDS-S (Structure Only)

TEDS와 같지만 셀 **내용은 무시**하고 **구조만** 비교한다. `rowspan`, `colspan`, 행/열 수가 맞는지만 본다. TEDS보다 항상 같거나 높다.

### OmniDocBench 리더보드 기준

공식 리더보드의 상위 파서들 점수 (참고용):

| 파서 | Overall | 비고 |
|---|---|---|
| PaddleOCR-VL | 92.86 | 상용, 리더보드 1위 |
| MinerU 2.5 | 90.67 | 전체 1,355페이지 기준 |
| Qwen3-VL-235B | 89.15 | 235B VLM |

우리 테스트는 **93개 샘플**이므로 공식 리더보드와 직접 비교는 불가능하지만, 상대적 순위를 파악하기에 충분하다.

---

## 결과

### 요소별 비교

| 요소 | 메트릭 | MinerU | Marker | Docling | 최고 | 해석 |
|---|---|---|---|---|---|---|
| **텍스트** | Edit Dist ↓ | **0.073** | 0.220 | 0.607 | MinerU | MinerU 92.7% 정확, Docling 39.3% |
| **수식** | Edit Dist ↓ | 0.421 | **0.258** | - | Marker | Marker 74.2% 정확, MinerU 57.9% |
| **테이블** | TEDS ↑ | **0.633** | 0.562 | 0.300 | MinerU | MinerU 63.3% 구조+내용 일치 |
| **테이블 구조** | TEDS-S ↑ | **0.670** | 0.651 | 0.469 | MinerU | 내용 무시시 MinerU와 Marker 비슷 |
| **읽기 순서** | Edit Dist ↓ | **0.092** | 0.230 | 0.395 | MinerU | MinerU 90.8% 정확 |

> ↓ = 낮을수록 좋음 (0이 완벽), ↑ = 높을수록 좋음 (1이 완벽)

### Overall Score 계산

OmniDocBench 공식 리더보드 공식: `((1 - Text_ED) × 100 + Table_TEDS × 100 + Formula_CDM) / 3`

CDM 환경이 없어 `(1 - Formula_ED) × 100`으로 근사:

| 파서 | 텍스트 점수 | 테이블 점수 | 수식 점수 | **Overall** | 해석 |
|---|---|---|---|---|---|
| **MinerU** | 92.7 | 63.3 | 57.9 | **71.3** | 텍스트/테이블 강함, 수식 보통 |
| **Marker** | 78.0 | 56.2 | 74.2 | **69.5** | 수식 강함, 나머지 보통 |
| **Docling** | 39.3 | 30.0 | 0 | **23.1** | 이미지 OCR에서 전반적 약함 |

참고: 공식 리더보드에서 MinerU 2.5는 전체 데이터 기준 90.67점이다. 우리 테스트에서 71.3점인 이유는 (1) 93개 샘플만 사용, (2) CDM 대신 근사 사용, (3) MinerU 2.7.6과 2.5 모델 차이 때문이다.

---

## 분석

### MinerU가 강한 이유

MinerU의 Pipeline 백엔드는 각 요소에 **전용 모델**을 사용한다:
- 텍스트: PytorchPaddleOCR (109개 언어, PyTorch 재구현)
- 테이블: PP-LCNet 분류 → SLANET+ / UNet 구조 인식
- 수식: YOLOv8 MFD 감지 → UniMERNet 인식
- 레이아웃: DocLayout-YOLO (YOLOv10)

이 다단계 파이프라인이 이미지 기반 파싱에서 강력한 성능을 보인다.

### Marker의 수식 강점

Marker(Surya OCR)는 수식 인식에서 MinerU를 앞섰다 (0.258 vs 0.421). Surya의 Recognition 모델이 수식 텍스트를 LaTeX로 변환하는 능력이 UniMERNet보다 좋을 수 있다.

### Docling의 한계

Docling은 이미지 기반 파싱에서 전반적으로 낮은 점수를 보였다. EasyOCR의 OCR 정확도가 PaddleOCR(MinerU)이나 Surya(Marker)보다 약한 것이 원인으로 보인다. **Docling의 강점은 PDF 텍스트 추출**(READoc 74.3%)이지 이미지 OCR이 아니다.

---

## READoc vs OmniDocBench 비교

두 벤치마크에서 파서 순위가 다르다:

| 파서 | READoc (PDF 텍스트) | OmniDocBench (이미지 OCR) |
|---|---|---|
| **MinerU** | 77.2% (1위) | **71.3** (1위) |
| **Marker** | 80.6%* (성공분 최고) | **69.5** (2위) |
| **Docling** | 74.3% (3위) | **23.1** (3위) |

*Marker READoc 성공률 34%

**핵심 발견**:
- MinerU는 PDF 텍스트와 이미지 OCR 모두 안정적으로 1위
- Marker는 PDF에서 성공하면 최고지만 실패율이 높고, 이미지에서도 강하지만 2위
- Docling은 PDF 텍스트에서 강하지만 이미지 OCR에서는 취약

### 용도별 추천

| 상황 | 추천 파서 | 이유 |
|---|---|---|
| **스캔 문서 / 이미지 PDF** | MinerU | OCR 성능 압도적 |
| **텍스트 기반 PDF, 상용 프로젝트** | Docling (MIT) | 라이선스 자유, PDF 텍스트에서 강함 |
| **수식 많은 학술 논문** | Marker (짧은 문서) | 수식 인식 최고, 단 안정성 주의 |
| **대량 배치 처리** | Docling 또는 PyMuPDF4LLM | 속도 + 안정성 |

---

## 정리

OmniDocBench로 **요소별 파싱 성능**을 분리 측정한 결과, MinerU의 다단계 전용 모델 파이프라인이 이미지 기반 파싱에서 가장 강력함을 확인했다. 특히 텍스트(0.073), 읽기 순서(0.092)에서 2위 대비 3배 이상의 격차를 보였다.

다만 이 결과는 **이미지 입력** 기준이다. PDF 텍스트 추출에서는 Docling, PyMuPDF4LLM도 충분히 좋은 성능을 보이므로, 사용 사례에 따라 적절한 파서를 선택해야 한다.

---

## 참고

- [OmniDocBench GitHub](https://github.com/opendatalab/OmniDocBench)
- [OmniDocBench Paper (CVPR 2025)](https://arxiv.org/abs/2412.07626)
- [[2026-03-23-MinerU-2x-파이프라인-분석|MinerU 파이프라인 분석]]
- [[2026-03-26-Docling-PDF-파서-분석|Docling 분석]]
- [[2026-03-26-Marker-PDF-파서-분석|Marker 분석]]
