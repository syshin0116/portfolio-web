---
title: RAG-Anything 파헤치기 - 멀티모달 GraphRAG의 구조와 원리
date: 2026-03-22
tags:
  - rag
  - knowledge-graph
  - graphrag
  - lightrag
  - mineru
  - multimodal
  - pdf-parser
  - document-ai
  - llm
  - embedding
draft: false
enableToc: true
description: RAG-Anything의 내부 구조를 파헤쳐본다. MinerU 파서, LightRAG 기반 지식 그래프 구축, 멀티모달 처리, VLM 강화 쿼리까지 전체 파이프라인을 상세히 분석한다.
summary: RAG-Anything은 LightRAG(그래프 기반 RAG)를 핵심 엔진으로 사용하면서 이미지, 표, 수식 등 멀티모달 콘텐츠 처리를 추가한 프레임워크다. MinerU를 기본 파서로 사용하여 PDF를 구조화된 데이터로 변환하고, LLM 기반 엔티티/관계 추출로 지식 그래프를 구축한 뒤, 벡터 유사도 + 그래프 탐색 하이브리드 검색으로 답변을 생성한다.
published: 2026-03-22
modified: 2026-03-23
---

> [!summary]
>
> RAG-Anything은 LightRAG(그래프 기반 RAG)를 핵심 엔진으로 사용하면서 이미지, 표, 수식 등 멀티모달 콘텐츠 처리를 추가한 프레임워크다. MinerU를 기본 파서로 사용하여 PDF를 구조화된 데이터로 변환하고, LLM 기반 엔티티/관계 추출로 지식 그래프를 구축한 뒤, 벡터 유사도 + 그래프 탐색 하이브리드 검색으로 답변을 생성한다.

## 들어가며

[[MinerU - PDF Parser|MinerU]]를 처음 써봤을 때 PDF 파싱 성능에 감탄했었다. 레이아웃 분석, 표 인식, 수식 변환까지 — 기존 PDF 로더들과는 차원이 달랐다. 하지만 PyMuPDF와 YOLO 의존성 때문에 AGPL-3.0 라이센스가 걸려 있어서 상용 서비스에는 아쉽게도 쓸 수 없었다.

그러던 중 RAG-Anything이라는 프로젝트를 발견했다. MinerU를 기본 파서로 쓰면서, LightRAG라는 그래프 기반 RAG 엔진 위에 멀티모달 처리를 얹은 구조다. 단순히 텍스트를 벡터로 바꿔 검색하는 naive RAG가 아니라, **문서에서 엔티티와 관계를 추출하여 지식 그래프를 구축**하고, **이미지/표/수식을 VLM으로 분석하여 그래프에 통합**하는 방식이다.

이 글에서는 RAG-Anything의 내부 구조를 깊이 파헤쳐본다.

---

## MinerU 근황: PyMuPDF 제거, 그러나 여전히 AGPL

> [!info] MinerU 2.0 주요 변화
>
> - **PyMuPDF 제거** → pypdfium2 (Apache 2.0/BSD)로 대체
> - 1B 미만 파라미터의 end-to-end 멀티모달 파싱 모델 도입
> - 단일 모델로 다국어 인식, 레이아웃 분석, 표/수식 인식, 읽기 순서 정렬 통합
> - NVIDIA 4090에서 10,000+ tokens/sec 처리 속도 (sglang 가속)
> - 패키지명 `magic-pdf` → `mineru`로 변경
> - 2026년 2월 기준 최신 버전: **2.7.6**

MinerU 2.0에서 PyMuPDF를 pypdfium2로 교체하면서 라이센스 문제가 일부 해소되었다. 하지만 **YOLO(DocLayout-YOLO) 의존성이 여전히 남아 있어** 프로젝트 전체 라이센스는 AGPL-3.0을 유지하고 있다. YOLO를 더 permissive한 모델로 교체할 계획이 있다고 하니, 그때가 되면 상용 서비스에서도 자유롭게 쓸 수 있을 것으로 기대된다.

> [!tip]
>
> 개인 연구나 내부 문서 처리 용도라면 라이센스 제약 없이 자유롭게 활용 가능하다. 상용 서비스 통합 시에만 AGPL 조건을 주의하면 된다.

---

## RAG-Anything 전체 아키텍처

RAG-Anything의 파이프라인은 크게 5단계로 나뉜다:

![RAG-Anything KG Pipeline](https://i.imgur.com/Dw0Czd6.png)

### 핵심 구조

```
RAGAnything (메인 오케스트레이터)
├── ProcessorMixin    — 문서 처리 파이프라인
├── QueryMixin        — 쿼리/검색
├── BatchMixin        — 배치 처리
├── CallbackManager   — 이벤트 관측성
└── LightRAG          — 핵심 RAG 엔진 (위임)
    ├── 텍스트 청킹 + 임베딩
    ├── 엔티티/관계 추출 (LLM 기반)
    ├── 지식 그래프 구축/병합
    └── 하이브리드 검색 (벡터 + 그래프)
```

RAG-Anything은 LightRAG를 직접 구현하지 않고, **LightRAG의 스토리지/임베딩/그래프/쿼리 기능을 모두 위임**한다. RAG-Anything이 추가하는 것은 멀티모달 파싱, VLM 기반 콘텐츠 분석, 그리고 멀티모달 엔티티를 KG에 통합하는 레이어다.

---

## 문서 파싱

### 지원 파서 3종

| 파서 | 특징 | 용도 |
|------|------|------|
| **MineruParser** | mineru CLI 서브프로세스 래퍼. OCR 방식 선택(auto/ocr/txt) | 기본 파서. PDF 파싱 최강 |
| **DoclingParser** | docling 라이브러리 기반 | 복잡한 레이아웃에 강함 |
| **PaddleOCRParser** | 경량 OCR 기반 | 가벼운 처리가 필요할 때 |

커스텀 파서도 등록 가능하다:

```python
from raganything import register_parser

class MyParser(Parser):
    def parse_document(self, file_path, **kwargs):
        # 커스텀 파싱 로직
        ...

register_parser("my_parser", MyParser)
```

### 파싱 결과 구조

파서는 구조화된 리스트를 반환한다:

```python
[
    {"type": "text", "text": "Introduction...", "page_idx": 0, "text_level": 1},
    {"type": "image", "img_path": "./output/fig1.png", "image_caption": [...], "page_idx": 1},
    {"type": "table", "table_body": "<html>...</html>", "table_caption": [...], "page_idx": 2},
    {"type": "equation", "text": "E = mc^2", "page_idx": 3},
]
```

### 파싱 캐시

파일 경로 + 수정시간 + 설정을 MD5 해싱하여 캐시 키를 생성한다. 파일이 변경되지 않으면 재파싱을 건너뛴다.

```python
cache_key = MD5(json.dumps({
    "file_path": str(absolute_path),
    "mtime": file_mtime,
    "parser": parser_name,
    "parse_method": method,
}))
```

---

## 텍스트/멀티모달 분리 및 처리

파싱 결과는 `separate_content()`로 **텍스트**와 **멀티모달**(이미지, 표, 수식)로 분리된다.

### 텍스트 처리

텍스트는 LightRAG에 직접 삽입되어 자동으로:
1. 토큰 기반 청킹 (기본 1200 토큰, 100 토큰 오버랩)
2. 임베딩 벡터 생성 → chunks_vdb 저장
3. LLM 기반 엔티티/관계 추출 → 지식 그래프 구축

### 멀티모달 처리 파이프라인

4종류의 Modal Processor가 각 타입을 처리한다:

| 프로세서 | 대상 | 분석 방식 |
|----------|------|-----------|
| **ImageModalProcessor** | 이미지 | Vision 모델로 이미지 분석 + 주변 텍스트 컨텍스트 |
| **TableModalProcessor** | 표 | LLM으로 표 구조/데이터 패턴/트렌드 분석 |
| **EquationModalProcessor** | 수식 | LLM으로 수학 공식 파싱 및 설명 생성 |
| **GenericModalProcessor** | 기타 | 폴백 처리기 |

#### 멀티모달 처리 7단계

```
1. VLM/LLM으로 각 멀티모달 아이템 설명 생성 (동시 처리)

2. 타입별 청크 템플릿 적용
   - 이미지: "Image Content Analysis: Image Path: ... Visual Analysis: ..."
   - 표:     "Table Content Analysis: Structure: ... Data Analysis: ..."
   - 수식:   "Equation Content Analysis: Expression: ... Mathematical Analysis: ..."

3. LightRAG 청크 포맷으로 변환 + 스토리지 저장

4. extract_entities()로 엔티티/관계 추출 (LLM 기반)

5. "belongs_to" 관계 추가
   → 추출된 엔티티를 부모 멀티모달 엔티티에 연결

6. merge_nodes_and_edges()로 기존 KG에 병합

7. doc_status 업데이트
```

#### 컨텍스트 추출 (ContextExtractor)

멀티모달 아이템 처리 시 **주변 텍스트 컨텍스트**를 함께 제공하여 분석 품질을 높인다:

- **페이지 기반 모드**: 같은 페이지의 텍스트를 컨텍스트로 사용
- **청크 기반 모드**: 인접 청크를 윈도우로 추출
- 토크나이저로 정확한 토큰 수 제한 (기본 2000 토큰)

---

## LightRAG 심층 분석

RAG-Anything의 핵심 엔진인 LightRAG를 깊이 들여다본다. [[Knowledge Graphs for RAG|지식 그래프를 활용한 RAG]]의 실제 구현체라고 볼 수 있다.

### LightRAG란

LightRAG는 홍콩대(HKU)에서 개발한 **LLM 기반 지식 그래프 RAG 시스템**이다. 전통적인 벡터 RAG와 달리, 텍스트에서 엔티티와 관계를 추출하여 지식 그래프를 구축하고, 쿼리 시 **벡터 검색 + 그래프 탐색**을 결합한다.

### 엔티티/관계 추출 — 100% LLM 기반

> [!important]
>
> LightRAG의 엔티티/관계 추출은 NER 모델이나 규칙 기반이 아니라 **완전히 LLM 기반**이다. LLM에게 "Knowledge Graph Specialist" 역할을 부여하고, 구조화된 포맷으로 추출을 요청한다.

#### 프롬프트 구조

시스템 프롬프트가 LLM에게 역할을 부여한다:

```
---Role---
You are a Knowledge Graph Specialist responsible for extracting
entities and relationships from the input text.
```

엔티티와 관계를 **한 번의 LLM 호출로 동시에 추출**한다:

```
# 엔티티 출력 포맷
entity<|#|>entity_name<|#|>entity_type<|#|>entity_description

# 관계 출력 포맷
relation<|#|>source_entity<|#|>target_entity<|#|>relationship_keywords<|#|>relationship_description
```

#### 실제 추출 예시

입력 텍스트:
```
Stock markets faced a sharp downturn today as tech giants saw
significant declines, with the global tech index dropping by 3.4%...
Nexon Technologies saw its stock plummet by 7.8%...
```

LLM 출력:
```
entity<|#|>Global Tech Index<|#|>category<|#|>The Global Tech Index tracks the performance of major technology stocks and experienced a 3.4% decline today.
entity<|#|>Nexon Technologies<|#|>organization<|#|>Nexon Technologies is a tech company that saw its stock decline by 7.8% after disappointing earnings.
relation<|#|>Nexon Technologies<|#|>Global Tech Index<|#|>company impact, index movement<|#|>Nexon Technologies' stock decline contributed to the overall drop in the Global Tech Index.
<|COMPLETE|>
```

#### 관계 추출 규칙

| 규칙 | 설명 |
|------|------|
| **N-ary 분해** | 3자 이상 관계는 이진 관계로 분해 (Alice-Bob-Carol → Alice-Bob, Alice-Carol, Bob-Carol) |
| **무방향** | 모든 관계는 무방향(undirected). src↔tgt 바꿔도 같은 관계 |
| **키워드 포함** | 관계에 고수준 키워드 포함 (예: "market performance, investor sentiment") |
| **자기 참조 금지** | source == target인 관계는 스킵 |

#### Gleaning (재추출)

추출 후 선택적으로 gleaning 단계가 있다. LLM에게 "놓친 엔티티/관계가 있으면 추가 추출해라"고 요청한다:

```
Based on the last extraction task, identify and extract any
**missed or incorrectly formatted** entities and relationships...
```

- 더 긴 설명이 나오면 기존 것을 교체
- 새로운 엔티티/관계가 발견되면 병합
- `entity_extract_max_gleaning` 설정으로 반복 횟수 조절 (기본: 0)

### 지식 그래프 구축 파이프라인

1. **청킹** — 텍스트를 1200 토큰 단위로 분할 (100 토큰 오버랩)
2. **LLM 추출** — 각 청크에서 LLM으로 엔티티 + 관계를 동시 추출. Gleaning으로 누락분 재추출
3. **결과 파싱** — `<|#|>` 구분자로 LLM 출력을 엔티티(name, type, description)와 관계(src, tgt, keywords, description)로 분리
4. **엔티티 병합** — 같은 이름의 엔티티는 설명을 수집하여 Map-Reduce 방식으로 LLM 요약 → Graph DB + Entity VDB에 upsert
5. **관계 병합** — 같은 (src, tgt) 쌍의 관계는 설명+키워드 병합, 가중치 합산 → Graph DB + Relationship VDB에 upsert

### 엔티티/관계 병합 — Map-Reduce 요약

동일 엔티티가 여러 청크에서 발견되면:

1. 기존 KG에서 같은 이름의 엔티티 확인
2. 모든 설명을 수집 + 중복 제거
3. 설명이 많으면 **Map-Reduce 방식으로 LLM 요약**:
   - 설명들을 토큰 제한에 맞게 분할
   - 각 그룹을 LLM으로 요약
   - 요약이 여전히 길면 재귀적으로 반복
4. `entity_type`은 가장 많이 나온 타입 선택
5. Graph DB + Vector DB 모두 업데이트

관계 병합도 동일한 방식에 추가로:
- **키워드 병합**: 모든 청크의 키워드를 합쳐서 중복 제거
- **가중치 합산**: 출현 횟수가 많을수록 weight 증가 (=더 중요한 관계)

### 노드/엣지 구조

```python
# 노드 (엔티티)
{
    "entity_name": "GDP Growth Rate",
    "entity_type": "concept",
    "description": "GDP Growth Rate is an economic indicator...",
    "source_id": "chunk-abc123",
    "file_path": "economic_report.pdf",
}

# 엣지 (관계)
{
    "src_id": "GDP Growth Rate",
    "tgt_id": "Table1",
    "description": "Entity GDP Growth Rate belongs to Table1",
    "keywords": "belongs_to,part_of,contained_in",
    "weight": 10.0,
    "source_id": "chunk-abc123",
}
```

### 스토리지 구조 — 벡터 DB + 그래프 DB 동시 사용

LightRAG는 **벡터 DB와 그래프 DB를 동시에** 사용한다. 같은 데이터가 양쪽에 저장되어, 검색 시 벡터 유사도 + 그래프 탐색을 결합할 수 있다.

| 스토리지 | 타입 | 용도 |
|----------|------|------|
| `chunk_entity_relation_graph` | **Graph DB** | 엔티티-관계 그래프 (노드 + 엣지) |
| `entities_vdb` | **Vector DB** | 엔티티 임베딩 (의미 검색용) |
| `relationships_vdb` | **Vector DB** | 관계 임베딩 (의미 검색용) |
| `chunks_vdb` | **Vector DB** | 텍스트 청크 임베딩 |
| `text_chunks` | KV 저장소 | 청크 원문 텍스트 |
| `full_entities` / `full_relations` | KV 저장소 | 엔티티/관계 전체 메타데이터 |
| `llm_response_cache` | KV 저장소 | LLM 응답 캐시 |
| `doc_status` | KV 저장소 | 문서 처리 상태 추적 |

인덱싱 시 엔티티는 **Graph DB에 노드로** + **Vector DB에 임베딩으로** 동시 저장된다. 관계도 마찬가지로 Graph DB의 엣지 + Vector DB의 임베딩으로 이중 저장된다.

---

## 지원 백엔드 및 설정

### 파서 (Document Parser)

| 파서 | 설명 | 기본값 |
|------|------|--------|
| **MineruParser** | MinerU CLI 래퍼. 레이아웃 분석 + OCR 최강 | ✅ 기본 |
| **DoclingParser** | IBM docling 기반. 복잡한 문서 구조에 강함 | |
| **PaddleOCRParser** | PaddleOCR 기반 경량 파서 | |
| **커스텀 파서** | `register_parser()`로 등록 가능 | |

### 벡터 DB

| 백엔드 | 외부 서비스 필요 | 기본값 |
|--------|----------------|--------|
| **NanoVectorDB** | 아니오 (파일 기반) | ✅ 기본 |
| **FAISS** | 아니오 (파일 기반) | |
| **Qdrant** | 예 (`QDRANT_URL`) | |
| **Milvus** | 예 (`MILVUS_URI`) | |
| **PostgreSQL pgvector** | 예 (`POSTGRES_*`) | |
| **MongoDB** | 예 (`MONGO_URI`) | |
| **Chroma** | 아니오 | (deprecated) |

### 그래프 DB

| 백엔드 | 외부 서비스 필요 | 기본값 |
|--------|----------------|--------|
| **NetworkX** | 아니오 (파일 기반) | ✅ 기본 |
| **Neo4j** | 예 (`NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`) | |
| **Memgraph** | 예 (`MEMGRAPH_URI`) | |
| **AGE** (PostgreSQL 확장) | 예 (`AGE_POSTGRES_*`) | |
| **PostgreSQL** | 예 (`POSTGRES_*`) | |
| **MongoDB** | 예 (`MONGO_URI`) | |

### KV 저장소

| 백엔드 | 외부 서비스 필요 | 기본값 |
|--------|----------------|--------|
| **JsonKVStorage** | 아니오 (파일 기반) | ✅ 기본 |
| **Redis** | 예 (`REDIS_URI`) | |
| **PostgreSQL** | 예 (`POSTGRES_*`) | |
| **MongoDB** | 예 (`MONGO_URI`) | |

### 기본값 정리

별도 설정 없이 사용하면 **모든 스토리지가 파일 기반**으로 동작한다:

```python
# LightRAG 기본값 (외부 서비스 불필요)
working_dir = "./rag_storage"
vector_storage = "NanoVectorDBStorage"      # 파일 기반 벡터 DB
graph_storage = "NetworkXStorage"           # 파일 기반 그래프
kv_storage = "JsonKVStorage"                # JSON 파일 기반 KV
doc_status_storage = "JsonDocStatusStorage"  # JSON 파일 기반
```

프로덕션 환경에서는 이렇게 변경할 수 있다:

```python
rag = LightRAG(
    working_dir="./rag_storage",
    vector_storage="QdrantVectorDBStorage",
    graph_storage="Neo4JStorage",
    kv_storage="RedisKVStorage",
    vector_db_storage_cls_kwargs={
        "cosine_better_than_threshold": 0.3
    }
)
```

환경변수로도 설정 가능하다:

```bash
VECTOR_STORAGE=MilvusVectorDBStorage
MILVUS_URI=http://milvus:19530
GRAPH_STORAGE=Neo4JStorage
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=password
```

> [!tip]
>
> RAG-Anything은 스토리지 설정을 LightRAG에 위임한다. `lightrag_kwargs`로 원하는 백엔드를 전달하면 된다. RAG-Anything 자체의 설정은 파서 선택, 멀티모달 처리 ON/OFF, 컨텍스트 윈도우 등 문서 처리 관련에 집중한다.

---

## 쿼리/검색 파이프라인

### 검색 모드

| 모드 | 검색 방식 |
|------|-----------|
| **local** | Entity VDB에서 low-level 키워드로 검색 |
| **global** | Relationship VDB에서 high-level 키워드로 검색 |
| **hybrid** | local + global 결합 |
| **naive** | Chunk VDB만 사용 (단순 벡터 유사도) |
| **mix** | hybrid + naive 결합 |
| **bypass** | 검색 없이 LLM 직접 호출 |

### 쿼리 흐름 (4단계)

```
쿼리 입력
    ↓
Stage 1: LLM으로 키워드 추출
  → high-level (글로벌용) + low-level (로컬용)
    ↓
Stage 2: 모드별 검색
  → 벡터 유사도로 후보 엔티티/관계 검색
  → 그래프 탐색으로 관련 노드 확장
    ↓
Stage 3: 토큰 제한 적용
  → 유사도 점수 기준 우선순위 정렬
  → max_entity_tokens, max_relation_tokens 내로 절단
    ↓
Stage 4: 컨텍스트 조합 + LLM 답변 생성
  → KG 데이터 + 텍스트 청크 + 레퍼런스 → LLM
```

### 이미지가 검색되면? — VLM 강화 쿼리

이미지는 KG에 **텍스트 설명**으로 저장된다:

```
Image Content Analysis:
Image Path: ./output/figure1.png
Captions: [캡션들]
Visual Analysis: [VLM이 생성한 상세 설명]
```

> [!info] 핵심 설계: Late Binding
>
> 인덱싱 시에는 이미지를 base64로 저장하지 않는다. 쿼리 시에만 이미지 파일을 읽어서 VLM에 전달하는 **late binding** 방식으로, KG를 경량하게 유지한다.

VLM 강화 쿼리 흐름 (`aquery_vlm_enhanced`):

```
1. LightRAG.aquery(query, only_need_prompt=True)
   → 텍스트 기반으로 관련 청크 검색 (이미지 설명 포함)

2. 정규식으로 "Image Path:" 추출
   → r"Image Path:\s*([^\r\n]*?\.(?:jpg|jpeg|png|...))"

3. 이미지 경로 검증
   → 파일 존재 확인, 심볼릭 링크 거부, 안전 디렉토리 확인, 50MB 크기 제한

4. base64 인코딩 + [VLM_IMAGE_N] 마커 삽입

5. OpenAI 호환 멀티모달 메시지 구성
   → [
       {"type": "text", "text": "...컨텍스트..."},
       {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}},
       {"type": "text", "text": "...User Question: ..."}
     ]

6. vision_model_func에 전달
   → VLM이 텍스트 + 실제 이미지 픽셀을 함께 분석하여 답변 생성
```

---

## 임베딩 모델

| 환경 | 모델 | 차원 |
|------|------|------|
| **기본 (OpenAI)** | `text-embedding-3-large` | 3072 |
| **LM Studio (로컬)** | `nomic-embed-text-v1.5` | 768 |
| **vLLM (로컬)** | `BAAI/bge-m3` | 1024 |
| **Ollama (로컬)** | `bge-m3:latest` | 1024 |

환경변수로 설정 가능:

```bash
EMBEDDING_MODEL=text-embedding-3-large
EMBEDDING_DIM=3072
EMBEDDING_BINDING=openai  # openai, ollama, lmstudio, vllm, azure_openai
```

코드에서의 사용:

```python
from lightrag.llm.openai import openai_embed
from lightrag.utils import EmbeddingFunc

embedding_func = EmbeddingFunc(
    embedding_dim=3072,
    max_token_size=8192,
    func=openai_embed.func  # .func으로 언래핑 필수 (이중 래핑 방지)
)
```

> [!warning]
>
> `openai_embed`는 이미 `EmbeddingFunc` 인스턴스이므로, `lambda texts: openai_embed(texts, ...)`처럼 한번 더 감싸면 "Vector count mismatch" 에러가 발생한다. 반드시 `.func`으로 내부 함수만 꺼내서 사용해야 한다.

---

## 캐싱 전략

RAG-Anything은 4단계 캐싱으로 효율을 극대화한다:

| 캐시 레이어 | 키 | 용도 |
|-------------|-----|------|
| **파싱 캐시** | MD5(파일경로 + mtime + 설정) | 문서 재파싱 방지 |
| **청크 벡터 캐시** | chunks_vdb | 임베딩 재계산 방지 |
| **LLM 응답 캐시** | llm_response_cache | 동일 LLM 호출 방지 |
| **쿼리 캐시** | hash(query + mode + ...) | 동일 쿼리 결과 재사용 |

---

## 핵심 설정 파라미터

### RAG-Anything 설정

```bash
# 파싱
PARSER=mineru          # mineru, docling, paddleocr
PARSE_METHOD=auto      # auto, ocr, txt

# 멀티모달 처리
ENABLE_IMAGE_PROCESSING=true
ENABLE_TABLE_PROCESSING=true
ENABLE_EQUATION_PROCESSING=true

# 컨텍스트 추출
CONTEXT_WINDOW=1
CONTEXT_MODE=page      # page, chunk
MAX_CONTEXT_TOKENS=2000
```

### LightRAG 핵심 설정

| 파라미터 | 기본값 | 설명 |
|----------|--------|------|
| `chunk_token_size` | 1200 | 청크 크기 |
| `chunk_overlap_token_size` | 100 | 청크 오버랩 |
| `entity_extract_max_gleaning` | 0 | gleaning 반복 횟수 |
| `top_k` | 10 | 검색할 엔티티/관계 수 |
| `chunk_top_k` | 8 | 검색할 텍스트 청크 수 |
| `cosine_threshold` | 0.2 | 벡터 유사도 컷오프 |
| `force_llm_summary_on_merge` | 3 | N개 이상 설명이면 LLM 요약 강제 |
| `kg_chunk_pick_method` | WEIGHT | 청크 선택 방식 (WEIGHT/VECTOR) |

---

## 실제 테스트: 학술 논문 PDF 파싱

RAG-Anything의 기본 파서인 MinerU 2.7.6으로 실제 학술 논문 PDF를 파싱해 보았다.

### 테스트 환경

| 항목 | 사양 |
|------|------|
| **OS** | macOS 26.3 |
| **Chip** | Apple M4 Pro |
| **RAM** | 48 GB |
| **Python** | 3.13.12 |
| **MinerU** | 2.7.6 (hybrid_auto 모드) |

### 테스트 문서

- **논문**: "Efficient Inverted Indexes for Approximate Retrieval over Learned Sparse Representations" (SIGIR '24)
- **페이지**: 11 pages, 844KB
- **특징**: 2단 레이아웃, 7개 차트/다이어그램, 2개 표, 수식, 알고리즘 의사코드, 참고문헌

### 파싱 속도

- **총 소요 시간**: 약 7분 22초
- **페이지당**: ~40초
- GPU 없이 CPU(Apple Silicon MPS) 기반 처리

### 파싱 결과 통계

```
Total items: 232

Type distribution:
  text:          158
  header:         20
  code:           24  (알고리즘 의사코드)
  list:           10
  image:           7  (논문 Figure 1~7)
  table:           2  (Table 1, 2)
  equation:        3  (수식 3개)
  page_footnote:   7
  aside_text:      1
```

### 레이아웃 분석 결과

MinerU는 레이아웃 분석 결과를 색상으로 구분한 PDF를 생성한다:

![레이아웃 감지 결과 - 1페이지](https://i.imgur.com/xXwUYaK.png)

> [!info]
>
> 색상 코드: 🔴 빨강 = 본문 텍스트, 🟢 초록 = 헤더/제목, 🟡 노랑 = 표, 🔵 파랑 = 이미지/차트, 🟣 보라 = 각주/메타데이터

2단 레이아웃을 정확하게 인식하고, 각 영역별로 올바르게 분류하고 있다. 제목, 저자 정보, Abstract, 본문, 참고문헌 형식까지 모두 구분된다.

**4페이지 (차트 + 본문 혼합):**

![레이아웃 감지 결과 - 4페이지](https://i.imgur.com/Hq7aBSO.png)

차트(Figure 1, 2)와 캡션이 정확히 분리되었다. 2단 레이아웃에서 차트가 한 컬럼만 차지하는 경우도 올바르게 처리한다.

**8페이지 (대형 표 + 차트 + 본문):**

![레이아웃 감지 결과 - 8페이지](https://i.imgur.com/Mt7T1CZ.png)

페이지 상단의 대형 성능 비교 표(Table 1)가 정확히 인식되었고, 하단의 차트(Figure 4)와 소형 표(Table 2)도 개별적으로 분리되었다.

### 이미지 추출 결과

총 12개 파일이 추출되었다: 논문 Figure 7개 + Table 이미지 2개 + 수식 이미지 3개

#### Figure 추출 (7/7 모두 추출)

**Figure 3 — SEISMIC 아키텍처 다이어그램:**

![추출된 아키텍처 Figure](https://i.imgur.com/AbYmRG5.jpeg)

> 색상, 점선, 텍스트 라벨까지 원본과 동일하게 추출되었다. 복잡한 구조적 다이어그램도 깨끗하게 나온다.

**Figure 1 — L1 mass 차트:**

![추출된 Figure - L1 Mass](https://i.imgur.com/nadR5Vl.jpeg)

> 축 라벨, 범례, 곡선 모두 선명하게 추출.

#### 표 추출 (2/2 모두 추출)

**Table 1 — 대형 성능 비교 표 (4개 데이터셋 × 8개 정확도 수준):**

![추출된 테이블 - Latency](https://i.imgur.com/IH9cLaV.jpeg)

> 이미지로도 추출되었지만, 동시에 **HTML 구조**로도 파싱되었다 (5,507자의 `<table>` HTML). 행/열 구조, 소수점, 괄호 안 speedup 값까지 잘 살아있다.

**Table 2 — 인덱스 크기/빌드 시간:**

![추출된 테이블 - Index Size](https://i.imgur.com/64BCyH6.jpeg)

> 간결한 표도 HTML 구조(399자)로 깔끔하게 파싱.

#### 수식 추출 (3/3 추출)

![추출된 수식 1](https://i.imgur.com/6TOi3eb.jpeg)

![추출된 수식 2](https://i.imgur.com/kwZdKzC.jpeg)

![추출된 수식 3](https://i.imgur.com/l7w92ei.jpeg)

> 수식은 이미지로 추출되며, 마크다운에서는 LaTeX 형식(`$S = \arg\max_{x \in X}^{(k)} \langle q, x \rangle$`)으로도 변환된다.

#### 불필요한 이미지?

> [!success] 쓸데없는 이미지 없음
>
> 추출된 12개 이미지 모두 논문의 실제 콘텐츠(Figure 7개 + Table 이미지 2개 + 수식 3개)에 해당한다. 페이지 번호, 헤더/푸터, 장식 요소 등 불필요한 이미지는 하나도 추출되지 않았다.

### 텍스트 추출 품질

- **2단 레이아웃**: 좌→우 칼럼 순서로 정확히 읽음
- **참조 번호**: `[17, 18]`, `[6, 7, 19, 35, 37]` 등 정확히 보존
- **특수 문자**: `$L_1$`, `$k$` 등 수학 기호 LaTeX 변환
- **알고리즘 의사코드**: Algorithm 1, 2가 `code` 타입으로 24개 라인 추출
- **각주**: URL 포함 각주 7개 정확히 분리

### 아쉬운 점

- Table 1 캡션에서 `μsec` → `??sec`로 변환됨 (유니코드 μ 문자 인식 실패)
- 알고리즘 의사코드가 `code` 타입으로 분류되어 구조 정보(if/for 등)가 평문으로 처리됨
- CPU 전용 환경에서 11페이지에 ~7분 소요 (GPU 있으면 훨씬 빠를 것으로 예상)

### 종합 평가

| 항목 | 평가 |
|------|------|
| **레이아웃 분석** | 2단 레이아웃, 차트/표/본문 분리 모두 정확 |
| **이미지 추출** | 7/7 Figure 모두 추출, 불필요 이미지 0 |
| **표 추출** | HTML 구조 + 이미지 동시 추출, 셀 데이터 정확 |
| **수식 추출** | 이미지 + LaTeX 동시 추출 |
| **텍스트 품질** | 참조 번호, 특수 문자, 2단 레이아웃 순서 모두 정확 |
| **처리 속도** | 11페이지 / 7분 22초 (CPU only, Apple M4 Pro) |

MinerU 2.7.6은 학술 논문 파싱에서 매우 높은 수준의 결과를 보여준다. 특히 복잡한 레이아웃의 표와 차트를 정확히 분리하고, HTML 구조까지 추출하는 점은 RAG 파이프라인에서 큰 장점이다.

---

## 정리

RAG-Anything의 핵심 기법들을 정리하면:

1. **그래프 기반 RAG** — 단순 벡터 검색이 아닌 엔티티-관계 지식 그래프 + 벡터 하이브리드 검색
2. **LLM 기반 KG 구축** — NER이 아닌 LLM 프롬프트로 엔티티/관계를 한 번에 추출
3. **멀티모달 통합** — VLM/LLM으로 이미지·표·수식을 텍스트 설명으로 변환 후 KG에 통합
4. **Late Binding 이미지 처리** — 인덱싱 시 경량 저장, 쿼리 시에만 실제 이미지를 VLM에 전달
5. **Map-Reduce 엔티티 병합** — 여러 청크의 동일 엔티티 설명을 LLM으로 재귀 요약
6. **belongs_to 관계** — 멀티모달 콘텐츠에서 추출된 엔티티를 부모 엔티티에 연결
7. **다층 캐싱** — 파싱·임베딩·LLM 응답·쿼리 결과 4단계 캐싱
8. **컨텍스트 인식 처리** — 멀티모달 아이템에 주변 텍스트 컨텍스트를 함께 제공

단순히 "문서를 벡터로 바꿔서 검색"하는 naive RAG를 넘어, 문서의 구조와 의미를 **지식 그래프로 표현**하고, 텍스트뿐 아니라 **이미지·표·수식까지 통합**하여 검색하는 접근이 인상적이다. 특히 엔티티 추출부터 관계 병합, 쿼리까지 전 과정에서 LLM을 적극 활용하는 것이 GraphRAG 계열 시스템의 특징이자 장단점이라 할 수 있다. LLM 호출 비용과 지연시간이 트레이드오프가 될 수 있지만, 그만큼 풍부한 컨텍스트를 제공할 수 있다는 점에서 복잡한 문서 처리에 적합한 아키텍처다.

---

## 참고자료

- [RAG-Anything GitHub](https://github.com/HKUDS/RAG-Anything) — RAG-Anything 공식 저장소
- [LightRAG GitHub](https://github.com/HKUDS/LightRAG) — LightRAG 공식 저장소 (홍콩대 HKU-DS)
- [LightRAG 논문](https://arxiv.org/abs/2410.05779) — "LightRAG: Simple and Fast Retrieval-Augmented Generation"
- [MinerU GitHub](https://github.com/opendatalab/MinerU) — MinerU 공식 저장소 (OpenDataLab)
- [PDF-Extract-Kit](https://github.com/opendatalab/PDF-Extract-Kit) — MinerU의 핵심 PDF 추출 엔진
- [[MinerU - PDF Parser|MinerU - 고품질 PDF 변환 및 데이터 추출 도구]] — MinerU 상세 리뷰
- [[Knowledge Graphs for RAG]] — 지식 그래프를 활용한 RAG 기초
- [[RAG용 PDF Loader 비교]] — PDF 로더 비교 분석
