# Project Page Structure

## Overview
프로젝트 페이지는 타임라인 형식의 메인 페이지와 각 프로젝트별 디테일 페이지로 구성되어 있습니다.

## 구조

### 1. 메인 프로젝트 페이지 (`/projects`)
- **컴포넌트**: `components/project-timeline.tsx`
- **데이터 소스**: `data/projects.ts` - `projectsTimeline` 배열
- **특징**:
  - 타임라인 형식으로 프로젝트 표시
  - 애니메이션 효과 (framer-motion)
  - 각 프로젝트 카드 클릭 시 상세 정보 확장
  - "자세히 보기" 버튼으로 디테일 페이지 이동

### 2. 프로젝트 디테일 페이지 (`/projects/[projectId]`)
- **라우트**: Next.js 동적 라우트 사용
- **컴포넌트**: `components/project-detail-template.tsx` (재사용 가능한 템플릿)
- **데이터 소스**: `data/projects.ts` - `projectsDetail` 객체
- **특징**:
  - SEO 최적화 (generateMetadata)
  - 정적 생성 (generateStaticParams)
  - 일관된 레이아웃 및 섹션 구조

## 새 프로젝트 추가하기

### Step 1: 타임라인 데이터 추가
`data/projects.ts` 파일의 `projectsTimeline` 배열에 새 프로젝트를 추가합니다:

```typescript
{
  id: "project-id",  // URL에 사용될 고유 ID
  title: "프로젝트 제목",
  period: "2024.01 ~ 2024.06",
  year: 2024,
  periodType: "H",  // "Q" (Quarter) 또는 "H" (Half)
  periodNumber: 1,   // 1 또는 2
  isCompleted: true, // 완료 여부
  description: "프로젝트 간단한 설명",
  tags: ["Tech1", "Tech2", "Tech3"]
}
```

### Step 2: 디테일 데이터 추가
같은 파일의 `projectsDetail` 객체에 상세 정보를 추가합니다:

```typescript
"project-id": {
  id: "project-id",  // Step 1의 ID와 동일해야 함
  title: "프로젝트 제목",
  subtitle: "부제목",
  period: "2024.01 ~ 2024.06",
  duration: "약 6개월",
  role: "역할",
  team: "팀 구성",
  description: "상세 설명",
  techStack: {
    backend: ["기술1", "기술2"],
    frontend: ["기술3", "기술4"],
    // ... 더 많은 카테고리
  },
  // 선택적 섹션들:
  achievements: ["성과1", "성과2"],
  keyFeatures: [
    {
      title: "기능 제목",
      details: ["상세1", "상세2"]
    }
  ],
  challenges: [
    {
      title: "도전 과제",
      description: "설명"
    }
  ],
  learnings: ["배운점1", "배운점2"]
}
```

### Step 3: 빌드 및 확인
```bash
npm run build
npm run dev
```

새 프로젝트가 자동으로:
- 타임라인에 표시됨
- `/projects/[project-id]` 경로로 접근 가능
- 정적 페이지로 생성됨 (SSG)

## 지원하는 섹션들

### 필수 섹션
- 프로젝트 기본 정보 (제목, 기간, 역할, 팀)
- 설명
- 기술 스택

### 선택적 섹션
- `achievements`: 주요 성과 (문자열 배열 또는 메트릭 객체 배열)
- `architectureEvolution`: 아키텍처 진화 과정
- `keyResponsibilities`: 담당 업무
- `keyFeatures`: 주요 기능
- `businessGoals`: 비즈니스 목표
- `challenges`: 도전 과제 및 극복
- `learnings`: 배운 점 및 성장

## 파일 구조

```
/workspace
├── app/
│   └── projects/
│       ├── page.tsx                    # 메인 프로젝트 페이지
│       └── [projectId]/
│           └── page.tsx                # 동적 디테일 페이지
├── components/
│   ├── project-timeline.tsx            # 타임라인 컴포넌트
│   └── project-detail-template.tsx     # 재사용 가능한 디테일 템플릿
└── data/
    └── projects.ts                     # 모든 프로젝트 데이터
```

## 스타일링
- Tailwind CSS 사용
- shadcn/ui 컴포넌트 활용
- 다크 모드 지원
- 반응형 디자인

## 애니메이션
- framer-motion 사용
- 페이드 인/아웃 효과
- 스무스한 확장/축소
- 호버 효과
