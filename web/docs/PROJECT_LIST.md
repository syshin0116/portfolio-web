# 프로젝트 목록

총 **13개 프로젝트**가 구현되어 있습니다.

## 랩큐 프로젝트 (6개)

### 1. SK PharmaAIX MR Assistant
- **기간**: 2024.07 ~ 현재 (진행 중)
- **역할**: AI 파트 리드 / 랩큐 팀 PL
- **주요 기술**: LangGraph, Multi-Agent, Qdrant, FastAPI
- **성과**: 응답 속도 83% 개선, 답변 커버리지 233% 향상, 만족도 99%
- **URL**: `/projects/sk-pharmaaix`

### 2. 한국자동차연구원 AI 에이전트
- **기간**: 2024.03 ~ 2024.11 (1년 8개월)
- **역할**: 1~2차 1인 풀스택, 3~4차 메인 PL
- **주요 기술**: Next.js, FastAPI, LangGraph, Qdrant, Keycloak SSO
- **성과**: 보고서 작성 시간 98% 단축 (1시간 → 1분)
- **URL**: `/projects/katech-ai-agent`

### 3. 그린텍 하수처리 수질 예측 AI
- **기간**: 2024.07 ~ 2024.11
- **역할**: PL (팀 2명)
- **주요 기술**: LightGBM, XGBoost, PyTorch, PyOD
- **성과**: 19개 타겟 변수 예측 모델 구축, 이상 탐지 98.5% 정확도
- **URL**: `/projects/greentech`

### 4. PROP - 제안서 작성 AI Agent
- **기간**: 2024.03 ~ 2024.04
- **역할**: 유지보수 및 추가 개발
- **주요 기술**: Flask, Celery, OpenAI API
- **성과**: GPT-4/GPT-4o 업그레이드, 비동기 처리 개선
- **URL**: `/projects/prop`

### 5. 네이버 부스트캠프 기업 해커톤
- **기간**: 2025.01 ~ 2025.02
- **역할**: 기획, 운영, 평가
- **주요 기술**: 챗봇, RAG, 멘토링
- **성과**: 해커톤 과제 기획 및 참가 팀 멘토링
- **URL**: `/projects/naver-hackathon`

### 6. SK Chemical AI/ML 프로젝트 (계획 중)
- Copoly CP-3 ES-20 COOH 예측
- QA팀 이미지 선별 모델 (Computer Vision)

---

## 개인 프로젝트 (7개)

### 1. AppHub - Living Portfolio 플랫폼
- **기간**: 2025.10 ~ 진행 중
- **역할**: 1인 풀스택 개발
- **주요 기술**: React 19, Next.js 15, FastAPI, Qdrant, Neo4j
- **특징**: 실제 동작하는 프로젝트 통합 관리, SSO, 통합 AI 백엔드
- **URL**: `/projects/apphub`

### 2. LangChain Open Tutorial 오픈소스 기여
- **기간**: 2025.01 ~ 2025.02
- **역할**: 오픈소스 컨트리뷰터
- **주요 기술**: LangChain, LangGraph, RAG
- **성과**: 2,000+ 커밋 프로젝트 기여, 3개 튜토리얼 작성
- **URL**: `/projects/langchain-tutorial`

### 3. Men-in-Black - 교통 법규 위반 감지
- **기간**: 2023.10 ~ 2023.12
- **역할**: License Plate Recognition 및 Depth Estimation 담당
- **주요 기술**: YOLOv8, EasyOCR, ZoeDepth, PyTorch
- **성과**: 차량 감지, 번호판 인식, 거리 추정 통합 시스템
- **URL**: `/projects/men-in-black`

### 4. Podly - AI 음성 뉴스 서비스
- **기간**: 2024.08 ~ 2024.09
- **역할**: 팀장 / AI 및 백엔드 개발
- **주요 기술**: RAG, Whisper, TTS, Flutter
- **성과**: 터치 없는 음성 인터페이스, 맞춤형 뉴스 큐레이션
- **URL**: `/projects/podly`

### 5. 고용노동 공공데이터 활용 공모전
- **기간**: 2024.06
- **역할**: 팀장
- **주요 기술**: Pandas, Plotly, 데이터 시각화
- **성과**: 인터랙티브 대시보드 구축, 고용 트렌드 분석
- **URL**: `/projects/employment-data`

### 6. PodlyBot - 카카오톡 LLM 챗봇
- **기간**: 2024.09 ~ 현재 (운영 중)
- **역할**: 1인 개발
- **주요 기술**: 메신저봇R, LLM API, Notion API
- **성과**: URL 요약 및 Notion 자동 정리, 24/7 운영
- **URL**: `/projects/podlybot`

### 7. LabQ Bot - 회사 카카오톡 챗봇
- **기간**: 2024.09 ~ 현재 (운영 중)
- **역할**: 1인 개발
- **주요 기술**: 메신저봇R, 회사 LLM 서비스, Notion API
- **성과**: 고객사 테스트 환경 제공, 회사 지식 관리 자동화
- **URL**: `/projects/labq-bot`

### 8. Blog RAG 챗봇
- **기간**: 2023.09 ~ 2023.12
- **역할**: 1인 개발
- **주요 기술**: LangChain, ChromaDB, FastAPI
- **성과**: 블로그 콘텐츠 100% 벡터화, 평균 응답 시간 2초
- **URL**: `/projects/blog-rag-chatbot`

---

## 기술 스택 요약

### AI/ML
- **LLM**: OpenAI GPT, Azure OpenAI, Claude, Upstage Solar, Gemma2, Phi, Llama
- **프레임워크**: LangChain, LangGraph
- **아키텍처**: RAG, Multi-Agent Supervisor, Chain + Agentic 하이브리드
- **Vector DB**: Qdrant, ChromaDB, LanceDB
- **ML/DL**: PyTorch, TensorFlow, LightGBM, XGBoost, CatBoost
- **Computer Vision**: YOLOv8, EasyOCR, ZoeDepth

### Backend
- **프레임워크**: FastAPI, Flask
- **작업 큐**: Celery, Redis
- **데이터베이스**: PostgreSQL, MariaDB, MySQL, Neo4j
- **ORM**: Drizzle, Kysely

### Frontend
- **프레임워크**: Next.js 15, React 19, Flutter
- **언어**: TypeScript, JavaScript
- **UI**: BlockNote Editor, Streamlit
- **상태 관리**: Zustand

### Infrastructure
- **컨테이너**: Docker, Docker Compose
- **서버**: Nginx, Linux Server, Gunicorn
- **클라우드**: Azure, AWS, GCP, Vercel, Railway, Fly.io
- **인증**: Keycloak (SSO), better-auth, OAuth 2.0
- **모니터링**: LangSmith, DataDog

### Development Tools
- **패키지 매니저**: Bun, npm
- **린팅**: Biome, ESLint
- **버전 관리**: Git, GitHub
- **협업**: Jira, Confluence, Slack, Notion

---

## 프로젝트 역할 분포

### 리더십 경험
- **AI 파트 리드**: SK PharmaAIX (BCG RA 15명 + 랩큐 팀 3명 리딩)
- **PL (Project Leader)**: 한국자동차연구원 (3명 팀), 그린텍 (2명 팀)
- **팀장**: Podly (4명 팀), 고용노동 공모전

### 개발 역할
- **1인 풀스택**: 한국자동차연구원 (1~2차, 7개월), AppHub, PodlyBot, LabQ Bot
- **AI/ML 개발자**: SK PharmaAIX, 그린텍, Men-in-Black
- **오픈소스 기여자**: LangChain Open Tutorial

### 멘토링 및 기획
- **멘토**: 네이버 부스트캠프
- **유지보수**: PROP

---

## 주요 성과

### 성능 개선
- **SK PharmaAIX**: 응답 속도 83% 개선, 답변 커버리지 233% 향상, 만족도 99%
- **한국자동차연구원**: 보고서 작성 시간 98% 단축 (1시간 → 1분)
- **그린텍**: 이상 탐지 98.5% 정확도, 19개 타겟 변수 예측 모델

### 오픈소스 기여
- **LangChain Open Tutorial**: 2,000+ 커밋 프로젝트 기여, 3개 튜토리얼 작성

### 운영 중인 서비스
- **PodlyBot**: 개인 비서 챗봇 24/7 운영
- **LabQ Bot**: 회사 업무용 챗봇 운영
- **AppHub**: Living Portfolio 플랫폼 구축 중

---

## 접근 방법

### 타임라인 페이지
- URL: `/projects`
- 시간순으로 모든 프로젝트 표시
- 애니메이션 효과 및 인터랙티브 카드
- "자세히 보기" 버튼으로 디테일 페이지 이동

### 개별 프로젝트 페이지
- URL: `/projects/[projectId]`
- 재사용 가능한 템플릿 구조
- SEO 최적화 (메타데이터 자동 생성)
- 정적 생성 (SSG)

### 새 프로젝트 추가
`data/projects.ts` 파일에 데이터만 추가하면 자동으로 페이지 생성됩니다.
