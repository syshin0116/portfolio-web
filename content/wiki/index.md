# Wiki Index

## All pages

| Page | Summary | Type | Tags | Sources | Updated |
|------|---------|------|------|---------|---------|
| [[agentic-decision-workflow]] | Agentic decision workflow는 에이전트가 GitHub issue, 리서치, ADR, PR, 리뷰 댓글 반영을 자동화하되 사람은 되돌리기 어려운 선택과 trade-off 승인에 집중하는 운영 패턴이다. 프로젝트→팀→조직으로 지식을 승격할 때 검색 가능한 metadata, source ACL 기반 권한, Second Brain/PARA와 CMDS의 process language를 함께 써야 한다. | pattern | ai, agent, github, adr, decision-making, knowledge-base, automation, workflow, human-in-the-loop | 11 | 2026-05-18 |
| [[ai-기초개념]] | AI 접근 방식은 규칙 기반 기호주의(Symbolism)와 뉴럴 네트워크 기반 연결주의(Connectionism)로 나뉜다. 기호주의는 1980년대 쇠락했고, 연결주의(퍼셉트론 → 딥러닝)가 현재 주류다. 데이터 분석 프로세스 표준인 CRISP-DM도 함께 정리한다. | concept | ai, machine-learning, deep-learning, symbolism, connectionism, neural-network, crisp-dm, data-science | 2 | 2026-04-26 |
| [[blog-seo]] | 블로그를 검색 엔진에 노출시키기 위한 단계별 가이드다. Google Search Console 등록(HTML 파일/메타 태그/Google Analytics 세 가지 소유권 확인 방법), sitemap 제출, robots.txt 설정을 다루며, Quartz 기반 블로그에서의 구체적인 설정 방법을 포함한다. | reference | seo, google-search-console, sitemap, blog, quartz, frontend, search | 1 | 2026-04-26 |
| [[cli-ux-design]] | CLI 도구의 사용성은 기능 추가가 아니라 출력 계약과 동작 규칙의 설계 문제다. TTY 감지로 사람과 기계의 출력 기본값 충돌을 해결하고, 출력 스키마를 API 계약처럼 안정적으로 유지하고, 명령의 의미에 따라 exit code를 분리하면 인간과 에이전트 모두가 예측 가능하게 사용할 수 있는 도구가 된다. | pattern | cli, rust, backend, agent, ux, api-design, unix, pattern | 1 | 2026-04-26 |
| [[clidex]] | Clidex는 AI 에이전트와 인간 모두를 위한 CLI 도구 발견(discovery) 도구로, Rust로 구현된 BM25 기반 검색 엔진을 갖는다. 5,277개 도구 인덱스를 대상으로 퍼지 매칭, 동의어 확장, edit distance 오타 교정을 지원하며, TTY 감지 기반 출력 형식 자동 전환으로 사람과 에이전트가 동일 명령을 공유할 수 있다. | tool | cli, rust, ai, agent, bm25, search, fuzzy-search, edit-distance, testing | 2 | 2026-04-26 |
| [[cursor-project-rules]] | Cursor의 Project Rules 시스템은 .cursor/rules/ 디렉터리에 YAML+Markdown 파일로 파일 패턴별 AI 동작 규칙을 정의한다. 구버전 .cursorrules 파일보다 유연하고 버전 관리가 가능하며, 팀 코딩 컨벤션 표준화에 효과적이다. | tool | cursor, ai, coding-assistant, project-rules, configuration, agent, pattern | 1 | 2026-04-26 |
| [[docker]] | Docker는 OS 커널을 공유하는 앱 수준 가상화 기술이다. VM(수 GB, 하이퍼바이저)과 달리 컨테이너는 수십 MB로 가볍고 빠르다. Docker Compose로 멀티 컨테이너를 오케스트레이션하며, 컨테이너 간 통신 시 localhost 대신 컨테이너 이름을 호스트로 사용한다. | concept | docker, container, devops, virtualization, backend, docker-compose, infrastructure | 3 | 2026-04-26 |
| [[git-basics]] | Git은 Linus Torvalds가 2005년 개발한 분산형 버전 관리 시스템(DVCS)이다. GitHub는 Git 저장소를 클라우드에서 호스팅하는 서비스다. 핵심 명령어(add, commit, push, branch, merge, rebase)와 브랜치 전략을 정리한다. | reference | git, github, version-control, devops, cli, backend | 1 | 2026-04-26 |
| [[github-actions-gcp-cicd]] | GitHub Actions로 코드 push 시 Docker 이미지를 빌드해 Docker Hub에 올리고, SSH로 GCP Compute Engine에 접속해 컨테이너를 재배포하는 CI/CD 파이프라인 패턴이다. GitHub Secrets로 민감 정보를 관리하며, 비용 없이 소규모 프로젝트에 적용 가능하다. | pattern | github-actions, cicd, gcp, docker, devops, automation, cloud, backend | 2 | 2026-04-26 |
| [[langflow]] | LangFlow는 드래그 앤 드롭으로 AI 워크플로우를 구성하는 MIT 라이선스 오픈소스 도구다(68.5k GitHub stars). LangChain 기반으로 RAG, 에이전트, 멀티에이전트 시스템을 시각적으로 설계하고 API로 배포할 수 있으나, 실제로는 low-code 수준의 학습 곡선이 존재한다. | tool | ai, llm, workflow, no-code, low-code, open-source, python, rag, agent, pipeline | 1 | 2026-04-26 |
| [[llm-text-to-sql]] | LLM 기반 Text-to-SQL 시스템을 프로덕션에서 안정적으로 운영하려면 프롬프트 튜닝보다 DB 스키마 품질이 결정적 요소다. 동적 스키마 조회, COMMENT 기반 zero-shot, AST 검증 기반 보안 레이어, 에이전트 위임 방식 self-correction을 조합하면 OLTP 수준 질의에서 높은 정확도를 달성할 수 있다. | pattern | text-to-sql, llm, ai, agent, postgresql, prompt-engineering, evaluation, security | 1 | 2026-04-26 |
| [[llm-wiki]] | LLM Wiki는 원문을 매번 검색해 답하는 RAG 대신, LLM이 raw 소스를 읽어 지속적으로 갱신되는 Markdown 위키를 컴파일·유지하는 패턴이다. CMDS/cmds-llm-wiki 사례처럼 raw source, index/log, Core Context pointer, Queries를 분리하면 프로젝트 지식을 중앙 위키와 연결하면서도 drift를 줄일 수 있다. | pattern | llm, ai, knowledge-base, pkm, markdown, agent, rag, obsidian, automation | 6 | 2026-05-18 |
| [[mac-dev-setup]] | 새 맥북을 받을 때 설치할 필수 도구 목록이다. Homebrew를 기반으로 Raycast, uv(Python), fnm(Node.js), Bun, Docker Desktop을 설치하고, App Store → Homebrew → 공식 웹사이트 순서로 설치를 진행한다. | reference | mac, setup, homebrew, devtools, productivity, python, nodejs, docker | 1 | 2026-04-26 |
| [[misen]] | misen(mise en place)은 AI 워크플로우의 반복 작업을 Block(dict→dict) 단일 인터페이스로 정의하고 연산자로 조합해 어떤 플랫폼에서든 재사용할 수 있게 하는 Python 라이브러리다. 조합의 결과도 Block이므로 중첩이 자유롭고(닫힘 성질), 플랫폼 어댑터가 LangGraph, MCP, FastAPI 변환을 담당한다. | tool | python, ai, llm, pipeline, workflow, open-source, library, agent, operator | 1 | 2026-04-26 |
| [[moonlight-ai]] | Moonlight는 학술 논문 PDF에 AI를 붙여주는 크롬 확장 프로그램이다. 3줄 요약, 자동 하이라이트(기여점/방법론/결과), 드래그 설명, 스마트 인용, Scholar Deep Search(RAG 기반 관련 논문 추천) 기능을 제공하며, 한국 AI 회사 Corca가 개발했다. | tool | ai, research, paper-reading, chrome-extension, rag, llm, productivity | 1 | 2026-04-26 |
| [[object-detection]] | 객체 탐지는 Region Proposal → Feature Extraction → NMS 세 단계 파이프라인으로 구성된다. R-CNN에서 시작해 Fast R-CNN, Faster R-CNN(RPN), SSD, YOLO로 발전하며 속도와 정확도를 개선했다. 성능 지표는 mAP(클래스별 AP의 평균)를 사용한다. | concept | object-detection, deep-learning, computer-vision, ai, cnn, rcnn, yolo, ssd, python | 4 | 2026-04-26 |
| [[obsidian-notion-sync]] | Obsidian은 개인 지식 관리에, Notion은 협업에 각각 강점이 있다. 두 도구 모두 Markdown 기반이므로 'Share to Notion' 플러그인과 Notion API Integration을 사용해 Obsidian 노트를 Notion으로 자동 동기화할 수 있다. | pattern | obsidian, notion, automation, pkm, markdown, workflow, productivity | 1 | 2026-04-26 |
| [[quartz-publishing]] | Quartz는 Obsidian 마크다운 노트를 정적 웹사이트로 변환해 GitHub Pages에 배포하는 오픈소스 SSG다. jackyzha0/quartz를 클론하고, GitHub Actions 워크플로우로 자동 배포를 설정하며, 커스텀 도메인 연결도 지원한다. | pattern | obsidian, quartz, github-pages, blog, publishing, ssg, markdown | 1 | 2026-04-26 |
| [[repo-intelligence-radar]] | Repo intelligence radar는 지식 위키 자체가 아니라 사용자에게 줄 수 있는 별도 외부 정보 소스/인텔리전스 피드다. Public-facing article [[2026-05-18-Repo-Intelligence-Radar]]와 연결되며, 새 레포와 watchlist 레포의 release note, changelog, docs/examples, issue/PR 변화를 digest와 action queue로 제공하고, 필요한 항목만 knowledge base로 승격한다. | pattern | github, open-source, changelog, research, automation, monitoring, pkm, workflow, ai, trend-tracking | 10 | 2026-05-18 |
| [[second-brain-rag]] | Second Brain(개인 지식 데이터베이스)에 RAG를 적용하면 컨텍스트 기반 정보 검색과 AI 응답 품질이 동시에 향상된다. 지식이 충분히 축적되면 개인 경험을 가진 Multi-Agent 구현도 가능하다는 아이디어다. | concept | second-brain, rag, llm, pkm, ai, agent, retrieval | 1 | 2026-05-17 |
| [[sql-relational-db]] | 관계형 DB는 1970년 Edgar Codd가 제안한 테이블 기반 데이터 모델로 현재 가장 널리 사용된다. 계층형 DB와 달리 복잡한 관계를 지원하며 데이터 독립성을 보장한다. MySQL 설치 및 기본 사용법도 포함한다. | concept | sql, database, relational-db, mysql, data, backend, data-science | 1 | 2026-04-26 |
| [[static-site-generators]] | GitHub Pages 배포용 SSG 중 Jekyll(Ruby), Hugo(Go), Hexo(Node.js), Gatsby(React)를 비교한 가이드다. Jekyll은 GitHub Pages 기본 지원으로 초보자에 적합하고, Hugo는 빌드 속도가 가장 빠르며 대규모에 적합하다. Hyde 테마 기반 Jekyll 포트폴리오 블로그 설정 방법도 포함한다. | reference | ssg, blog, jekyll, hugo, gatsby, frontend, github-pages, comparison | 4 | 2026-04-26 |
| [[transformer-architecture]] | Transformer는 RNN의 기울기 소실과 고정 크기 컨텍스트 벡터 문제를 Attention 메커니즘으로 해결한 아키텍처다. Q-K-V Attention으로 입력 시퀀스 전체에서 중요 정보를 동적으로 가중하며, Positional Encoding으로 위치 정보를 보완한다. 학습 시 Teacher Forcing을 사용해 수렴 속도를 높인다. | concept | transformer, attention, nlp, deep-learning, ai, seq2seq, python, tensorflow | 2 | 2026-04-26 |
| [[ubuntu-server-setup]] | Ubuntu 서버를 새로 받을 때 필수 패키지를 한 번에 설치하는 bash 스크립트다. build-essential, git, curl, tmux 등 기본 도구와 함께 Python용 uv, Docker CE(공식 레포지토리 경유)를 설치하고 사용자를 docker 그룹에 추가한다. | reference | ubuntu, server, devops, docker, bash, infrastructure, setup, python | 1 | 2026-04-26 |
| [[vibe-coding]] | Vibe coding은 Andrej Karpathy가 명명한 개발 철학으로, LLM과 AI 에디터에 코드 생성을 완전히 위임하고 개발자는 의도와 방향에 집중하는 방식이다. Cursor + Composer 조합이 대표적 구현 도구이며, 프로토타입과 주말 프로젝트에 효과적이나 프로덕션 코드에서는 코드 이해 부재가 위험 요소다. | concept | ai, coding-assistant, cursor, productivity, llm, vibe-coding, agent, pattern | 1 | 2026-04-26 |
| [[zettelkasten]] | Zettelkasten은 Niklas Luhmann이 개발한 개인 지식 관리 시스템으로, 노트를 수집이 아닌 연결 중심으로 조직한다. 각 노트에 고정 주소를 부여하고 하이퍼텍스트 링크로 이어 '생각의 웹'을 형성하는 것이 핵심이며, 키워드는 저장 분류가 아닌 미래 검색 시점을 기준으로 선택한다. | concept | zettelkasten, pkm, note-taking, second-brain, obsidian, productivity | 1 | 2026-04-26 |
| [[블로그-검색-실험]] | 280개 한국어+영어 혼용 블로그 포스트를 테스트베드로 6가지 검색 방법(Ripgrep, BM25, BM25+Kiwi, 벡터 검색, 메타데이터 필터, 하이브리드 퓨전)의 성능을 비교하는 실험 시리즈다. 교착어 한국어의 형태소 분석 필요성, 다국어 임베딩 모델 선택, 하이브리드 퓨전 전략이 핵심 변수다. | reference | rag, ai, embeddings, bm25, search, vector-search, hybrid-search, korean, experiment, evaluation | 1 | 2026-05-17 |
| [[빅분기-실기]] | 빅데이터분석기사(빅분기) 실기는 1유형(데이터 조작), 2유형(머신러닝 파이프라인), 3유형(통계 검정·회귀)으로 구성된다. pandas 명령어, RandomForest 모델링, 가설검정 절차를 숙지하는 것이 핵심이며 Python 환경에서 시험이 진행된다. | reference | 빅분기, data-analysis, python, pandas, machine-learning, statistics, certification, sklearn | 4 | 2026-04-26 |
| [[정보처리기사]] | 정보처리기사 1과목(소프트웨어 구축)과 3과목(운영체제)의 핵심 개념을 정리한다. SDLC, 개발 방법론(구조적/OOP/애자일), 비용 산정(LOC/COCOMO), UI 설계 원칙, 서버 아키텍처(WEB/WAS/DBMS/CDN), 운영체제 기초를 포함한다. | reference | 정보처리기사, software-engineering, certification, os, ui, backend, sdlc | 7 | 2026-04-26 |

## Sources catalog

| Source | Wiki pages |
|--------|------------|
| content/AI/2026-05-18-Repo-Intelligence-Radar.md | [[repo-intelligence-radar]] |
| content/AI/2026-04-04-블로그-검색-실험-1-실험설계.md | [[블로그-검색-실험]] |
| content/AI/2026-04-19-LLM-Text-to-SQL-실전-가이드.md | [[llm-text-to-sql]] |
| content/Projects/Clidex/03-Search-Quality-Hardening.md | [[clidex]] |
| content/Projects/Clidex/04-CLI-UX-Design.md | [[cli-ux-design]], [[clidex]] |
| content/Projects/misen/2026-04-04-misen-overview.md | [[misen]] |
| content/Study/SeSAC/2023-11-17-딥러닝 영상처리.md | [[object-detection]] |
| content/Study/SeSAC/2023-11-20-딥러닝 영상처리2.md | [[object-detection]] |
| content/Study/SeSAC/2023-11-22-딥러닝 영상처리3.md | [[object-detection]] |
| content/Study/SeSAC/2023-11-23-딥러닝 영상처리4.md | [[object-detection]] |
| content/Study/SeSAC/2023-11-29-Transformers 강의 정리.md | [[transformer-architecture]] |
| content/Study/SeSAC/2023-11-30-Transformers 실습.md | [[transformer-architecture]] |
| content/Study/SeSAC/data-analysis/2023-07-18-SeSAC-데이터 분석 기초-1일차.md | [[ai-기초개념]] |
| content/Study/SeSAC/data-analysis/2023-07-20-SeSAC-SQL로 데이터베이스 다루기-1일차.md | [[sql-relational-db]] |
| content/Study/SeSAC/data-analysis/2023-07-28-SeSAC-인공지능.md | [[ai-기초개념]] |
| content/Study/빅분기/2023-09-22-빅분기.md | [[빅분기-실기]] |
| content/Study/빅분기/2023-11-27-빅분기-실기-1유형.md | [[빅분기-실기]] |
| content/Study/빅분기/2023-11-30-빅분기-실기-2유형.md | [[빅분기-실기]] |
| content/Study/빅분기/2023-12-02-빅분기-실기-3유형.md | [[빅분기-실기]] |
| content/Study/정보처리기사/2023-07-05-소프트웨어 개발 방법론.md | [[정보처리기사]] |
| content/Study/정보처리기사/2023-07-05-소프트웨어 공학.md | [[정보처리기사]] |
| content/Study/정보처리기사/2023-07-08-프로젝트 계획 및 분석.md | [[정보처리기사]] |
| content/Study/정보처리기사/2023-07-11-소프트웨어 설계.md | [[정보처리기사]] |
| content/Study/정보처리기사/2023-07-16-서버 프로그램 구현.md | [[정보처리기사]] |
| content/Study/정보처리기사/2023-07-16-화면 설계.md | [[정보처리기사]] |
| content/Study/정보처리기사/2023-07-21-정처기-3과목-운영체제.md | [[정보처리기사]] |
| content/Tools/2024-01-01-깃 블로그 생성.md | [[static-site-generators]] |
| content/Tools/2024-01-03-Git Blog SSG 비교.md | [[static-site-generators]] |
| content/Tools/2024-01-05-Hugo 블로그 생성 연습.md | [[static-site-generators]] |
| content/Tools/2024-03-09-Obsidian to Notion 자동화.md | [[obsidian-notion-sync]] |
| content/Tools/2024-07-29-Zettelkasten.md | [[zettelkasten]] |
| content/Tools/2024-08-02-Second-Brain-RAG.md | [[second-brain-rag]] |
| content/Tools/2026-03-03-Moonlight-AI-논문-리더-활용법.md | [[moonlight-ai]] |
| content/Tools/Cursor-Project-Rules.md | [[cursor-project-rules]] |
| content/Tools/Docker/2023-05-08-Docker와 VM 차이.md | [[docker]] |
| content/Tools/Docker/2023-11-09-Docker-실습.md | [[docker]] |
| content/Tools/Docker/2024-03-27-Docker Compose에서 Flask와 MySQL 연결 문제.md | [[docker]] |
| content/Tools/Git/2022-09-08-_Github_Github정리.md | [[git-basics]] |
| content/Tools/Git/2023-12-11-Git Blog Themes.md | [[static-site-generators]] |
| content/Tools/Git/2024-11-09-정리-Github CI CD - GCP.md | [[github-actions-gcp-cicd]] |
| content/Tools/Git/2024-11-17-방법-Github CI CD - GCP.md | [[github-actions-gcp-cicd]] |
| content/Tools/LangFlow.md | [[langflow]] |
| content/Tools/Mac/2025-04-18-맥북 초기 세팅.md | [[mac-dev-setup]] |
| content/Tools/Obsidian/Quartz, GitHub Pages 사용하여 Obsidian 노트 배포.md | [[quartz-publishing]] |
| content/Tools/Obsidian/검색 노출 시키는 방법.md | [[blog-seo]] |
| content/Tools/Ubuntu-Server-Setup.md | [[ubuntu-server-setup]] |
| content/Tools/바이브코딩과 커서(Cursor).md | [[vibe-coding]] |
| https://atlan.com/know/llm-wiki-vs-rag-knowledge-base/ | [[llm-wiki]] |
| https://blog.starmorph.com/blog/karpathy-llm-wiki-knowledge-base-guide | [[llm-wiki]] |
| https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f | [[llm-wiki]] |
| https://www.mindstudio.ai/blog/karpathy-llm-wiki-pattern-knowledge-base-without-rag | [[llm-wiki]] |
| https://www.atlassian.com/blog/atlassian-engineering/hula-blog-autodev-paper-human-in-the-loop-software-development-agents | [[agentic-decision-workflow]] |
| https://github.blog/ai-and-ml/automate-repository-tasks-with-github-agentic-workflows/ | [[agentic-decision-workflow]] |
| https://arxiv.org/html/2602.17084 | [[agentic-decision-workflow]] |
| https://aws.amazon.com/blogs/architecture/master-architecture-decision-records-adrs-best-practices-for-effective-decision-making/ | [[agentic-decision-workflow]] |
| https://learn.microsoft.com/en-us/azure/well-architected/architect-role/architecture-decision-record | [[agentic-decision-workflow]] |
| https://adr.github.io/ | [[agentic-decision-workflow]] |
| https://code.claude.com/docs/en/github-actions | [[agentic-decision-workflow]] |
| https://developers.openai.com/cookbook/examples/codex/build_code_review_with_codex_sdk | [[agentic-decision-workflow]] |
| https://github.com/prodbartist/cmds-vault | [[agentic-decision-workflow]], [[llm-wiki]] |
| https://github.com/prodbartist/cmds-vault/blob/main/90.%20Settings/91.%20Skills/cmds-llm-wiki/SKILL.md | [[llm-wiki]] |
| https://fortelabs.com/blog/para/ | [[agentic-decision-workflow]] |
| https://learn.microsoft.com/en-us/azure/search/search-document-level-access-overview | [[agentic-decision-workflow]] |
| https://www.dataquest.io/blog/metadata-filtering-and-hybrid-search-for-vector-databases/ | [[agentic-decision-workflow]] |

| https://docs.github.com/en/rest/repos | [[repo-intelligence-radar]] |
| https://docs.github.com/en/rest/releases | [[repo-intelligence-radar]] |
| https://docs.github.com/en/rest/activity | [[repo-intelligence-radar]] |
| https://github.com/trending | [[repo-intelligence-radar]] |
| https://news.hada.io/ | [[repo-intelligence-radar]] |
| https://github.com/HackerNews/API | [[repo-intelligence-radar]] |
| https://hn.algolia.com/api | [[repo-intelligence-radar]] |
| https://info.arxiv.org/help/api/user-manual.html | [[repo-intelligence-radar]] |
| https://huggingface.co/papers/trending | [[repo-intelligence-radar]] |
