---
title: RAG용 PDF Loader 비교
date: 2024-05-22
tags:
- rag
- langchain
- pymupdf
- pypdflium2
- document-loader
- PDF
- pdf-parser
draft: false
enableToc: true
description: LangChain에서 사용 가능한 다양한 PDF Loader 라이브러리들의 특징과 성능을 비교 분석한 문서
summary: "RAG 시스템의 성능은 PDF 문서에서 얼마나 정확하게 텍스트와 이미지를 추출하는지에 크게 의존한다. PyMuPDF와 PyPDFium2 같은 Loader들은 각각 고유한 장단점을 가지고 있으며, 사용 목적에 따라 적절한 선택이 필요하다."
published: 2024-05-22
modified: 2024-05-22
---
## 개요

RAG 성능 향상 방법엔 여러가지 기법이 있지만, 기본적으로 자료에서 Document를 얼마나 잘 가져오느냐가 중요하다. 특히, Hallucination 확인, 자세한 출처 표기, 그리고 알맞은 image extraction을 위해, 성능이 좋은 PDF Loader는 필수적이다. [[LangChain]]에서 제공하는 다양한 PDF Loader들의 특징과 성능을 비교해보자.

---

## PDF Loader 비교

RAG 시스템 구축 시 PDF 처리는 중요한 부분을 차지한다. 여기서는 주요 PDF Loader들을 비교한다.

### PyMuPDF

[테디노트 PyMuPDF 개발자 라이브 미팅 유투브](https://www.youtube.com/watch?v=VemLpb1UXRs&t=18s)
[PyMuPDF for LLM&RAG](https://pymupdf.readthedocs.io/en/latest/rag.html)

PyMuPDF는 다음과 같은 특징을 가진다:

- **주요 고객사**: OpenAI, Notion, Anthropic
- **라이선스**: 상업목적 사용 시 별도 라이선스 구매 필요
- **핵심 특징**: 
  - C 기반의 MuPDF 기반으로 매우 빠른 처리 속도 제공
  - Pdfminer.six 대비 6배 빠른 속도
  - 정확한 텍스트 및 이미지 추출 지원

![PyMuPDF 성능 비교](https://i.imgur.com/AkluzNm.png)

> [!Note]
> PyMuPDF는 상업적 사용 시 라이선스 비용이 발생하므로 프로젝트의 성격에 따라 라이선스 조건을 확인해야 한다.

### PyPDFium2Loader

PyPDFium2Loader는 [[LangChain]]에서 제공하는 또 다른 PDF Loader로, 다음과 같은 특징이 있다:

- **라이선스**: 오픈소스 기반으로 상업적 사용에 제약이 적음
- **특징**:
  - 비교적 간단한 구현과 사용법
  - 기본적인 텍스트 추출 기능 제공
  - 이미지 추출 기능은 PyMuPDF에 비해 제한적

---

## 실제 사용 시 고려사항

PDF Loader를 선택할 때는 다음 요소들을 고려해야 한다:

1. **처리 속도**: 대량의 PDF 문서를 처리해야 할 경우 PyMuPDF가 유리
2. **텍스트 정확도**: 복잡한 레이아웃의 문서에서는 정확한 텍스트 추출이 중요
3. **이미지 추출**: 문서 내 이미지를 활용해야 하는 경우 이미지 추출 기능 고려
4. **라이선스 비용**: 상업용 프로젝트의 경우 라이선스 비용 계산 필요
5. **통합 용이성**: [[LangChain]] 프레임워크와의 통합 편의성

> [!Note]
> [[문서(pdf 등) 내 시각 자료와 텍스트의 추출 및 활용 연구]] 문서에서 더 자세한 PDF 처리 방법을 확인할 수 있다.

---

## 결론

PDF Loader의 선택은 프로젝트의 요구사항과 예산에 따라 달라질 수 있다. 성능이 가장 중요한 경우 PyMuPDF가 우수하나, 라이선스 비용이 부담될 수 있다. 반면 PyPDFium2Loader는 기본적인 기능을 무료로 제공한다. RAG 시스템 개발 시 문서 특성과 추출 요구사항을 고려하여 적절한 PDF Loader를 선택해야 한다.

PDF 처리와 관련된 추가 정보는 [[LangChain]], [[문서(pdf 등) 내 시각 자료와 텍스트의 추출 및 활용 연구]], [[LayoutLM]] 문서를 참조하자.

## 참고 자료

- [다양한 Python PDF 텍스트 추출 방법 비교](https://medium.com/social-impact-analytics/comparing-4-methods-for-pdf-text-extraction-in-python-fd34531034f)
- [LangChain PyMuPDF 사용 가이드](https://python.langchain.com/v0.1/docs/modules/data_connection/document_loaders/pdf/#using-pymupdf)
- [LangChain PyPDFium2Loader 문서](https://api.python.langchain.com/en/latest/_modules/langchain_community/document_loaders/pdf.html#PyPDFium2Loader)
- [PyPDF 비교 문서](https://pypdf.readthedocs.io/en/latest/meta/comparisons.html)
- [PyMuPDF 라이선스 정보](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright) 
