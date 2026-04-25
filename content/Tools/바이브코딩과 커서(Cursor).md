---
title: 바이브코딩과 커서(Cursor)
date: 2025-06-02
tags:
- 데블챌
- 데이터블로그
- 챌린지
- 바이브코딩
- Cursor
- AI코딩
- 개발도구
draft: false
enableToc: true
description: 바이브코딩이란 무엇인지, 그리고 AI 코딩 도구인 Cursor를 활용하는 방법과 사용 후기에 대한 글이다.
summary: "바이브코딩은 코딩에 대한 즐거움과 몰입을 중시하는 개발 철학으로, AI 도구를 활용하여 개발 생산성을 높이는 방식이다. Cursor는 이러한 바이브코딩을 지원하는 AI 코딩 도구로, VS Code 기반에 강력한 AI 기능을 더해 개발자 경험을 향상시킨다. 업스테이지에서는 많은 개발자가 Cursor를 활용해 생산성을 높이고 있다."
published: 2025-06-02
modified: 2025-06-02
---
> [!info]
> 이 글은 [[데블챌 데이터 블로그 챌린지]] 참여 글입니다.

## 바이브코딩이란?

바이브코딩(Vibe Coding)은 단순히 코드를 작성하는 것을 넘어 개발 과정에서의 몰입과 즐거움을 중요시하는 개발 철학이다. 전통적인 코딩 방식에서는 구문 오류, 디버깅, 반복적인 작업 등으로 인해 개발의 흐름이 끊기는 경우가 많았다. 바이브코딩은 이러한 방해 요소를 최소화하고, 개발자가 창의적인 문제 해결과 설계에 집중할 수 있도록 한다.

바이브코딩은 전 Tesla AI 디렉터이자 OpenAI의 설립 멤버인 Andrej Karpathy가 처음 사용한 용어로, "코딩에 별로 공수를 들이지 않고 LLM에게 다 시켜서 바이브대로 간다"는 의미를 담고 있다. 이것이 가능해진 이유는 Cursor와 같은 도구가 발전했고, 최근 LLM 모델들의 코딩 능력이 크게 향상되었기 때문이다.

> [!info] Andrej Karpathy: 
> "There's a new kind of coding I call "vibe coding", where you fully give in to the vibes, embrace exponentials, and forget that the code even exists. It's possible because the LLMs (e.g. Cursor Composer w Sonnet) are getting too good. Also I just talk to Composer with SuperWhisper so I barely even touch the keyboard. I ask for the dumbest things like "decrease the padding on the sidebar by half" because I'm too lazy to find it. I "Accept All" always, I don't read the diffs anymore. When I get error messages I just copy paste them in with no comment, usually that fixes it. The code grows beyond my usual comprehension, I'd have to really read through it for a while. Sometimes the LLMs can't fix a bug so I just work around it or ask for random changes until it goes away. It's not too bad for throwaway weekend projects, but still quite amusing. I'm building a project or webapp, but it's not really coding - I just see stuff, say stuff, run stuff, and copy paste stuff, and it mostly works."

바이브코딩은 개발자가 AI 도구와 협업하여 코드를 작성하는 방식을 의미한다. 여기서 '바이브(Vibe)'는 작업의 흐름이나 집중 상태를 뜻하며, AI가 반복적인 로직 구현, 구문 검토, 오류 수정 등을 지원해 개발자가 창의적 문제 해결에 집중할 수 있도록 돕는 개념이다. 개발자가 AI 코딩 에이전트와 자연어로 대화하며 원하는 프로그램을 설명하면, AI가 코딩을 통해 이를 구현한다.

바이브코딩의 주요 특징은 다음과 같다:
- 몰입감 있는 코딩 경험 추구
- AI 도구를 활용한 반복 작업 자동화
- 개발자의 의도와 생각을 코드로 빠르게 구현
- 코드 작성보다 문제 해결과 설계에 집중
### 바이브코딩의 장점

- **생산성 향상**: 반복적인 코드 작성이 자동화되어 **개발 속도** 크게 향상된다.
- **진입 장벽 감소**: 프로그래밍 경험이 적은 사람도 복잡한 소프트웨어 개발이 가능해진다.
- **코드 일관성 유지**: AI가 제공하는 코드는 일관된 스타일과 패턴을 유지할 수 있다.
- **지식 격차 해소**: 최신 라이브러리나 프레임워크에 대한 지식 부족 시에도 효율적인 개발이 가능하다.
- **프로토타이핑 가속화**: 아이디어에서 실제 구현까지 시간이 대폭 단축된다.


#### 바이브코딩 경험담: 새로운 기술 스택 도전기

나는 Java 기반의 Spring 웹프레임워크와 Python 기반의 FastAPI, Flask 등을 주로 사용해본 경험이 있다. 하지만 바이브코딩을 통해 처음으로 NextJS와 React를 시도해볼 수 있었다. 이전에는 생소했던 이 기술 스택을 사용하여 CI/CD 설정부터 환경 구성, 그리고 최종 배포까지 한 번에 완료할 수 있었다.

특히 프론트엔드 개발에 있어서는 기본적으로 HTML, CSS, JavaScript만 알고 있었는데, Cursor 에이전트와의 협업(때로는 싸움처럼 느껴지기도 했다)을 통해 컴포넌트 생성 및 관리, 상태 관리, SSR(Server-Side Rendering), CSR(Client-Side Rendering) 등의 복잡한 개념 익히면서 동시에 실제 구현해볼 수 있었다. 

회사에서 진행한 프로젝트는 보안상 공개할 수 없지만, 현재 비슷한 방식으로 개발 중인 프로젝트로 [HostIt](https://hostit-web.vercel.app/)이 있다. HostIt은 누구나 쉽게 MCP 도구를 조합해보고, 사용하고, 공유할 수 있는 오픈 소스 플랫폼이다. 바이브코딩이 아니었다면, 이러한 새로운 기술 영역에 도전하는 것이 훨씬 더 어려웠을 것이다.

HostIt 랜딩페이지:

![](https://i.imgur.com/Zg7JMSX.png)


### 바이브코딩의 단점

![](https://i.imgur.com/eNUbD6f.png)


- **개발자의 주도적인 창의성 저하 가능성**: AI에 과도하게 의존할 경우 문제 해결 능력이 약화될 수 있다.
- **AI에 대한 과도한 의존성**: 기본 원리를 이해하지 못한 채 AI에만 의존하게 될 우려가 있다.
- **코드 품질과 보안 문제**: AI가 생성한 코드에 품질 문제나 보안 취약점이 존재할 가능성이 있다.
- **코드 작동 원리에 대한 깊이 있는 이해 부족**: 생성된 코드의 동작 원리를 완전히 파악하지 못할 수 있다.



## Cursor: AI 기반 코딩 도구

![](https://media.beehiiv.com/cdn-cgi/image/fit=scale-down,format=auto,onerror=redirect,quality=80/uploads/asset/file/4d55a7c5-055b-4429-91a9-fc5a7717b22e/Court_Rules_Against_AI_Artwork___1_.gif?t=1725288411)


Cursor는 바이브코딩을 실현할 수 있는 대표적인 AI 코딩 도구이다. VS Code를 기반으로 하면서 강력한 AI 기능을 통합하여, 개발자가 코드를 더 빠르고 효율적으로 작성할 수 있도록 지원한다. 

GitHub Copilot과 같은 1세대 코딩 어시스턴트와 달리, Cursor는 훨씬 더 강력하고 폭넓은 기능을 제공한다. Copilot이 주로 간단한 자동 완성과 코드 제안에 초점을 맞췄다면, Cursor는 전체 프로젝트 컨텍스트를 이해하고 다양한 파일 간의 관계를 파악하여 더 정교한 코드 생성 및 수정이 가능하다.

업스테이지의 하현수 개발자님은 Cursor가 VS Code의 오픈소스 버전을 포크하여 만들어졌기 때문에 VS Code 사용자들이 익숙한 환경에서 바로 사용할 수 있다고 설명한다. 테마, 익스텐션, 키바인딩 등 기존 설정을 모두 그대로 가져와 사용할 수 있어 진입 장벽이 낮은 것이 큰 장점이다.

### Cursor의 주요 기능

1. **AI 코드 생성 및 완성**
   - 자연어 명령으로 코드 블록 생성
   - 맥락을 이해한 코드 자동 완성
   - 다양한 프로그래밍 언어 지원

2. **멀티파일 컨텍스트 지원**
   - 폴더 전체를 AI에게 참조시킬 수 있는 '@' 멘션 기능
   - 여러 파일에 걸친 코드 이해 및 수정
   - 프로젝트 전반의 맥락을 고려한 코드 생성

3. **리팩토링 및 디버깅 지원**
   - 코드 개선 제안
   - 잠재적 버그 식별
   - 성능 최적화 제안

4. **페어 프로그래밍 경험**
   - AI와의 대화형 코딩
   - 코드 설명 및 문서화 지원
   - 학습과 개발을 동시에

## 바이브코딩 관련 주요 도구들

바이브코딩을 지원하는 도구들은 Cursor 외에도 다양하게 있다:

- **GitHub Copilot**: GitHub와 OpenAI가 공동 개발한 AI 코딩 도구로, 다양한 IDE에 통합하여 사용할 수 있다.
- **Codeium**: 다양한 IDE에 통합하여 사용할 수 있는 AI 코딩 도우미로, 무료 버전도 제공한다.
- **Tabnine**: 머신러닝 기반 코드 자동 완성 도구로, 작업 패턴을 학습하여 정확한 제안을 제공한다.

## 업스테이지의 Cursor 활용 사례

업스테이지에서는 많은 개발자들이 Cursor를 활용하여 생산성을 크게 향상시키고 있다. 하현수 개발자님의 내부 인터뷰 결과에 따르면, 개발자들의 Cursor에 대한 업무 의존도는 상당히 높은 편이다. 5점 만점에 4~5점을 준 사용자가 대다수였으며, 일부는 "Cursor 없으면 차라리 연차를 쓰겠다"는 농담을 할 정도로 의존도가 높았다.

업스테이지 개발자들이 Cursor를 활용하는 주요 사례들은 다음과 같다:
- 간단한 POC나 데모 빠르게 구현
- 오픈소스 분석 및 수정 (코드 이해 없이도 가능)
- 러스트와 같이 익숙하지 않은 언어로 작업할 때
- README와 같은 문서 작성
- 테스트 코드 자동 생성
- 반복적인 API 연동 작업 자동화

## Cursor 활용 수준에 따른 단계별 분류


업스테이지의 하현수 개발자님은 Cursor 사용 수준을 5단계로 분류했다:

![](https://i.imgur.com/iU0HQDl.png)


## Cursor 고급 기능 활용하기

### 1. Cursor Rules

Cursor Rules은 Cursor가 사용하는 LLM에게 전달되는 프롬프트로, 프로젝트의 기술 스택, 폴더 구조, 코딩 컨벤션 등을 명시할 수 있다. 두 가지 종류의 Rules이 있다:

- **유저 Rules**: 계정에 로그인하면 모든 프로젝트에 적용되는 개인 설정
- **프로젝트 Rules**: .cursor-rules 또는 .mdc 파일을 통해 특정 프로젝트에만 적용되는 설정

팀 단위로 프로젝트 Rules을 Git 저장소에 포함시키면 모든 팀원이 동일한 프롬프트가 적용된 환경에서 작업할 수 있어, 코드 일관성을 유지하는 데 도움이 된다. GitHub에는 "awesome-cursor-rules"라는 저장소도 있어, 다양한 프로그래밍 언어나 프레임워크별 좋은 Rule 템플릿을 찾아볼 수 있다.

### 2. .cursor-ignore

Cursor는 코드베이스를 이해하기 위해 각 코드 파일을 인덱싱하는데, 불필요한 파일이나 데이터 파일이 인덱싱되면 부정확한 답변이 생성될 수 있다. .cursor-ignore 파일을 만들어 .gitignore와 유사한 방식으로 특정 파일이나 패턴을 제외하면 정확도를 높일 수 있다.

### 3. 폴더 멘션(@)

Cursor의 가장 유용한 기능 중 하나는 '@' 기호를 사용한 폴더 멘션 기능이다. 이를 통해 AI에게 필요한 컨텍스트를 쉽게 제공할 수 있다.

예를 들어, @폴더명 형태로 폴더를 통째로 컨텍스트에 추가하고 "이 에어플로우 DAG에서 문제 생기면 슬랙 알람 보내기 기능을 추가하고 싶어"라고 요청하면, Cursor는 해당 폴더 내에서 관련 코드를 찾아 슬랙 알람 기능을 추가해준다.

### 4. Docs 멘션

공식 문서를 바탕으로 답변을 생성하도록 @docs 멘션을 사용할 수 있다. 이를 통해 할루시네이션(환각)을 줄이고 최신 라이브러리에 맞는 코드를 생성할 수 있다. 새 문서를 추가하려면 "Add New Doc" 버튼을 눌러 문서 링크와 프리픽스를 입력하면 된다.

### 5. Web 멘션과 URL 멘션

개발 중 정보가 필요할 때 IDE를 벗어나 검색할 필요 없이, @web 멘션을 통해 Cursor 내에서 웹 검색을 할 수 있다. 또한 @URL 형식으로 특정 웹페이지(예: 기술 블로그)를 컨텍스트로 추가할 수도 있다.

### 6. Cursor 설정 최적화

성능 향상을 위한 몇 가지 중요 설정은 다음과 같다:
- Include Project Structure: 프로젝트 폴더 구조를 자동으로 컨텍스트에 포함 (베타)
- Large Context: 컨텍스트 길이를 증가시켜 더 많은 코드 파일 이해
- Web Search Tool: 모델이 모르는 정보를 웹 검색으로 보완
- 모델 설정: Claude 4.1 또는 Sonnet 3.7 Thinking으로 설정하면 정확도가 크게 향상


나는 Level 3인 것 같다. `@` 기능과 `Agent` 기능을 활발히 사용하는 것은 확실하지만, `cursorrules`는 사용하긴 하되 적극적으로 활용하진 않는 편이다. 또한 `cursorignore`는 지금까지 사용해볼 생각이 없었는데, 큰 프로젝트, 특히 monorepo 구조에서는 AI가 불필요하게 참조하는 파일들을 제한함으로써 실용성을 높이고 유용하게 활용될 수 있을 것 같다.

사실 고백하자면, 이 블로그 글도 커서로 작성하고 있다ㅎㅎ

![](https://i.imgur.com/ucwHctO.png)

## Model Context Protocol (MCP) 활용하기

> [!info]
> MCP에 대한 글 [[MCP(Model Context Protocal)]]

레벨 5 수준의 Cursor 활용은 MCP(Model Context Protocol)를 통해 가능하다. MCP는 엔트로픽(Anthropic)이 제시한 개념으로, LLM이 다양한 애플리케이션과 상호작용할 수 있도록 하는 표준화된 프로토콜이다.

USB-C 포트와 같이, MCP는 LLM 호스트(Cursor, Claude)와 다양한 애플리케이션(슬랙, Gmail, 캘린더 등)을 연결하는 인터페이스 역할을 한다. 이를 통해 AI 에이전트는 필요에 따라 데이터베이스 테이블을 생성하거나 슬랙에 메시지를 보내는 등의 작업을 수행할 수 있다.

특히 이를 활용하면 복잡한 개발 작업도 AI 에이전트가 자동으로 처리할 수 있다.

업스테이지 개발자님은 TaskMaster MCP를 최근 인기 있는 도구로, PM 역할을 수행하며 요구사항 명세서를 받아 작업을 세분화하고 우선순위를 정하는 기능을 제공한다라고 소개하셨지만, 사실 내가 사용해본 결과 체감 효과는 기대했던 것보다 좋지 않았다. 하지만 흥미로운 점은 TaskMaster의 접근 방식이 내가 프로젝트 시작단계에서 하는 방식과 매우 유사하다는 것이다.

나도 프로젝트를 시작할 때 먼저 커서와 대화하며 다음과 같은 문서들을 정리해 둔다:

![](https://i.imgur.com/SEhAd9W.png)

이렇게 문서화해둔 내용을 참고하며 커서로 코딩을 진행하는 방식이 내게는 더 효율적이었다.

오히려 내가 개발자들에게 추천하고 싶은 MCP는 [Context7](https://smithery.ai/server/@upstash/context7-mcp)이다. 이 MCP는 라이브러리나 프레임워크의 최신 문서를 직접 참조할 수 있어 더 정확하고 최신 정보에 기반한 코드를 작성하는 데 도움이 된다.

## 바이브코딩의 미래

바이브코딩은 AI 기술 발전과 함께 새로운 소프트웨어 개발 패러다임으로 자리 잡고 있으며, 앞으로 다음과 같은 방향으로 발전할 것으로 예상된다:

- **도메인별 전문화**: 특정 산업이나 도메인에 최적화된 바이브 코딩 도구들이 등장할 것이다.
- **완전 자동화된 코드 생성**: 설계 단계부터 배포까지 AI가 지원하는 엔드투엔드 개발 환경이 구축될 것이다.
- **교육 방식 변화**: 코딩 교육이 문법 학습에서 AI와의 협업 방식으로 전환될 것이다.
- **새로운 프로그래밍 언어 탄생**: AI와의 상호작용에 최적화된 새로운 프로그래밍 언어가 등장할 가능성이 있다.

## 결론

바이브코딩과 Cursor의 조합은 개발자의 창의성과 AI의 효율성을 결합하여 더 즐겁고 생산적인 코딩 경험을 제공한다. 코드 작성의 반복적이고 지루한 부분은 AI에게 맡기고, 개발자는 더 높은 수준의 문제 해결과 설계에 집중할 수 있게 되었다.

업스테이지의 사례에서 볼 수 있듯이, Cursor의 다양한 기능을 제대로 활용하면 생산성이 크게 향상된다. 특히 레벨 4와 레벨 5 수준으로 Cursor를 활용하는 개발자들은 단순한 코딩 보조 도구를 넘어, AI와 함께 개발하는 새로운 패러다임을 경험하고 있다.

개발자의 업무 트렌드는 매우 빠르게 변화하고 있으며, AI를 잘 활용하여 개인화된 워크플로우를 정의할 수 있는 사람과 그렇지 못한 사람 사이에는 생산성의 압도적인 차이가 발생할 것이다. 코딩 자체에 시간을 줄이고 좋은 구조 설계와 적절한 도구 활용 방법을 끊임없이 고민하는 것이 미래 개발자의 중요한 역량이 될 것이다.

## 참고 자료
- [Cursor 공식 웹사이트](https://cursor.sh/)
- [업스테이지 커서 세미나](https://www.youtube.com/live/-Efpu0hdRMc)
- [Smithery Context7](https://smithery.ai/server/@upstash/context7-mcp) 
- [Vibe-Coding Wikipedia](https://en.wikipedia.org/wiki/Vibe_coding)
- [What is vibe coding?](https://www.ibm.com/think/topics/vibe-coding)