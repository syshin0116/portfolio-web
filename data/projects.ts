export interface ProjectTimeline {
  id: string;
  title: string;
  period: string;
  year: number;
  periodType: "Q" | "H";
  periodNumber: number;
  isCompleted: boolean;
  description: string;
  tags: string[];
  category: "company" | "personal";
  company?: string;
  github?: string;
  demo?: string; // 배포된 사이트 URL
}

export interface ProjectDetail {
  id: string;
  title: string;
  subtitle: string;
  period: string;
  duration: string;
  role: string;
  team: string;
  description: string;
  github?: string;
  demo?: string;
  blogPost?: string; // 블로그 Overview 글 경로 (e.g. "/blog/Projects/Nuartz/00-Overview")
  package?: {
    registry: string; // "npm" | "crates.io" | "pypi" etc.
    name: string;
    url: string;
  };
  demoImage?: {
    url: string;
    alt: string;
  };
  techStack: {
    [key: string]: string[];
  };
  achievements?: (string | {
    metric: string;
    before: string;
    after: string;
    improvement: string;
  })[];
  keyFeatures?: {
    title: string;
    details: string[];
  }[];
  keyResponsibilities?: {
    title: string;
    details: string[];
  }[];
  businessGoals?: {
    title: string;
    description?: string;
    items?: string[];
  }[];
  architectureEvolution?: {
    version: string;
    title: string;
    problems?: string[];
    changes?: string[];
    results?: string[];
  }[];
  challenges?: {
    title: string;
    description: string;
  }[];
  learnings?: string[];
}

// Timeline data for the main projects page
export const projectsTimeline: ProjectTimeline[] = [
  // 진행 중인 프로젝트 (최신순)
  {
    id: "clidex",
    title: "Clidex - AI 에이전트를 위한 CLI 도구 검색",
    period: "2026.03 ~ 진행 중",
    year: 2026,
    periodType: "Q",
    periodNumber: 1,
    isCompleted: false,
    description: "AI 에이전트가 CLI 도구를 검색·비교·설치할 수 있는 인덱스. BM25 + 시노님 확장으로 21개 쿼리 기준 100% recall 달성. Rust로 구현.",
    tags: ["오픈소스", "Rust", "CLI", "AI Agent", "BM25"],
    category: "personal",
    github: "https://github.com/syshin0116/clidex"
  },
  {
    id: "syshin0116-dev",
    title: "Syshin0116.dev - 블로그 + 포트폴리오 통합",
    period: "2026.03 ~ 진행 중",
    year: 2026,
    periodType: "Q",
    periodNumber: 1,
    isCompleted: false,
    description: "Nuartz 기반 블로그와 포트폴리오를 하나의 사이트로 통합. 4개 레포를 3개로 재편하고 blog-rag(Modular RAG) 백엔드와 연동 계획.",
    tags: ["Full Stack", "Next.js 15", "Nuartz", "포트폴리오"],
    category: "personal",
    github: "https://github.com/syshin0116/syshin0116.dev",
    demo: "https://syshin0116.vercel.app"
  },
  {
    id: "nuartz",
    title: "Nuartz - Obsidian → Next.js 오픈소스 라이브러리",
    period: "2026.03 ~ 진행 중",
    year: 2026,
    periodType: "Q",
    periodNumber: 1,
    isCompleted: false,
    description: "Obsidian 볼트를 Next.js 웹사이트로 퍼블리싱하는 headless 라이브러리. 위키링크, 백링크, 그래프뷰, 검색 등 Obsidian 기능을 Next.js에서 구현. npm 패키지로 배포.",
    tags: ["오픈소스", "Next.js 15", "TypeScript", "Obsidian", "npm"],
    category: "personal",
    github: "https://github.com/syshin0116/nuartz",
    demo: "https://nuartz.vercel.app"
  },
  {
    id: "sk-pharmaaix",
    title: "MR Assistant - 제약 영업 지원 AI 챗봇",
    period: "2025.07 ~ 2026.02",
    year: 2025,
    periodType: "H",
    periodNumber: 2,
    isCompleted: true,
    description: "대형 제약 그룹 MR 약 350명을 위한 RAG 기반 질의응답 시스템",
    tags: ["AI/ML", "LangGraph", "FastAPI", "Azure"],
    category: "company",
    company: "LabQ"
  },
  {
    id: "katech-ai-agent",
    title: "자동차 지식 에이전트 - 보고서 자동 생성 AI",
    period: "2024.03 ~ 2026.02",
    year: 2024,
    periodType: "H",
    periodNumber: 1,
    isCompleted: true,
    description: "국내 자동차 연구기관의 RAG 기반 보고서 자동 생성 시스템 및 챗봇",
    tags: ["Full Stack", "RAG", "Next.js", "FastAPI"],
    category: "company",
    company: "LabQ"
  },

  // SK Chemical AI/ML 프로젝트
  {
    id: "sk-cooh-prediction",
    title: "Copolyester COOH 예측 모델",
    period: "2025 (SK Chemical)",
    year: 2025,
    periodType: "H",
    periodNumber: 1,
    isCompleted: true,
    description: "ES-20 COOH 변화 예측으로 온도/유량 사전 Action 가능, Polymer 반응성 안정 운전 지원",
    tags: ["AI/ML", "Python", "LightGBM", "XGBoost", "시계열"],
    category: "company",
    company: "SK Chemical"
  },
  {
    id: "sk-qa-image-classification",
    title: "이미지 선별 모델 - 이물 분석 검출 지원",
    period: "2025.02 ~ 2025.04",
    year: 2025,
    periodType: "Q",
    periodNumber: 1,
    isCompleted: true,
    description: "PET Chip 이물 이미지 자동 선별 모델로 QA팀 업무 Load 감소",
    tags: ["Computer Vision", "Python", "이미지 분류", "PDF 처리"],
    category: "company",
    company: "SK Chemical"
  },

  // 완료된 프로젝트 (최신순)
  {
    id: "naver-hackathon",
    title: "네이버 부스트캠프 기업 해커톤",
    period: "2025.01 ~ 2025.02",
    year: 2025,
    periodType: "Q",
    periodNumber: 1,
    isCompleted: true,
    description: "기업 평가 챗봇 개발 해커톤 기획 및 운영",
    tags: ["해커톤", "멘토링", "챗봇"],
    category: "company",
    company: "LabQ"
  },
  {
    id: "langchain-tutorial",
    title: "LangChain Open Tutorial",
    period: "2025.01 ~ 2025.02",
    year: 2025,
    periodType: "Q",
    periodNumber: 1,
    isCompleted: true,
    description: "2,000+ 커밋 오픈소스 프로젝트에 RAG 튜토리얼 작성",
    tags: ["오픈소스", "LangChain", "RAG", "LangGraph"],
    category: "personal",
    github: "https://github.com/LangChain-OpenTutorial/LangChain-OpenTutorial"
  },
  {
    id: "greentech",
    title: "그린텍 하수처리 수질 예측 AI",
    period: "2024.07 ~ 2024.11",
    year: 2024,
    periodType: "H",
    periodNumber: 2,
    isCompleted: true,
    description: "하수처리 공정 수질 예측 및 이상탐지 AI 시스템",
    tags: ["AI/ML", "LightGBM", "PyTorch", "Time Series"],
    category: "company",
    company: "LabQ"
  },
  {
    id: "podlybot",
    title: "PodlyBot - 카카오톡 LLM 챗봇",
    period: "2024.09",
    year: 2024,
    periodType: "H",
    periodNumber: 2,
    isCompleted: true,
    description: "개인 비서 & 회사 업무용 LLM 챗봇 - URL 요약, Notion 자동 정리, 회사 LLM 서비스 연동",
    tags: ["챗봇", "LLM", "Notion API", "JavaScript"],
    category: "personal"
  },
  {
    id: "podly",
    title: "Podly - AI 음성 뉴스 서비스",
    period: "2024.08 ~ 2024.09",
    year: 2024,
    periodType: "H",
    periodNumber: 2,
    isCompleted: true,
    description: "AI 기반 맞춤형 음성 뉴스 및 관심사 정보 제공 서비스",
    tags: ["AI/ML", "RAG", "TTS", "Flutter"],
    category: "personal"
  },
  {
    id: "employment-data",
    title: "고용노동 공공데이터 활용 공모전",
    period: "2024.06",
    year: 2024,
    periodType: "H",
    periodNumber: 1,
    isCompleted: true,
    description: "고용노동 공공데이터 분석 및 Plotly 시각화",
    tags: ["데이터 분석", "Plotly", "Python"],
    category: "personal"
  },
  {
    id: "prop",
    title: "PROP - 제안서 작성 AI Agent",
    period: "2024.03 ~ 2024.04",
    year: 2024,
    periodType: "Q",
    periodNumber: 1,
    isCompleted: true,
    description: "제안서 및 문서 생성 자동화 시스템",
    tags: ["AI/ML", "OpenAI API", "Flask"],
    category: "company",
    company: "LabQ"
  },
  {
    id: "men-in-black",
    title: "Men-in-Black - 교통 법규 위반 감지",
    period: "2023.10 ~ 2023.12",
    year: 2023,
    periodType: "H",
    periodNumber: 2,
    isCompleted: true,
    description: "블랙박스 영상 속 교통 법규 위반 차량 감지 시스템",
    tags: ["Computer Vision", "YOLOv8", "OCR", "PyTorch"],
    category: "personal"
  },
];

// Detailed project data for individual project pages
export const projectsDetail: { [key: string]: ProjectDetail } = {
  "sk-pharmaaix": {
    id: "sk-pharmaaix",
    title: "MR Assistant - 제약 영업 지원 AI 챗봇",
    subtitle: "대형 제약 그룹 MR 영업 지원",
    period: "2025.07 ~ 2026.02",
    duration: "약 7개월",
    role: "AI 파트 리드 / 팀 PL",
    team: "팀원 3명 + 글로벌 컨설팅사 RA 5~6명 리딩",
    description: "대형 제약 그룹의 MR 약 350명을 위한 AI 챗봇. 영업활동 기록, 제품 정보 검색, 고성과자 노하우 공유를 통한 성과 향상 지원. 제약 도메인 특화 RAG 기반 질의응답 시스템.",
    techStack: {
      backend: ["FastAPI", "Python"],
      database: ["MariaDB", "Qdrant (Vector DB)", "AWS Redshift", "Redis"],
      aiml: ["LangChain", "LangGraph", "Azure OpenAI API"],
      infrastructure: ["Azure", "Docker"],
      collaboration: ["Slack", "Jira", "Confluence"]
    },
    businessGoals: [
      {
        title: "생산성 향상 목표",
        description: "MR 인당 생산성 11% 향상 (컨설팅사 예상치)"
      },
      {
        title: "4R 전략",
        items: [
          "Right Target: 적절한 타겟 고객 식별 및 추천",
          "Right Product: 고객 상황에 맞는 적절한 제품 추천",
          "Right Message: 효과적인 메시지 전달 전략 제공",
          "Right Timing: 최적의 타이밍 제안"
        ]
      }
    ],
    achievements: [
      {
        metric: "응답 속도",
        before: "평균 3분 이상",
        after: "평균 30초",
        improvement: "83% 개선"
      },
      {
        metric: "답변 커버리지",
        before: "30%",
        after: "100%",
        improvement: "233% 향상"
      },
      {
        metric: "답변 품질",
        before: "-",
        after: "99% 만족도",
        improvement: "AIX팀 정성 평가"
      }
    ],
    architectureEvolution: [
      {
        version: "V1",
        title: "완전 Chain 방식",
        problems: [
          "Orchestrator + Chain 방식으로 지나치게 지엽적",
          "설계된 specific한 질문만 답변 가능",
          "대부분의 실제 사용자 질의에 대답 불가",
          "응답 속도 3분 이상, 커버리지 30% 수준"
        ]
      },
      {
        version: "V2",
        title: "Multi-Agent Supervisor 전환",
        changes: [
          "Agentic Supervisor Multi-Agent 아키텍처로 전환",
          "Supervisor가 사용자 질문 분석 후 적절한 Agent 호출"
        ],
        problems: [
          "많은 개발자들이 설계 의도대로 구현하지 못함",
          "아키텍처 이해도 부족으로 인한 구현 오류"
        ]
      },
      {
        version: "V3",
        title: "완전 재설계",
        changes: [
          "Agent 구조, init, tool까지 직접 제작하여 배포",
          "개발자들이 그대로 사용할 수 있도록 완성된 형태로 제공",
          "Chain + Agentic 하이브리드 구조"
        ],
        results: [
          "응답 속도 83% 개선 (3분 → 30초)",
          "답변 커버리지 233% 향상 (30% → 100%)",
          "답변 품질 99% 만족도 달성"
        ]
      }
    ],
    keyResponsibilities: [
      {
        title: "AI 파트 리딩 및 멀티 팀 협업",
        details: [
          "컨설팅사 PM 다음으로 AI 파트 전체 리더 역할",
          "컨설팅사 RA 5~6명 (3개월 로테이션, 총 15명) 업무 분담 및 관리",
          "팀원 3명 PL 역할 (요구사항 분석, 일정 관리, 코드 리뷰)",
          "추진팀, 인프라팀, 보안팀, QA팀, 백엔드, 프론트 등 다수 팀과 협업 및 조율"
        ]
      },
      {
        title: "서비스 아키텍처 재설계",
        details: [
          "LangGraph 기반 Multi-Agent Supervisor 구조로 전환",
          "Supervisor Agent: 사용자 질문 분석 및 적절한 하위 에이전트 호출",
          "다양한 Tool Agent 설계 및 구현 (MariaDB 조회, Qdrant 검색, Redshift 분석 등)",
          "Chain + Agentic 하이브리드 구조 구현"
        ]
      },
      {
        title: "Vector Database 교체",
        details: [
          "LanceDB → Qdrant 마이그레이션",
          "하이브리드 검색 (Dense + Sparse) 구현",
          "컬렉션 관리 및 임베딩 파이프라인 재구축",
          "검색 정확도 및 속도 향상"
        ]
      },
      {
        title: "성능 고도화",
        details: [
          "비동기 처리, 캐싱 전략 (Redis, Qdrant)",
          "병렬처리 및 Forward Tool 적용",
          "Agent 워크플로우 최적화",
          "실시간 스트리밍 응답 구현 (SSE)"
        ]
      }
    ],
    challenges: [
      {
        title: "대규모 인력 관리",
        description: "다수 인턴급 RA(15명) + 타 업체 개발자 코드 리뷰 및 관리. V3 아키텍처로 완성된 구조 제공, 명확한 가이드라인 제시로 극복"
      },
      {
        title: "대기업 보안 정책",
        description: "방화벽 신청 → 승인 → 작업 완료까지 5일 소요. 사전에 모든 담당자 파악, 직접 커뮤니케이션으로 극복"
      },
      {
        title: "대규모 협업의 어려움",
        description: "약 10개 팀과 빈번한 회의, 오래 걸리는 의사결정. 명확한 문서화 및 사전 조율, 변경 최소화 전략으로 극복"
      }
    ],
    learnings: [
      "아키텍처 설계의 중요성: 개발자들이 이해하고 따라할 수 있는 명확한 구조 제공",
      "고객 중심 개발: 약 10회 반복 개선 사이클로 99% 만족도 달성",
      "대기업 문화 이해: 변경 최소화 전략, 사전 조율 및 명확한 문서화",
      "성능 최적화 경험: 병목 지점 정확히 파악하고 단계적으로 개선",
      "멀티 팀 협업: 각 분야 최고 전문가들의 일하는 방식을 직접 관찰하고 배움",
      "기술 깊이의 중요성: LLM 고유명사 오표기 문제를 토크나이저 레벨까지 분석"
    ]
  },
  "katech-ai-agent": {
    id: "katech-ai-agent",
    title: "자동차 지식 에이전트 - 보고서 자동 생성 AI",
    subtitle: "국내 자동차 연구기관 RAG 기반 보고서 생성",
    period: "2024.03 ~ 2026.02",
    duration: "약 1년 11개월",
    role: "1~2차: 1인 풀스택 개발 (7개월) / 3~4차: 메인 PL / 팀 3명",
    team: "개발자 3명 (본인 포함)",
    description: "국내 자동차 연구기관의 자동차 분야 특화 RAG 기반 보고서 자동 생성 시스템 및 챗봇. 사전 공개/공개/비공개 데이터 3단계 분류 관리, 마이디스크 연동, Keycloak SSO 인증.",
    techStack: {
      backend: ["FastAPI", "Python", "Celery", "Redis"],
      frontend: ["Next.js", "React", "TypeScript", "BlockNote Editor"],
      database: ["PostgreSQL (Kysely ORM)", "Qdrant (Vector DB)"],
      aiml: ["LangChain", "LangGraph", "OpenAI API (GPT-3.5/4/4o)", "Claude"],
      infrastructure: ["Docker", "Docker Compose", "Nginx", "Linux Server"],
      authentication: ["Keycloak (SSO)"],
      monitoring: ["LangSmith", "DataDog"],
      etc: ["Server-Sent Events (SSE)"]
    },
    keyFeatures: [
      {
        title: "서버 인프라 구축 및 배포",
        details: [
          "Docker Compose 기반 멀티 컨테이너 환경 구축",
          "HTTPS 적용 및 도메인 설정 (https://agent.bigdata-car.kr/)",
          "VPN 및 SSH 접속 환경 설정"
        ]
      },
      {
        title: "인증 및 권한 관리",
        details: [
          "Keycloak 기반 SSO(Single Sign-On) 로그인 시스템",
          "OAuth 2.0 토큰 관리",
          "세션 기반 사용자 인증 및 권한 검증"
        ]
      },
      {
        title: "RAG 기반 보고서 자동 생성",
        details: [
          "사전 공개/공개/비공개 데이터 3단계 분류",
          "마이디스크 연동 파일 업로드 및 관리",
          "PDF, DOCX, PPTX 파일 자동 파싱",
          "DALL-E 3 연동 이미지 자동 생성",
          "출처 표기 UI (PDF 페이지 번호 포함)"
        ]
      },
      {
        title: "LangGraph 멀티 에이전트 시스템",
        details: [
          "Research Agent: Multi-Query 생성 및 하이브리드 검색",
          "Report Agent: 검색 결과 기반 보고서 생성",
          "Supervisor Agent: 에이전트 조율 및 상태 관리",
          "PostgreSQL Checkpointer로 에이전트 상태 영속화"
        ]
      },
      {
        title: "멀티 파일 파서 통합",
        details: [
          "4개 파서 통합: Upstage, LlamaParse, Docling, Unstructured",
          "파서별 성능 비교 및 최적화",
          "파싱 결과 시각화 (PDF + Markdown Interactive Highlight)",
          "사용자별 기본 파서 선택 기능"
        ]
      }
    ],
    achievements: [
      {
        metric: "보고서 작성 시간",
        before: "1시간",
        after: "1분",
        improvement: "98% 단축"
      },
      "1인 풀스택으로 7개월간 전체 시스템 설계 및 구현",
      "Keycloak SSO 기반 보안 인증 시스템 구축",
      "3단계 데이터 분류 및 권한 관리 시스템",
      "Flask → FastAPI 마이그레이션 성공",
      "LangGraph 멀티 에이전트 아키텍처 구축",
      "200+ 테스트 케이스 작성으로 시스템 안정성 확보"
    ],
    challenges: [
      {
        title: "1인 풀스택 개발",
        description: "백엔드, 프론트엔드, 인프라, AI 모델 연동까지 전체 스택 담당. 체계적인 아키텍처 설계와 단계적 구현으로 극복"
      },
      {
        title: "대규모 재설계",
        description: "3차에서 Flask를 FastAPI로 전환. API 문서 선행 작성 및 모듈별 단계적 이전으로 안전하게 완료"
      },
      {
        title: "프로젝트 동시 진행",
        description: "대형 제약 프로젝트와 동시 진행으로 매일 새벽 2시까지 근무. 시간대별 우선순위 분리로 효율적 관리"
      }
    ],
    learnings: [
      "풀스택 개발 역량: 백엔드/프론트엔드/인프라 전체 스택 경험",
      "SSO 인증 시스템: Keycloak 기반 OAuth 2.0 구현 노하우",
      "데이터 권한 관리: 3단계 분류 및 세밀한 권한 제어",
      "프로젝트 관리: 1인 개발에서 팀 PL로 역할 전환 경험",
      "단계별 개선의 힘: MVP부터 시작하여 지속적으로 개선"
    ]
  },
  "greentech": {
    id: "greentech",
    title: "그린텍 하수처리 수질 예측 AI",
    subtitle: "하수처리공정 수질 예측 및 이상탐지",
    period: "2024.07 ~ 2024.11",
    duration: "약 4개월",
    role: "PL (팀 2명: 본인 포함)",
    team: "개발자 2명",
    description: "하수처리장의 공정 단계별 수질 예측 모델 개발 및 실시간 이상 탐지 시스템. 19개 타겟 변수에 대한 예측 모델 구축으로 품질 Hunting 최소화 및 안정 운전 지원.",
    techStack: {
      ml: ["PyTorch", "LightGBM", "XGBoost", "CatBoost"],
      anomaly: ["PyOD", "COMBO"],
      dataprocessing: ["NumPy", "Pandas", "Numba"],
      visualization: ["Matplotlib", "Seaborn", "Plotly Dash"],
      backend: ["Flask", "Gunicorn"],
      timeseries: ["statsmodels"],
      deployment: ["Docker"]
    },
    keyFeatures: [
      {
        title: "수질 예측 모델 개발",
        details: [
          "LightGBM, XGBoost, CatBoost 앙상블 모델",
          "PyTorch 기반 LSTM, GRU 딥러닝 모델",
          "ARIMA, SARIMA 시계열 모델",
          "Optuna 하이퍼파라미터 튜닝"
        ]
      },
      {
        title: "이상 탐지 시스템",
        details: [
          "PyOD 기반 10+ 알고리즘 실험 (Isolation Forest, LOF, CBLOF)",
          "COMBO 앙상블 이상 탐지",
          "이상치 스코어 계산 및 임계값 설정",
          "실시간 모니터링 및 알림"
        ]
      },
      {
        title: "시각화 대시보드",
        details: [
          "Plotly Dash 기반 실시간 모니터링",
          "공정 단계별 수질 예측값 및 실측값 시각화",
          "이상 탐지 알림 표시",
          "자동 분석 리포트 생성"
        ]
      }
    ],
    achievements: [
      {
        metric: "T-N 방류수 예측",
        before: "-",
        after: "R² 0.9244",
        improvement: "RandomForest"
      },
      {
        metric: "TOC 방류수 예측",
        before: "-",
        after: "R² 0.8640",
        improvement: "CatBoost"
      },
      {
        metric: "이상 탐지 정확도",
        before: "-",
        after: "98.50%",
        improvement: "Random Forest"
      },
      "19개 타겟 변수 예측 모델 개발 완료",
      "실시간 이상 탐지 시스템 구축",
      "품질 Hunting 최소화로 안정 운전 가능"
    ],
    challenges: [
      {
        title: "시계열 데이터 처리",
        description: "결측치, 이상치가 많은 공정 데이터. 도메인 지식 기반 전처리 및 피처 엔지니어링으로 해결"
      },
      {
        title: "모델 선택",
        description: "다양한 ML/DL 모델 실험 필요. 체계적인 실험 관리 및 성능 비교로 최적 모델 도출"
      }
    ],
    learnings: [
      "앙상블 모델의 강력함: 단일 모델 대비 성능 향상",
      "도메인 지식의 중요성: 하수처리 공정 이해가 피처 엔지니어링에 핵심",
      "실시간 시스템 구축: 배치 예측과 실시간 모니터링의 차이",
      "클라이언트 커뮤니케이션: 기술 용어를 비즈니스 가치로 전달"
    ]
  },
  "prop": {
    id: "prop",
    title: "PROP - 제안서 작성 AI Agent",
    subtitle: "제안서 및 문서 생성 자동화 시스템",
    period: "2024.03 ~ 2024.04",
    duration: "약 2개월",
    role: "유지보수 및 추가 개발",
    team: "사내 자체 프로젝트",
    description: "AI 기반 사업 제안서, 기술 제안서 자동 생성 시스템. 템플릿 기반 문서 구조 생성 및 사용자 정의 프롬프트 지원. Celery 기반 비동기 작업 처리로 사용자 경험 개선.",
    techStack: {
      backend: ["Flask", "Celery", "Redis", "MySQL"],
      frontend: ["HTML", "JavaScript (Vanilla JS)"],
      ai: ["OpenAI API (GPT-3.5-turbo, GPT-4, GPT-4o)"]
    },
    keyFeatures: [
      {
        title: "제안서 생성 엔진",
        details: [
          "템플릿 기반 문서 구조 자동 생성",
          "프롬프트 엔지니어링을 통한 품질 향상",
          "섹션별 생성 로직 개선",
          "GPT-4/GPT-4o 업그레이드"
        ]
      },
      {
        title: "비동기 작업 처리",
        details: [
          "Celery 기반 문서 생성 비동기 처리",
          "Redis 작업 큐 관리",
          "생성 진행 상황 실시간 업데이트"
        ]
      },
      {
        title: "사용자 관리",
        details: [
          "MySQL 기반 사용자 정보 관리",
          "사용자별 생성 이력 저장",
          "사용 통계 수집 (생성 횟수, 토큰 사용량)"
        ]
      }
    ],
    achievements: [
      "OpenAI API 업데이트로 제안서 품질 향상",
      "Celery 비동기 처리로 사용자 경험 개선",
      "사용자 가입 및 사용 현황 모니터링 시스템 구축"
    ],
    learnings: [
      "기존 시스템 유지보수 경험: 레거시 코드 이해 및 개선",
      "비동기 작업 처리: Celery + Redis 활용 노하우",
      "프롬프트 엔지니어링: 생성 품질 향상을 위한 프롬프트 최적화"
    ]
  },
  "langchain-tutorial": {
    id: "langchain-tutorial",
    title: "LangChain Open Tutorial",
    subtitle: "RAG 및 LangGraph 튜토리얼 작성",
    period: "2025.01 ~ 2025.02",
    duration: "약 7주",
    role: "오픈소스 컨트리뷰터",
    team: "TeddyNote 커뮤니티",
    description: "2,000+ 커밋이 발생한 대규모 오픈소스 프로젝트에 기여. RAG(Retrieval-Augmented Generation) 관련 LangChain 튜토리얼 작성 및 번역. 한국어 개발자들이 RAG와 LangGraph를 쉽게 배울 수 있도록 지원.",
    techStack: {
      aiml: ["LangChain", "LangGraph", "RAG"],
      llm: ["OpenAI GPT-4o", "Claude"],
      tools: ["LlamaParse", "DuckDuckGo API"],
      development: ["Jupyter Notebook", "Python", "Google Colab"],
      collaboration: ["GitHub", "GitBook"]
    },
    keyFeatures: [
      {
        title: "LlamaParse 튜토리얼",
        details: [
          "PDF, Word, PowerPoint, Excel 등 다양한 파일 파싱",
          "Multimodal 모델(GPT-4o) 기반 문서 분석",
          "자연어 명령을 통한 커스텀 파싱 설정",
          "OCR 기반 이미지 텍스트 추출"
        ]
      },
      {
        title: "Conversation Memory Management",
        details: [
          "LangGraph 기반 챗봇 메모리 관리 시스템",
          "Configuration Class 활용 사용자별 컨텍스트 관리",
          "단기 및 장기 메모리 구현",
          "StateGraph 활용 대화 플로우 자동화"
        ]
      },
      {
        title: "CoT-Based Smart Web Search",
        details: [
          "Chain-of-Thought (CoT) 기반 스마트 웹 검색",
          "Plan-and-Execute QA 시스템 개발",
          "Multi-Query 생성 (1개 → 3~5개 검색 쿼리)",
          "검색 → 추출 → 추론 → 응답 파이프라인"
        ]
      }
    ],
    achievements: [
      "3개의 튜토리얼 작성 및 GitHub/GitBook 게시",
      "대규모 오픈소스 프로젝트(2,000+ 커밋) 기여 경험",
      "Peer Review 세션을 통한 협업 및 기술 인사이트 확장",
      "한국어 개발자 커뮤니티에 RAG/LangGraph 지식 공유"
    ],
    challenges: [
      {
        title: "번역의 어려움",
        description: "단순 번역이 아닌 한국 개발자들이 이해하기 쉬운 설명 필요. 전문 용어, 의역, 예시 추가를 신중히 판단"
      },
      {
        title: "초보자 눈높이",
        description: "Peer Review 피드백을 통해 초보자가 이해하기 어려운 부분 파악 및 개선"
      }
    ],
    learnings: [
      "기술 지식의 민주화: 오픈소스 기여로 개발자 생태계 성장 지원",
      "설명의 명확성: '왜'와 '어떻게'를 함께 전달하는 법",
      "협업의 가치: Peer Review로 더 나은 콘텐츠 완성",
      "기술 블로그 운영: 지식 공유의 선순환"
    ]
  },
  "nuartz": {
    id: "nuartz",
    title: "Nuartz - Obsidian → Next.js 오픈소스 라이브러리",
    subtitle: "Obsidian 볼트를 Next.js 웹사이트로 퍼블리싱하는 headless 라이브러리",
    period: "2026.03 ~ 진행 중",
    duration: "약 2주",
    role: "1인 개발 / npm 패키지 배포",
    team: "개인 오픈소스 프로젝트",
    description: "Obsidian 볼트를 Next.js 웹사이트로 서빙하기 위한 headless 데이터 레이어 라이브러리. Quartz의 한계(커스텀 UI 불가, AI 연동 어려움)를 해결하기 위해 직접 개발. npm 패키지로 배포하여 누구나 자신의 Next.js 앱에 Obsidian 기능을 통합 가능.",
    blogPost: "/blog/Projects/Nuartz/00-Overview",
    package: {
      registry: "npm",
      name: "nuartz",
      url: "https://www.npmjs.com/package/nuartz"
    },
    demoImage: {
      url: "https://raw.githubusercontent.com/syshin0116/nuartz/main/assets/nuartz-homepage.png",
      alt: "Nuartz 데모 사이트 스크린샷"
    },
    techStack: {
      core: ["TypeScript", "unified (remark/rehype)"],
      features: ["remark-math", "rehype-katex", "rehype-pretty-code", "FlexSearch", "D3.js"],
      webapp: ["Next.js 15", "Tailwind CSS v4", "shadcn/ui", "next-themes"],
      build: ["Bun", "tsc"],
      deployment: ["npm registry", "Vercel", "GitHub Pages"]
    },
    keyFeatures: [
      {
        title: "Obsidian 호환 마크다운 렌더링",
        details: [
          "위키링크 ([[note]], [[note|alias]]) 파싱 및 라우팅",
          "양방향 백링크 인덱스 자동 생성",
          "콜아웃 블록 (> [!note], > [!warning] 등)",
          "하이라이트 (==text==), 코멘트 (%%text%%), 화살표 (->)",
          "LaTeX 수식 렌더링 ($...$, $$...$$)"
        ]
      },
      {
        title: "콘텐츠 유틸리티",
        details: [
          "재귀적 마크다운 파일 탐색 및 드래프트 필터링",
          "폴더 기반 파일 트리 생성 (사이드바용)",
          "FlexSearch 기반 전문 검색 인덱스 (CJK 지원)",
          "그래프 뷰 데이터 생성 (노트-태그 관계)"
        ]
      },
      {
        title: "headless 아키텍처",
        details: [
          "UI 없이 데이터 레이어만 제공 — 어떤 디자인이든 적용 가능",
          "nuartz.config.ts로 설정 (title, baseUrl, nav 등)",
          "SSG/ISR 모두 지원",
          "GitHub Pages 정적 배포 지원"
        ]
      },
      {
        title: "참고 웹앱 (apps/web)",
        details: [
          "shadcn/ui + Tailwind v4 기반 모던 UI",
          "다크모드, 반응형 레이아웃",
          "그래프뷰 (D3.js), 목차, 검색 (cmdk)",
          "OG 이미지 자동 생성, RSS 피드"
        ]
      }
    ],
    achievements: [
      "npm 패키지 배포 (nuartz@0.1.7)",
      "Quartz 핵심 기능을 Next.js 생태계로 포팅",
      "CJK(한국어/일본어/중국어) 검색 지원",
      "Vercel + GitHub Pages 양쪽 배포 지원",
      "개인 블로그로 실사용 중 (syshin0116.github.io)"
    ],
    challenges: [
      {
        title: "Quartz 플러그인 시스템 재해석",
        description: "Quartz의 Preact 기반 정적 사이트 생성기를 Next.js의 unified 파이프라인으로 재설계. remark/rehype 플러그인으로 위키링크, 콜아웃 등을 직접 구현"
      },
      {
        title: "CJK 검색 최적화",
        description: "FlexSearch의 기본 토크나이저가 한국어를 제대로 분리하지 못하는 문제. CJK 전용 토크나이저 설정으로 해결"
      },
      {
        title: "CSS 변수 호환성",
        description: "Tailwind v4의 oklch 색상 체계와 D3.js SVG 렌더링 간 호환 문제. hsl() 래퍼 제거하고 CSS 변수 직접 참조로 해결"
      }
    ],
    learnings: [
      "unified 생태계 깊이 이해: remark/rehype 플러그인 직접 작성",
      "npm 패키지 배포 및 버전 관리 실무 경험",
      "모노레포 구조 설계: packages/nuartz (라이브러리) + apps/web (참고 앱)",
      "headless 라이브러리 설계 철학: UI와 데이터 레이어의 분리",
      "오픈소스 프로젝트 운영: README, CHANGELOG, 문서화의 중요성"
    ]
  },
  "clidex": {
    id: "clidex",
    title: "Clidex - AI 에이전트를 위한 CLI 도구 검색",
    subtitle: "CLI 도구 검색 엔진 for AI Agents",
    period: "2026.03 ~ 진행 중",
    duration: "약 1주",
    role: "1인 개발 / 오픈소스",
    team: "개인 프로젝트",
    description: "AI 에이전트가 CLI 도구를 자연어로 검색·비교·설치할 수 있는 Rust 기반 인덱스. BM25 + 시노님 확장 + 퍼지 매칭 하이브리드 검색으로 높은 recall 달성. YAML/JSON 출력으로 LLM 친화적.",
    blogPost: "/blog/Projects/Clidex/01-Overview",
    package: {
      registry: "crates.io",
      name: "clidex",
      url: "https://crates.io/crates/clidex"
    },
    demoImage: {
      url: "https://raw.githubusercontent.com/syshin0116/clidex/main/assets/demo.gif",
      alt: "Clidex 터미널 데모"
    },
    techStack: {
      language: ["Rust (2021 edition)"],
      search: ["BM25 (bm25 crate)", "fuzzy-matcher (Skim algorithm)"],
      cli: ["clap 4 (derive)", "colored 2"],
      serialization: ["serde", "serde_yaml", "serde_json"],
      network: ["reqwest 0.12 (rustls)", "tokio 1"],
      build: ["LTO", "strip symbols", "opt-level = 'z'"]
    },
    keyFeatures: [
      {
        title: "하이브리드 검색 알고리즘",
        details: [
          "BM25 필드별 가중치 (이름 3x, 태그/카테고리 2x, 설명 1x)",
          "70+ 시노님 매핑 (search→find/grep/locate, http→web/api/curl 등)",
          "퍼지 매칭 폴백 (Skim algorithm) — 오타/부분 매칭 대응",
          "GitHub stars 기반 인기도 보정 (비선형 정규화)"
        ]
      },
      {
        title: "CLI 명령어 체계",
        details: [
          "clidex \"query\" — 자연어 도구 검색 (상위 10개)",
          "clidex info <name> — 도구 상세 정보",
          "clidex compare <names...> — 도구 비교 테이블",
          "clidex trending — 인기 도구 목록",
          "clidex update — GitHub Releases에서 인덱스 갱신"
        ]
      },
      {
        title: "AI 에이전트 친화적 설계",
        details: [
          "YAML/JSON 출력 포맷 — LLM이 파싱하기 쉬운 구조",
          "설치 명령어 통합 (brew, apt, cargo, npm 등)",
          "도구별 docs/llms.txt 링크 제공",
          "Pretty/YAML/JSON 3가지 출력 모드"
        ]
      }
    ],
    achievements: [
      "30개 쿼리 테스트 스위트에서 높은 recall 달성",
      "70+ CLI 도메인 시노님 매핑 구축",
      "최소 바이너리 사이즈 최적화 (LTO + strip)",
      "20+ 실제 CLI 도구 인덱싱 (jq, ripgrep, fd, bat, fzf 등)"
    ],
    challenges: [
      {
        title: "검색 정확도와 recall 균형",
        description: "BM25 단독으로는 'find files' → 'fd' 같은 시노님 매칭 불가. 도메인 특화 시노님 확장 + 퍼지 매칭 하이브리드로 해결"
      },
      {
        title: "인기도 편향 방지",
        description: "GitHub stars가 높은 도구가 관련성 낮은 쿼리에서도 상위 노출. 비선형 정규화 (10k stars 이상 diminishing returns)로 해결"
      }
    ],
    learnings: [
      "Rust 실전 프로젝트: clap, serde, tokio 활용",
      "정보 검색 알고리즘: BM25 + 시노님 확장의 효과",
      "AI 에이전트 도구 설계: 구조화된 출력의 중요성",
      "CLI 도구 생태계 이해: 패키지 매니저별 설치 방식"
    ]
  },
  "syshin0116-dev": {
    id: "syshin0116-dev",
    title: "Syshin0116.dev - 블로그 + 포트폴리오 통합",
    subtitle: "Nuartz 기반 블로그·포트폴리오·AI 챗봇 통합 사이트",
    period: "2026.03 ~ 진행 중",
    duration: "약 2주",
    role: "1인 풀스택 개발",
    team: "개인 프로젝트",
    description: "개인 기술 블로그, 프로젝트 포트폴리오, RAG 기반 AI 챗봇을 하나의 도메인으로 통합. Nuartz를 데이터 레이어로 사용하고 Next.js 15 + shadcn/ui로 모던 UI 구현. LangGraph SDK로 blog-rag 백엔드와 연동하여 블로그 콘텐츠 기반 질의응답 제공.",
    techStack: {
      frontend: ["Next.js 15 (App Router)", "React 19", "Tailwind CSS v4", "shadcn/ui", "Framer Motion"],
      content: ["Nuartz (headless markdown)", "FlexSearch (CJK 검색)", "D3.js (그래프뷰)", "Mermaid"],
      ai: ["LangGraph SDK", "LangChain Core", "blog-rag 백엔드 (FastAPI)"],
      auth: ["Supabase (Google OAuth)"],
      rendering: ["KaTeX (수식)", "Shiki (코드 하이라이팅)", "remark/rehype"],
      deployment: ["Vercel", "Bun"]
    },
    keyFeatures: [
      {
        title: "RAG 기반 AI 챗봇",
        details: [
          "LangGraph SDK로 blog-rag 백엔드 연동",
          "자동/수동 검색 모드 (메타데이터, 벡터, 그래프 검색)",
          "실시간 스트리밍 응답 + 도구 호출 시각화",
          "출처 표시 기능"
        ]
      },
      {
        title: "Obsidian 호환 블로그",
        details: [
          "위키링크, 백링크, 콜아웃 블록 지원",
          "D3.js 인터랙티브 지식 그래프",
          "Cmd+K 전문 검색 (FlexSearch, CJK 지원)",
          "링크 호버 프리뷰, 리더 모드, 읽기 시간"
        ]
      },
      {
        title: "프로젝트 포트폴리오",
        details: [
          "타임라인 뷰 (12+ 프로젝트)",
          "상세 프로젝트 페이지 (기술스택, 성과, 아키텍처)",
          "회사/개인 프로젝트 분류"
        ]
      },
      {
        title: "SEO 및 인프라",
        details: [
          "JSON-LD 구조화 데이터, Open Graph 이미지",
          "sitemap, robots.txt 자동 생성",
          "Giscus 댓글, Vercel Analytics",
          "다크/라이트 테마"
        ]
      }
    ],
    achievements: [
      "4개 레포를 3개로 재편하여 통합 사이트 구축",
      "Nuartz를 실제 프로덕션에서 사용하며 라이브러리 검증",
      "RAG 챗봇으로 블로그 콘텐츠 기반 대화형 검색 제공",
      "Obsidian 볼트 → 웹사이트 무중단 퍼블리싱 파이프라인"
    ],
    challenges: [
      {
        title: "레포 통합",
        description: "기존 블로그, 포트폴리오, Obsidian 볼트가 별도 레포. Nuartz를 공통 데이터 레이어로 사용하여 하나의 Next.js 앱으로 통합"
      },
      {
        title: "RAG 백엔드 연동",
        description: "LangGraph SDK의 스트리밍 응답과 도구 호출을 프론트엔드에서 실시간 시각화. SSE + 상태 관리로 해결"
      }
    ],
    learnings: [
      "프로덕션 사용이 최고의 라이브러리 테스트",
      "Next.js 15 App Router + React 19의 서버 컴포넌트 활용",
      "Supabase Auth 통합 경험",
      "통합 사이트의 UX 설계: 블로그, 포트폴리오, 챗봇의 조화"
    ]
  },
  "men-in-black": {
    id: "men-in-black",
    title: "Men-in-Black - 교통 법규 위반 감지",
    subtitle: "블랙박스 영상 속 교통 법규 위반 차량 감지",
    period: "2023.10 ~ 2023.12",
    duration: "약 3개월",
    role: "팀 프로젝트 (4명) - License Plate Recognition 및 Depth Estimation 담당",
    team: "새싹 AI 부트캠프",
    description: "블랙박스 영상에서 교통 법규 위반 차량을 자동으로 감지하고 신고하는 AI 시스템. 차량 감지, 번호판 인식, 거리 추정 등 종합적인 Computer Vision 기술 적용.",
    techStack: {
      computervision: ["YOLOv8 (n, m)", "SORT", "EasyOCR"],
      depthestimation: ["ZoeDepth", "MiDaS v3"],
      mldl: ["PyTorch", "TensorFlow", "OpenCV"],
      backend: ["FastAPI"],
      environment: ["NVIDIA GPU", "AWS", "Ubuntu", "Anaconda"]
    },
    keyFeatures: [
      {
        title: "차량 및 번호판 감지",
        details: [
          "YOLOv8n, YOLOv8m 기반 차량 감지 (COCO Dataset)",
          "SORT 알고리즘으로 실시간 2D 다중 객체 추적",
          "YOLOv8m 기반 번호판 감지 (Roboflow Dataset 24,242 images)",
          "Data Augmentation: Flip, Crop, Rotation, Shear, Grayscale 등"
        ]
      },
      {
        title: "OCR (번호판 텍스트 인식)",
        details: [
          "EasyOCR 활용 번호판 텍스트 인식",
          "Preprocessing: Grayscale, CLAHE, Gaussian Blur, Canny Edge",
          "Perspective Transformation으로 번호판 영역 추출"
        ]
      },
      {
        title: "Monocular Depth Estimation",
        details: [
          "ZoeDepth 모델로 단일 카메라 영상에서 거리 추정",
          "실시간 거리 추정 및 안전거리 위반 탐지"
        ]
      }
    ],
    achievements: [
      "YOLOv8 기반 차량 및 번호판 실시간 감지 구현",
      "EasyOCR을 활용한 번호판 텍스트 인식",
      "ZoeDepth 기반 차량 간 거리 추정",
      "종합적인 Computer Vision 프로젝트 경험"
    ],
    challenges: [
      {
        title: "낮은 화질",
        description: "블랙박스 영상의 낮은 화질로 인한 OCR 정확도 저하. Preprocessing 최적화로 개선"
      },
      {
        title: "상대 속도",
        description: "상대 속도가 빠를수록 인식률 감소. 향후 Segmentation 시도 필요"
      }
    ],
    learnings: [
      "Object Detection: YOLO 시리즈 실전 활용",
      "Object Tracking: SORT 알고리즘 이해 및 적용",
      "OCR: EasyOCR과 Preprocessing 최적화",
      "Depth Estimation: Monocular 방식의 한계와 가능성",
      "팀 협업: 모듈별 역할 분담 및 통합"
    ]
  },
  "podly": {
    id: "podly",
    title: "Podly - AI 기반 맞춤형 음성 뉴스 서비스",
    subtitle: "AI 음성 뉴스 및 관심사 정보 제공",
    period: "2024.08 ~ 2024.09",
    duration: "약 2개월",
    role: "팀장 / AI 및 백엔드 개발 (팀 4명)",
    team: "창업 경진대회",
    description: "이동 중 터치 없이 음성만으로 맞춤형 뉴스를 청취할 수 있는 AI 서비스. 음성 인식, 자연어 처리, TTS, RAG 기술을 종합한 종합 AI 플랫폼. 고령층 및 시각장애인의 디지털 정보 접근성 향상.",
    techStack: {
      backend: ["FastAPI", "Python"],
      frontend: ["Flutter", "React"],
      aiml: ["LangChain", "RAG", "OpenAI API", "Upstage Solar", "Google Gemma2", "Microsoft Phi 3.5", "Meta Llama 3.1"],
      speech: ["OpenAI Whisper", "ElevenLabs TTS", "TypeCast TTS"],
      data: ["Pandas", "NumPy", "Tableau", "Power BI"],
      cloud: ["GCP"]
    },
    keyFeatures: [
      {
        title: "음성 인식 및 자연어 처리",
        details: [
          "OpenAI Whisper 음성→텍스트 변환",
          "다양한 LLM 모델 테스트 (GPT, Solar, Gemma2, Phi, Llama)",
          "실시간 질의응답 및 콘텐츠 생성",
          "개인화 추천 시스템"
        ]
      },
      {
        title: "RAG 기반 뉴스 큐레이션",
        details: [
          "외부 문서에서 관련 정보 검색",
          "실시간 주요 뉴스 요약",
          "맞춤형 뉴스 큐레이션 (사용자 관심사 기반)",
          "심층 질의응답 (Q&A): 뉴스 원문 기반 답변"
        ]
      },
      {
        title: "TTS 및 목소리 변환",
        details: [
          "ElevenLabs, TypeCast 고급 TTS",
          "자연스럽고 감정이 담긴 음성 생성",
          "다양한 목소리 옵션 (성우, 유명인)"
        ]
      },
      {
        title: "공공데이터 활용",
        details: [
          "정부 및 공공기관 데이터 수집",
          "Pandas, NumPy 데이터 분석",
          "Tableau, Power BI 시각화",
          "위치 기반 날씨, 개인 일정 반영"
        ]
      }
    ],
    achievements: [
      "음성 명령 기반 뉴스 서비스로 터치 없는 정보 소비 경험 제공",
      "RAG 기법으로 최신 정보와 개인화 추천 결합",
      "다양한 LLM 모델 테스트 및 최적 모델 선택 경험",
      "공공데이터 활용 신뢰성 높은 콘텐츠 제작"
    ],
    challenges: [
      {
        title: "LLM 모델 선택",
        description: "다양한 LLM 모델(GPT, Solar, Gemma2, Phi, Llama) 비교 실험. 비용, 속도, 품질 균형 찾기"
      },
      {
        title: "TTS 품질",
        description: "자연스러운 음성 생성. ElevenLabs와 TypeCast 조합으로 해결"
      }
    ],
    learnings: [
      "음성 인터페이스 설계: 터치 없는 경험의 UX",
      "다양한 LLM 모델 비교 및 선택 기준",
      "TTS 기술: 자연스러운 음성 생성의 어려움",
      "사회적 가치: 디지털 격차 해소 및 접근성 향상",
      "시장성 분석: 음성 인식 및 LLM 시장 전망"
    ]
  },
  "employment-data": {
    id: "employment-data",
    title: "고용노동 공공데이터 활용 공모전",
    subtitle: "데이터 분석 및 인터랙티브 시각화",
    period: "2024.06",
    duration: "약 1개월",
    role: "팀장 (팀 프로젝트)",
    team: "고용노동부 공모전",
    description: "고용노동부 공공데이터를 활용한 데이터 분석 및 시각화 서비스. 데이터 전처리 및 Plotly 기반 인터랙티브 시각화로 고용 트렌드 및 패턴 발견.",
    techStack: {
      dataprocessing: ["Python", "Pandas", "NumPy"],
      visualization: ["Plotly", "Matplotlib", "Seaborn"],
      development: ["Jupyter Notebook"]
    },
    keyFeatures: [
      {
        title: "데이터 수집 및 전처리",
        details: [
          "고용노동부 공공데이터포털 데이터 수집",
          "Pandas 데이터 전처리 (결측치, 이상치, 정규화)",
          "데이터 병합 및 집계 (merge, groupby, pivot_table)",
          "NumPy 수치 연산 및 배열 처리"
        ]
      },
      {
        title: "탐색적 데이터 분석 (EDA)",
        details: [
          "기술 통계량 분석 (평균, 중앙값, 표준편차)",
          "데이터 분포 및 상관관계 분석",
          "시계열 데이터 트렌드 분석",
          "지역별/산업별 고용 현황 비교"
        ]
      },
      {
        title: "Plotly 인터랙티브 시각화",
        details: [
          "드롭다운, 슬라이더 필터 기능",
          "Line Chart: 시계열 고용 트렌드",
          "Bar Chart: 지역별/산업별 비교",
          "Scatter Plot: 상관관계 분석",
          "Heatmap: 데이터 분포 및 밀도",
          "Choropleth Map: 지역별 고용 현황 지도"
        ]
      }
    ],
    achievements: [
      "고용노동 공공데이터 전처리 및 정제 경험",
      "Plotly 인터랙티브 대시보드 구축",
      "데이터 인사이트 및 결론 도출",
      "공공데이터 활용 서비스 기획 경험"
    ],
    learnings: [
      "공공데이터 활용: 데이터 수집 및 정제 노하우",
      "Plotly 마스터: 인터랙티브 시각화의 강력함",
      "데이터 스토리텔링: 시각화로 인사이트 전달",
      "팀 협업: 데이터 분석 프로젝트의 역할 분담"
    ]
  },
  "podlybot": {
    id: "podlybot",
    title: "PodlyBot - 카카오톡 LLM 챗봇",
    subtitle: "개인 비서 & 회사 업무용 LLM 챗봇",
    period: "2024.09",
    duration: "약 1개월",
    role: "1인 개발 (기획, 개발, 운영)",
    team: "개인 프로젝트 + 회사 내부 프로젝트",
    description: "안드로이드 폰에 구현한 카카오톡 기반 LLM 챗봇. 개인용(PodlyBot)과 회사용 두 가지 버전으로 배포. 단체 채팅방에서 즉시 호출 가능한 LLM 서비스. URL 요약 및 Notion 자동 정리 기능으로 정보 수집 워크플로우 자동화. 회사용은 자체 LLM 서비스 연동 및 고객사 테스트 환경 제공.",
    techStack: {
      platform: ["메신저봇R (Android)"],
      language: ["JavaScript (Rhino JavaScript Engine)"],
      ai: ["LLM API (OpenAI GPT 등)", "회사 자체 LLM 서비스"],
      integration: ["Notion API (개인/회사 워크스페이스)", "Web Scraping"],
      deployment: ["안드로이드 공기계"]
    },
    keyFeatures: [
      {
        title: "공통 기능: LLM 대화 기능",
        details: [
          "카카오톡 단체 채팅방에서 바로 호출 가능",
          "별도 설명 없이 즉시 사용 가능한 직관적 인터페이스",
          "메신저봇R 기반 알림 감지 및 자동 응답",
          "채팅방별 컨텍스트 관리"
        ]
      },
      {
        title: "공통 기능: URL 요약 및 Notion 정리",
        details: [
          "채팅방에 공유된 URL 자동 감지",
          "웹 페이지 내용 크롤링 및 요약 생성",
          "요약 내용을 Notion 페이지에 자동 저장",
          "메타데이터(URL, 날짜, 카테고리) 자동 기록"
        ]
      },
      {
        title: "개인용 (PodlyBot): 워크플로우 최적화",
        details: [
          "유용한 URL 발견 시 카톡으로 전송",
          "자동으로 요약 및 개인 Notion에 정리",
          "Notion에서 체계적으로 정리된 내용 검토",
          "24/7 상시 운영 (안드로이드 공기계)"
        ]
      },
      {
        title: "회사용: LLM 서비스 연동 및 테스트",
        details: [
          "회사에서 개발한 AI 서비스들과 연동",
          "고객사가 카톡으로 간편하게 테스트 가능",
          "데모 및 프로토타입 공유 용도",
          "팀원들이 공유하는 기술 자료, 뉴스 회사 Notion에 정리"
        ]
      }
    ],
    achievements: [
      "개인용과 회사용 두 가지 버전으로 배포하여 다양한 사용 케이스 대응",
      "개인용: 일상적인 정보 수집 및 정리 워크플로우 자동화, 지인들도 사용 요청",
      "회사용: 고객사가 별도 환경 설정 없이 LLM 서비스 테스트 가능",
      "URL 공유 시 즉시 요약 및 Notion 정리로 생산성 향상",
      "단체 채팅방에서 LLM 서비스 간편하게 활용"
    ],
    challenges: [
      {
        title: "Rhino JavaScript 한계",
        description: "최신 문법 사용 불가. async/await 대신 콜백 패턴으로 구현"
      },
      {
        title: "알림 기반 처리",
        description: "카톡 알림 기반 이벤트 처리. 채팅방별 컨텍스트 관리 필요"
      }
    ],
    learnings: [
      "작은 불편함 해결이 큰 가치: 개인 문제 해결이 주변 사람들 생산성 향상으로",
      "레거시 환경 극복: Rhino JavaScript 제약 속에서 구현",
      "24/7 운영 경험: 안드로이드 공기계 활용 노하우",
      "실용주의: 수익보다 실제 문제 해결에 집중",
      "확장 가능한 설계: 같은 기술 베이스로 개인용과 회사용 두 버전 배포",
      "회사 내부 시스템 연동: 자체 LLM 서비스와 Notion 워크스페이스 통합",
      "고객사 지원: 간편한 테스트 환경 제공의 가치"
    ]
  },
  "sk-cooh-prediction": {
    id: "sk-cooh-prediction",
    title: "Copolyester COOH 예측 모델",
    subtitle: "Copolyester 생산 공정 COOH 예측",
    period: "2025 (SK Chemical)",
    duration: "TBD",
    role: "ML 모델 개발",
    team: "SK Chemical DX Lab",
    description: "ES-20 COOH 변화에 따라 Polymer 반응성이 변하여 제품 품질 Hunting이 발생하는 문제를 해결. COOH 변화 예측으로 온도/유량 사전 Action이 가능하게 하여 안정 운전 지원.",
    techStack: {
      ml: ["scikit-learn", "LightGBM", "XGBoost"],
      dataprocessing: ["Python", "Pandas", "NumPy"],
      datasource: ["RTIS", "ERP"]
    },
    businessGoals: [
      {
        title: "As-is",
        description: "ES-20 COOH 변화에 따라 Polymer 반응성이 변하여 제품 품질 Hunting 발생"
      },
      {
        title: "To-be",
        description: "ES-20 COOH 변화 예측으로 온도/유량 사전 Action 가능, 안정 운전"
      }
    ],
    keyResponsibilities: [
      {
        title: "공정 데이터 분석 및 전처리",
        details: [
          "ES-10/20 온도, 레벨, 압력, (열매/물) 유량 등 인풋 데이터 분석",
          "ES-20 COOH 분석값 기반 피처 엔지니어링",
          "RTIS, ERP 데이터 소스 통합 및 전처리"
        ]
      },
      {
        title: "COOH 예측 ML 모델 개발",
        details: [
          "다양한 ML 모델 실험 (LightGBM, XGBoost 등)",
          "모델 성능 평가 및 하이퍼파라미터 튜닝",
          "예측값 기반 Action 가이드 제공"
        ]
      }
    ],
    achievements: [
      "품질 Hunting 최소화로 안정 운전 가능",
      "온도/유량 사전 Action으로 불량률 감소"
    ],
    learnings: [
      "화학 공정 도메인 지식: Copolyester 반응 메커니즘 이해",
      "공정 데이터 특성: RTIS/ERP 데이터 전처리 노하우",
      "예측 모델의 실제 현장 적용: 모델 결과를 운전자 Action으로 연결"
    ]
  },
  "sk-qa-image-classification": {
    id: "sk-qa-image-classification",
    title: "이미지 선별 모델 - 이물 분석 검출 지원",
    subtitle: "PET Chip 이물 이미지 자동 분류",
    period: "2025.02.24 ~ 2025.04.03",
    duration: "약 1개월",
    role: "Computer Vision 모델 개발",
    team: "풍영환 (QA팀), 전한솔 (DT추진팀)",
    description: "PET Chip 특성상 원통형이고 불투명하여 선별기기의 한계로 오류값 다수 발생. 이미지 분석을 통해 사람이 직접 확인해야 하는 이미지 수를 최소화하는 모델 개발.",
    techStack: {
      ml: ["Python", "Computer Vision"],
      imageprocessing: ["OpenCV", "PyTorch"],
      dataprocessing: ["PyPDF2", "pdf2image"]
    },
    businessGoals: [
      {
        title: "As-is",
        description: "PET Chip 특성상 원통형이고 불투명하여 선별기기의 한계로 오류값 다수 발생, 사람이 직접 선별 시 업무 Load 과다"
      },
      {
        title: "To-be",
        description: "이미지 분석을 통해 사람이 직접 확인해야 하는 이미지 수 최소화"
      }
    ],
    keyResponsibilities: [
      {
        title: "PDF 파일에서 이미지 추출 및 전처리",
        details: [
          "선별기기 결과 Report (PDF 파일)에서 이미지 추출",
          "이미지 전처리 및 정규화"
        ]
      },
      {
        title: "이물 검출 이미지 분류 모델 개발",
        details: [
          "Binary Classification (정상/이물 분류)",
          "선별기기 결과를 1차 필터링하는 모델 개발",
          "모델 성능 평가 (정확도, 재현율, F1-score)"
        ]
      }
    ],
    keyFeatures: [
      {
        title: "이물 검출 파이프라인",
        details: [
          "선별기기 결과 → 이미지 선별 모델 1차 필터링 → 사람 최종 선별",
          "PDF Report에서 자동 이미지 추출",
          "Binary Classification 기반 정상/이물 분류"
        ]
      }
    ],
    achievements: [
      "사람이 확인해야 하는 이미지 수 대폭 감소",
      "산터우 공장 등 해외 공장 확대 가능성 확인"
    ],
    challenges: [
      {
        title: "PET Chip 이미지 특성",
        description: "원통형이고 불투명한 PET Chip 특성으로 선별기기 오류값 다수. 이미지 전처리 및 모델 최적화로 해결"
      }
    ],
    learnings: [
      "제조업 도메인 CV 적용: 선별기기 한계를 AI로 보완",
      "Binary Classification 실전: 정밀도와 재현율 균형",
      "PDF 기반 데이터 파이프라인: 비정형 데이터에서 이미지 추출"
    ]
  },
  "naver-hackathon": {
    id: "naver-hackathon",
    title: "네이버 부스트캠프 기업 해커톤",
    subtitle: "기업 평가 챗봇 개발 해커톤",
    period: "2025.01 ~ 2025.02",
    duration: "약 1개월",
    role: "기획, 운영, 평가",
    team: "네이버 부스트캠프",
    description: "네이버 부스트캠프 주최 기업 해커톤에서 기업 평가 챗봇 개발 과제를 기획하고 운영. 참가 팀 멘토링 및 기술 지원, 최종 평가 진행.",
    techStack: {
      aiml: ["LangChain", "RAG", "챗봇"],
      collaboration: ["GitHub", "Notion", "Slack"]
    },
    keyFeatures: [
      {
        title: "해커톤 과제 기획",
        details: [
          "기업 평가 챗봇 과제 설계",
          "평가 기준 수립 (기술성, 창의성, 완성도)",
          "참가 팀 가이드라인 작성"
        ]
      },
      {
        title: "멘토링 및 기술 지원",
        details: [
          "참가 팀 멘토링",
          "기술적 질문 답변",
          "중간 피드백 제공"
        ]
      },
      {
        title: "해커톤 운영 및 평가",
        details: [
          "해커톤 일정 관리",
          "최종 결과 평가",
          "우수 팀 시상"
        ]
      }
    ],
    achievements: [
      "해커톤 과제 기획 및 평가 기준 수립 경험",
      "참가 팀 멘토링으로 기술 지식 공유",
      "해커톤 운영 및 결과 평가 참여"
    ],
    learnings: [
      "해커톤 기획 및 운영 노하우",
      "멘토링 스킬: 기술 지식 효과적 전달",
      "평가 기준 설계: 공정하고 명확한 평가",
      "커뮤니티 기여: 후배 개발자 성장 지원"
    ]
  }
};
