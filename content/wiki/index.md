# Wiki Index

## All pages

| Page | Summary | Type | Tags | Sources | Updated |
|------|---------|------|------|---------|---------|
| [[cli-ux-design]] | CLI 도구의 사용성은 기능 추가가 아니라 출력 계약과 동작 규칙의 설계 문제다. TTY 감지, 출력 스키마 안정성, exit code 분리로 인간과 에이전트 모두가 예측 가능하게 쓸 수 있는 도구가 된다. | pattern | cli, rust, backend, ai-agent, ux, api-design, unix, pattern | 1 | 2026-04-26 |
| [[clidex]] | AI 에이전트와 인간 모두를 위한 CLI 도구 발견 도구. Rust 구현 BM25 엔진, 5,277개 인덱스 대상 퍼지 매칭·동의어 확장·edit distance 오타 교정, TTY 감지 기반 출력 자동 전환. | tool | cli, rust, ai, ai-agent, bm25, search, fuzzy-search, edit-distance, testing | 2 | 2026-04-26 |
| [[llm-text-to-sql]] | DB 스키마 품질이 Text-to-SQL 정확도의 결정적 요소다. 동적 스키마 조회, COMMENT 기반 zero-shot, AST 검증 보안 레이어, 에이전트 위임 self-correction을 조합해 OLTP 수준 질의에서 높은 정확도를 달성한다. | pattern | text-to-sql, llm, ai, agent, postgresql, prompt-engineering, evaluation, security | 1 | 2026-04-26 |
| [[misen]] | dict→dict Block 단일 인터페이스와 연산자 조합으로 AI 워크플로우를 플랫폼 독립적으로 구성하는 Python 라이브러리. 조합 결과도 Block이므로 중첩 재사용 가능(닫힘 성질). | tool | python, ai, llm, pipeline, workflow, open-source, library, agent, operator | 1 | 2026-04-26 |
| [[블로그-검색-실험]] | 280개 한국어+영어 혼용 블로그 포스트를 테스트베드로 6가지 검색 방법의 성능을 비교하는 실험 시리즈. 한국어 형태소 분석, 다국어 임베딩 모델, 하이브리드 퓨전 전략이 핵심 변수. | reference | rag, ai, embeddings, bm25, search, vector-search, hybrid-search, korean, experiment, evaluation | 1 | 2026-04-26 |

## Sources catalog

| Source | Wiki pages |
|--------|------------|
| content/AI/2026-04-19-LLM-Text-to-SQL-실전-가이드.md | [[llm-text-to-sql]] |
| content/AI/2026-04-04-블로그-검색-실험-1-실험설계.md | [[블로그-검색-실험]] |
| content/Projects/Clidex/03-Search-Quality-Hardening.md | [[clidex]] |
| content/Projects/Clidex/04-CLI-UX-Design.md | [[clidex]], [[cli-ux-design]] |
| content/Projects/misen/2026-04-04-misen-overview.md | [[misen]] |
