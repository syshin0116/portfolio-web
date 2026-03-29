# 변경 사항

## 2025-12-25 - SYS-19: RAG Mode Multi-Select

### RAG 모드 선택 UI 개선
- 4개의 개별 버튼을 하나의 multi-select toggle group으로 통합
- 사용자가 여러 RAG 모드를 동시에 선택 가능
- shadcn 공식 컴포넌트 사용 (Toggle, ToggleGroup)

### 기술적 변경사항
- `@radix-ui/react-toggle` 및 `@radix-ui/react-toggle-group` 추가
- `components/ui/toggle.tsx` 생성 - shadcn Toggle 컴포넌트
- `components/ui/toggle-group.tsx` 생성 - shadcn ToggleGroup 컴포넌트
- `components/chat-section.tsx` 업데이트:
  - `ragSettings` 객체 → `selectedRagModes` 배열로 상태 관리 변경
  - 4개의 개별 Button → 1개의 ToggleGroup + 4개의 ToggleGroupItem으로 변경
  - `toggleRagSetting` 함수 제거 (더 이상 필요 없음)

### RAG 모드
1. Metadata Search (블로그 메타데이터 검색)
2. Filesystem Search (파일시스템 기반 검색)
3. Vector Search (임베딩 벡터 검색)
4. Graph Search (그래프 기반 검색)

### 빌드 결과
```
✅ 빌드 성공
✅ 린터 에러 없음 (기존 경고만 존재)
✅ TypeScript 컴파일 성공
```

---

## 2025-12-08 - 프로젝트 구조 개선

## 주요 변경사항

### 1. Blog RAG 챗봇 → AppHub로 통합
- `blog-rag-chatbot` 프로젝트를 `apphub`으로 통합
- AppHub가 2023년 9월 Blog RAG 챗봇으로 시작하여 Living Portfolio 플랫폼으로 발전한 스토리 반영
- 기간: 2023.09 ~ 진행 중 (약 2년 3개월)
- Phase 1 (Blog RAG 챗봇)과 Phase 2 (플랫폼화)로 구조화

### 2. 진행 중인 프로젝트 우선 표시
- 타임라인에서 진행 중인 프로젝트를 최상단에 배치
- 순서:
  1. AppHub (개인, 진행 중)
  2. SK PharmaAIX (회사, 진행 중)
  3. 한국자동차연구원 (회사, 진행 중)
  4. PodlyBot (개인, 진행 중)
  5. LabQ Bot (회사, 진행 중)
  6. 완료된 프로젝트들 (최신순)

### 3. 회사/개인 프로젝트 명확한 구별
- `category` 필드 추가: "company" | "personal"
- 카드에 회사/개인 뱃지 표시 (Briefcase/User 아이콘)
- 회사 프로젝트: 파란색 뱃지
- 개인 프로젝트: 아웃라인 뱃지

### 4. NavBar 단순화
- 프로젝트 드롭다운 제거 (12개 프로젝트로 너무 많음)
- Home, Projects, Blog 단순 링크로 변경
- 모바일 메뉴도 Accordion 제거하고 단순화

### 5. 프로젝트 카드 UX 개선
- 카드 클릭 시 바로 상세 페이지로 이동
- Description을 제목 바로 아래에 기본으로 표시
- 확장/축소 기능 제거 (불필요한 클릭 단계 제거)
- 호버 시 scale 효과로 클릭 가능함을 명확히 표시

## 프로젝트 개수
- **이전**: 13개 (blog-rag-chatbot 별도)
- **현재**: 12개 (AppHub로 통합)

## 기술적 변경사항
- `ProjectTimeline` 인터페이스에 `category` 필드 추가
- `project-timeline.tsx` 컴포넌트 리팩토링
  - 확장/축소 상태 관리 제거
  - 카드 전체를 Link로 감싸서 클릭 시 이동
  - 회사/개인 뱃지 추가
- `navbar.tsx` 단순화
  - 프로젝트 드롭다운 관련 코드 제거
  - 불필요한 import 제거
  - ListItem 컴포넌트 제거

## 빌드 결과
```
✅ 빌드 성공
✅ 린터 에러 없음
✅ 12개 프로젝트 정적 페이지 생성 완료
✅ 타입 체크 통과
```

## 프로젝트 분류

### 회사 프로젝트 (6개)
1. SK PharmaAIX MR Assistant (진행 중)
2. 한국자동차연구원 AI 에이전트 (진행 중)
3. LabQ Bot - 회사 카카오톡 챗봇 (진행 중)
4. 그린텍 하수처리 수질 예측 AI (완료)
5. 네이버 부스트캠프 기업 해커톤 (완료)
6. PROP - 제안서 작성 AI Agent (완료)

### 개인 프로젝트 (6개)
1. AppHub - Living Portfolio 플랫폼 (진행 중)
2. PodlyBot - 카카오톡 LLM 챗봇 (진행 중)
3. LangChain Open Tutorial 기여 (완료)
4. Podly - AI 음성 뉴스 서비스 (완료)
5. 고용노동 공공데이터 활용 공모전 (완료)
6. Men-in-Black - 교통 법규 위반 감지 (완료)

## 사용자 경험 개선
1. **타임라인**: 진행 중인 프로젝트를 먼저 볼 수 있어 현재 작업 상황 파악 용이
2. **카드 클릭**: 불필요한 클릭 단계 제거로 더 빠른 네비게이션
3. **회사/개인 구별**: 뱃지로 한눈에 프로젝트 성격 파악 가능
4. **NavBar**: 단순한 구조로 더 나은 사용성
5. **Description 표시**: 확장하지 않아도 프로젝트 개요 즉시 확인 가능
