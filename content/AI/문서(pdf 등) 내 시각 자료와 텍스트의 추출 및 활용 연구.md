---
title: 문서(pdf 등) 내 시각 자료와 텍스트의 추출 및 활용 연구
date: 2024-06-08
tags:
- AI
- RAG
- MultiModal
- PDF
- pdf-parser
draft: false
enableToc: true
description: 멀티모달 RAG를 통한 문서 내 텍스트와 이미지 추출 및 활용 연구
summary: "멀티모달 RAG를 통한 문서 내 텍스트와 이미지 추출 및 활용 연구"
published: 2024-06-08
modified: 2024-06-08
---
# Multi-Modal RAG

### 배경:
- GPT-4V, GPT-4o와 같은 다중 모달 LLM 등장
- RAG에서 text뿐만 아니라 image도 함께 활용하는 방안

### Why Text Extraction is hard

PDF에서 텍스트를 추출하는 것은 매우 까다로울 수 있다. 여러 경우에 예상되는 결과가 명확하지 않다:

1. **단락**: 원본 PDF에 있던 것과 같은 위치에 줄 바꿈이 있어야 하는지 아니면 하나의 텍스트 블록이어야 하는지?
2. **페이지 번호**: 추출물에 포함되어야 하는지?
3. **헤더 및 푸터**: 페이지 번호와 유사하게 - 추출해야 하는지?
4. **개요**: 개요를 모두 추출해야 하는지?
5. **서식**: 텍스트가 **굵게** 또는 _기울임꼴_인 경우 출력에 포함되어야 하는지?
6. **표**: 텍스트 추출이 표를 건너뛰어야 하는지? 단지 텍스트만 추출해야 하는지? 테두리가 Markdown과 같은 방식으로 표시되어야 하는지 아니면 구조가 HTML 테이블로 표시되어야 하는지? 병합된 셀은 어떻게 처리할 것인지?
7. **캡션**: 이미지와 표 캡션이 포함되어야 하는지?
8. **합자**: 유니코드 기호 [U+FB00](https://www.compart.com/de/unicode/U+FB00)은 두 소문자 'f'에 대한 단일 기호 ﬀ이다. 유니코드 기호 'ﬀ'로 파싱되어야 하는지 아니면 두 개의 ASCII 기호 'ff'로 파싱되어야 하는지?
9. **SVG 이미지**: 텍스트 부분을 추출해야 하는지?
10. **수학 공식**: 추출해야 하는지? 공식에는 인덱스와 중첩된 분수가 있다.
11. **공백 문자**: 3cm의 수직 공백에 대해 몇 개의 새 줄을 추출해야 하는지? 3cm의 수평 공백이 있는 경우 몇 개의 공백을 추출해야 하는지? 탭과 공백을 언제 추출할 것인지?
12. **각주**: 여러 페이지의 텍스트를 추출할 때 각주는 어디에 표시되어야 하는지?
13. **하이퍼링크 및 메타데이터**: 전혀 추출해야 하는지? 어떤 형식으로 어디에 배치해야 하는지?
14. **선형화**: 단락 사이에 떠 있는 그림이 있다고 가정할 때, 먼저 단락을 마치거나 그림 텍스트를 사이에 넣어야 하는지?

그런 다음 대부분의 사람들이 올바른 출력에 동의하겠지만 PDF가 정보를 저장하는 방식으로 인해 그것을 달성하기 어려운 문제가 있다:

1. **표**: 일반적으로 표는 절대 위치가 지정된 텍스트일 뿐이다. 최악의 경우, 모든 글자마다 절대 위치가 지정될 수 있다. 이로 인해 열/행이 어디에 있는지 파악하기 어렵다.
2. **이미지**: 때로는 PDF가 표시된 대로 텍스트를 포함하지 않고 대신 이미지를 포함한다. 텍스트를 복사할 수 없을 때 이것을 알아차린다. 그런 다음 이미지와 배경에 텍스트 레이어를 포함하는 PDF 파일이 있다. 이는 일반적으로 문서가 스캔되었을 때 발생한다. 오늘날 스캐닝 소프트웨어(OCR)는 매우 좋지만, 가끔 실패한다. PyPDF2는 OCR 소프트웨어가 아니므로 이러한 실패를 감지할 수 없다. PyPDF2는 이미지에서 텍스트를 추출할 수 없다.

### 목표:
1. 문서 내의 시각 데이터 추출, 답변 생성시 관련있는 시각 데이터 답변에 포함
2. 문서 내의 시각 데이터에 담긴 정보 이해

### 주요 방법:

#### 1. Retrieve Raw Image
- 다중 모달 임베딩(ex: CLIP)을 사용하여 이미지와 텍스트를 임베딩
- 유사성 검색을 사용하여 둘 다 검색
- 다중 모달 LLM에 원본 이미지와 텍스트 조각을 전달하여 답변 합성

#### 2. Retrieve Image Summary
- 다중 모달 LLM(ex: GPT-4V, GPT-4o, LLaVA, FUYU)를 사용하여 이미지에서 텍스트 요약 생성
- 텍스트 임베딩, 검색
- LLM에 텍스트 조각을 전달하여 답변을 합성

#### 3. Retrieve Raw Image + Image Summary
- 다중 모달 LM(ex: GPT-4V, GPT-4o, LLaVA, FUYU)을 사용하여 이미지에서 텍스트 요약 생성
- 원본 이미지에 대한 참조와 함께 이미지 요약을 임베딩하고 검색
- 다중 모달 LLM에 원본 이미지와 텍스트 조각을 전달하여 답변을 합성

> Demo에선 UnStructured PDF Loader 사용
> - 이유: partition_pdf(이미지 추출 기능) 제공

![](https://i.imgur.com/rqUfDaj.png)

## 절차

### 1. 데이터 로드

#### 1-1. PDF에서 요소(image, text) 추출
```python
def extract_pdf_elements(path, fname):
    """
    PDF 파일에서 이미지, 테이블, 그리고 텍스트 조각을 추출한다.
    path: 이미지(.jpg)를 저장할 파일 경로
    fname: 파일 이름
    """
    return partition_pdf(
        filename=os.path.join(path, fname),
        extract_images_in_pdf=True, # PDF 내 이미지 추출 활성화
        infer_table_structure=True, # 테이블 구조 추론 활성화
        chunking_strategy="by_title", # 제목별로 텍스트 조각화
        max_characters=4000, # 최대 문자 수
        new_after_n_chars=3800, # 이 문자 수 이후에 새로운 조각 생성
        combine_text_under_n_chars=2000, # 이 문자 수 이하의 텍스트는 결합
        image_output_dir_path=path, # 이미지 출력 디렉토리 경로
    )
```

#### 1-2. 요소 유형별(테이블, 텍스트)로 분류

```python
def categorize_elements(raw_pdf_elements):
    """
    PDF에서 추출된 요소를 테이블과 텍스트로 분류한다.
    raw_pdf_elements: unstructured.documents.elements의 리스트
    """
    tables = [] # 테이블 저장 리스트
    texts = [] # 텍스트 저장 리스트
    for element in raw_pdf_elements:
        if "unstructured.documents.elements.Table" in str(type(element)):
            tables.append(str(element)) # 테이블 요소 추가
        elif "unstructured.documents.elements.CompositeElement" in str(type(element)):
            texts.append(str(element)) # 텍스트 요소 추가
    return texts, tables
```


### 2. 데이터 요약

#### 2-1. 텍스트 및 테이블 요약
```python
def generate_text_summaries(texts, tables, summarize_texts=False):
    """
    텍스트 요소 요약
    texts: 문자열 리스트
    tables: 문자열 리스트
    summarize_texts: 텍스트 요약 여부를 결정. True/False
    """
    
    # 프롬프트 설정
    prompt_text = """You are an assistant tasked with summarizing tables and text for retrieval. \
    These summaries will be embedded and used to retrieve the raw text or table elements. \
    Give a concise summary of the table or text that is well optimized for retrieval. Table or text: {element} """
    prompt = ChatPromptTemplate.from_template(prompt_text)
    
    # 텍스트 요약 체인
    model = ChatOpenAI(temperature=0, model="gpt-4")
    summarize_chain = {"element": lambda x: x} | prompt | model | StrOutputParser()
    
    # 요약을 위한 빈 리스트 초기화
    text_summaries = []
    table_summaries = []
    
    # 제공된 텍스트에 대해 요약이 요청되었을 경우 적용
    if texts and summarize_texts:
        text_summaries = summarize_chain.batch(texts, {"max_concurrency": 5})
    elif texts:
        text_summaries = texts
    
    # 제공된 테이블에 적용
    if tables:
        table_summaries = summarize_chain.batch(tables, {"max_concurrency": 5})
    
    return text_summaries, table_summaries
```


#### 2-2. 이미지 요약

```python
def generate_img_summaries(path):
    """
    이미지에 대한 요약과 base64 인코딩된 문자열을 생성한다.
    path: Unstructured에 의해 추출된 .jpg 파일 목록의 경로
    """
    
    # base64로 인코딩된 이미지를 저장할 리스트
    img_base64_list = []
    
    # 이미지 요약을 저장할 리스트
    image_summaries = []
    
    # 요약을 위한 프롬프트
    prompt = """You are an assistant tasked with summarizing images for retrieval. \
    These summaries will be embedded and used to retrieve the raw image. \
    Give a concise summary of the image that is well optimized for retrieval."""
    
    # 이미지에 적용
    for img_file in sorted(os.listdir(path)):
        if img_file.endswith(".jpg"):
            img_path = os.path.join(path, img_file)
            base64_image = encode_image(img_path)
            img_base64_list.append(base64_image)
            image_summaries.append(image_summarize(base64_image, prompt))
    
    return img_base64_list, image_summaries
```


### 3. Vectorstore에 저장

- Docstore: 원본 텍스트, 테이블, 이미지
- Vectorstore: 벡터


## 참조

- [[유튜브 테디노트] GPT4o를 사용하여 PDF 내 표와 이미지를 참고하여 답변하는멀티모달 RAG](https://youtu.be/U_f4-Br3_Y0?si=Q-cRhXih576BoDcg)
- [[DeepLearning.AI]building-multimodal-search-and-rag](https://learn.deeplearning.ai/courses/building-multimodal-search-and-rag)
- [PyPDF2 Documentation](https://pypdf2.readthedocs.io/)
- https://www.youtube.com/watch?v=U_f4-Br3_Y0
- [Medium]Multimodal RAG using Langchain Expression Language And GPT4-Vision](https://medium.aiplanet.com/multimodal-rag-using-langchain-expression-language-and-gpt4-vision-8a94c8b02d21)
- [[Langchain]How to pass multimodal data directly to models](https://python.langchain.com/v0.2/docs/how_to/multimodal_inputs/)
- [https://paperswithcode.com/paper/llava-uhd-an-lmm-perceiving-any-aspect-ratio](https://paperswithcode.com/paper/llava-uhd-an-lmm-perceiving-any-aspect-ratio)
- [https://huggingface.co/docs/transformers/en/model_doc/llava](https://huggingface.co/docs/transformers/en/model_doc/llava)
- [https://github.com/langchain-ai/langchain/blob/master/cookbook/multi_modal_output_agent.ipynb](https://github.com/langchain-ai/langchain/blob/master/cookbook/multi_modal_output_agent.ipynb)