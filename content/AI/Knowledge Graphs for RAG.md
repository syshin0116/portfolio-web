---
title: Knowledge Graphs for RAG
date: 2024-08-15
tags:
- ai
- deep-learning
- knowledge-graph
- rag
- neo4j
- graph-database
draft: false
enableToc: true
description: RAG(Retrieval-Augmented Generation) 시스템에서 지식 그래프 활용 방법과 Neo4j 구현
summary: "지식 그래프(Knowledge Graph)는 노드(entities)와 관계(relationships)로 정보를 저장하는 데이터베이스로, RAG 시스템에서 정보 검색과 컨텍스트 제공을 향상시킨다. Neo4j와 같은 그래프 데이터베이스를 통해 구현되며, Cypher라는 쿼리 언어를 사용해 복잡한 관계를 검색할 수 있다. 지식 그래프는 데이터를 구조화하고 관계를 강조하며, 노드와 엣지 모두 속성을 가질 수 있어 풍부한 정보 표현이 가능하다."
published: 2024-08-15
modified: 2024-08-15
---
## 개요

지식 그래프(Knowledge Graph)는 RAG(Retrieval-Augmented Generation) 시스템에서 정보 검색과 컨텍스트 제공을 향상시키는 데 활용되는 강력한 도구다. 이 문서에서는 지식 그래프의 기본 개념과 Neo4j를 활용한 구현 방법에 대해 알아본다.

### 참고자료
- [DeepLearning.AI - Knowledge Graphs for RAG](https://learn.deeplearning.ai/courses/knowledge-graphs-rag/lesson/1/introduction)

## 지식 그래프란?

지식 그래프는 노드(nodes)와 관계(relationships)를 사용하여 정보를 저장하는 데이터베이스다.

주요 특징:
- 데이터 정렬 및 구성 방법 제공
- 개체 간의 관계 강조
- 그래프 기반 구조 사용:
  - 노드: 개체(entity) 표현
  - 엣지: 노드 간의 관계 표현

![지식 그래프 예시](https://i.imgur.com/v3dXFGn.png)

## 기본 개념

### 노드와 엣지

노드와 엣지는 지식 그래프의 기본 구성 요소다.

![노드와 엣지 예시](https://i.imgur.com/aqQtqhM.png)

표현 방식: (Person) - [Knows] - (Person)

> 노드는 관계 내에 있으며, 속성을 갖는 관계로 연결된다.

![복잡한 관계 예시](https://i.imgur.com/Kmhm0zd.png)

표현 방식: (Person) - [TEACHES] → (Course) ← [INTRODUCES] - (Person)

![엣지 속성 예시](https://i.imgur.com/bOdx0b4.png)

노드와 마찬가지로 엣지도 키/값 구조를 가질 수 있다.

**지식 그래프 개요:**

- 지식 그래프: 노드와 관계로 정보 저장
- 노드와 관계: 둘 다 속성을 가질 수 있음
- 노드: 라벨을 붙여 그룹화 가능
- 관계: 항상 타입과 방향을 가짐

## 지식 그래프 쿼리

지식 그래프를 쿼리하기 위해 Neo4jGraph를 사용할 수 있다.

```python
from langchain_community.graphs import Neo4jGraph

kg = Neo4jGraph(
    url=NEO4J_URI, username=NEO4J_USERNAME, password=NEO4J_PASSWORD, database=NEO4J_DATABASE
)
```

![그래프 구조 예시](https://i.imgur.com/cutLMPA.png)

(Person) - [ACTED_IN] → (Movie)

### 노드 속성

노드는 다양한 속성을 가질 수 있다.

![노드 속성 예시](https://i.imgur.com/A0EADne.png)

### 엣지-영화와 인물 간의 관계

엣지는 노드 간의 관계를 표현한다.

![엣지 관계 예시](https://i.imgur.com/nqVR5Jg.png)

이를 통해 한 사람이 영화에 출연하고 감독도 한 것과 같은 복잡한 상황을 설명할 수 있다.

### Cypher 쿼리 언어

Cypher는 Neo4j의 쿼리 언어로, 패턴 매칭을 사용하여 그래프 내의 정보를 검색한다.

#### 기본 쿼리

모든 노드의 수를 계산하는 쿼리:

```python
# 모든 노드의 수
cypher = """
  MATCH (n) 
  RETURN count(n)
  """
```

```python
result = kg.query(cypher)
result
```

결과:
```
[{'count(n)': 171}]
```

#### 별칭 사용

결과에 별칭을 부여하는 방법:

```python
cypher = """
  MATCH (n) 
  RETURN count(n) AS numberOfNodes
  """
result = kg.query(cypher)
result
```

결과:
```
[{'numberOfNodes': 171}]
```

결과 활용:
```python
print(f"There are {result[0]['numberOfNodes']} nodes in this graph.")
```

출력:
```
There are 171 nodes in this graph.
```

#### 패턴 매칭

특정 라벨을 가진 노드 검색:

```python
cypher = """
  MATCH (n:Movie) 
  RETURN count(n) AS numberOfMovies
  """
kg.query(cypher)
```

결과:
```
[{'numberOfMovies': 38}]
```

속성을 가진 특정 노드 검색:

```python
cypher = """
  MATCH (tom:Person {name:"Tom Hanks"}) 
  RETURN tom
  """
kg.query(cypher)
```

결과:
```
[{'tom': {'born': 1956, 'name': 'Tom Hanks'}}]
```

## RAG에서의 지식 그래프 활용

지식 그래프는 RAG 시스템에서 다음과 같은 이점을 제공한다:

1. **구조화된 정보 검색**: 단순 키워드 검색이 아닌 관계 기반 검색 가능
2. **컨텍스트 강화**: 관련 개체와 관계 정보를 통해 LLM에 더 풍부한 컨텍스트 제공
3. **추론 지원**: 그래프 구조를 통해 복잡한 추론 작업 지원

## 결론

지식 그래프는 RAG 시스템에서 정보 검색과 컨텍스트 제공을 향상시키는 강력한 도구다. Neo4j와 같은 그래프 데이터베이스와 Cypher 쿼리 언어를 활용하면 복잡한 관계를 효과적으로 모델링하고 검색할 수 있다.

관련 문서로는 [[LLM Chain Chatbot + RAG]], [[RAG+Groq]], [[Agent 사용 RAG+Tavily]]를 참조하자. 