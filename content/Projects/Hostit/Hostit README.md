---
title: Hostit README
date: 2025-05-04
tags:
- project
- HostIt
- MCP
- Next.js
- AI
- documentation
draft: false
enableToc: true
description: MCP 도구를 쉽게 호스팅하고 사용할 수 있는 플랫폼 Hostit의 설치 및 사용 가이드
summary: "MCP 도구를 쉽게 호스팅하고 사용할 수 있는 플랫폼 Hostit의 설치 및 사용 가이드"
published: 2025-05-04
modified: 2025-05-04
---
# Host it!

<p align="center">
  <img src="./src/app/assets/hostit.png" alt="Host it! Logo" width="150" />
</p>

## English

Host it! is a platform that allows you to easily host and use MCP (Model Context Protocol) tools. Even non-developers can interact with AI through a chat interface and utilize various tools without any technical knowledge.

### Key Features

- **Easy MCP Tool Hosting**: Host and manage various MCP tools with ease.
- **Intuitive Chat Interface**: Interact with AI and utilize tools through conversation without development knowledge.
- **Tool Management System**: Easily check and manage available tools.
- **API Key Settings**: Manage API keys through a simple settings screen.

### Getting Started

#### Prerequisites

- Node.js 18.0.0 or higher
- npm or yarn

#### Installation

```bash
# Clone the repository
git clone https://github.com/jioni-jioni/web.git
cd web

# Install dependencies
npm install
# or
yarn install

# Run the development server
npm run dev
# or
yarn dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser to see the application.

### How to Use

1. Enter your API key in the **Settings** page.
2. Check and manage MCP tools in the **Tool Management** tab.
3. Utilize tools through conversation with AI in the **Chat Interface**.

### Tech Stack

- [Next.js](https://nextjs.org/) - React framework
- [Tailwind CSS](https://tailwindcss.com/) - UI styling
- [LangChain](https://js.langchain.com/) - AI model and tool integration
- [MCP Adapters](https://github.com/langchain-ai/langchainjs/tree/main/libs/langchain-mcp-adapters) - MCP tool integration

---

## 한국어

Host it!은 MCP(Model Context Protocol) 도구를 손쉽게 호스팅하고 사용할 수 있는 플랫폼입니다. 개발자가 아니더라도 일반 사용자도 채팅 인터페이스를 통해 쉽게 AI와 상호작용하며 다양한 도구를 활용할 수 있습니다.

### 주요 기능

- **간편한 MCP 도구 호스팅**: 다양한 MCP 도구를 쉽게 호스팅하고 관리할 수 있습니다.
- **직관적인 채팅 인터페이스**: 개발 지식 없이도 AI와 대화하며 도구를 활용할 수 있습니다.
- **도구 관리 시스템**: 사용 가능한 도구를 쉽게 확인하고 관리할 수 있습니다.
- **API 키 설정**: 간편한 설정 화면을 통해 API 키를 관리할 수 있습니다.

### 시작하기

#### 필수 조건

- Node.js 18.0.0 이상
- npm 또는 yarn

#### 설치 방법

```bash
# 저장소 복제
git clone https://github.com/jioni-jioni/web.git
cd web

# 의존성 설치
npm install
# 또는
yarn install

# 개발 서버 실행
npm run dev
# 또는
yarn dev
```

브라우저에서 [http://localhost:3000](http://localhost:3000)을 열어 애플리케이션을 확인할 수 있습니다.

### 사용 방법

1. **설정 페이지**에서 API 키를 입력합니다.
2. **도구 관리** 탭에서 사용할 MCP 도구를 확인하고 관리합니다.
3. **채팅 인터페이스**를 통해 AI와 대화하며 도구를 활용합니다.

### 기술 스택

- [Next.js](https://nextjs.org/) - React 프레임워크
- [Tailwind CSS](https://tailwindcss.com/) - UI 스타일링
- [LangChain](https://js.langchain.com/) - AI 모델 및 도구 통합
- [MCP Adapters](https://github.com/langchain-ai/langchainjs/tree/main/libs/langchain-mcp-adapters) - MCP 도구 통합

## License / 라이선스

This project is distributed under the MIT license.  
이 프로젝트는 MIT 라이선스에 따라 배포됩니다.
