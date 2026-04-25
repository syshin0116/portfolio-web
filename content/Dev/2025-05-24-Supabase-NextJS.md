---
title: Supabase-NextJS
date: 2025-05-24
tags:
- Supabase
- NextJS
- project
- Hostit
- project-starter
draft: false
enableToc: true
description: Supabase와 NextJS를 활용한 풀스택 웹 애플리케이션 개발 완전 가이드
summary: "Supabase와 NextJS는 현대적인 풀스택 웹 애플리케이션 개발을 위한 이상적인 조합이다. Supabase는 PostgreSQL 기반 오픈소스 Firebase 대안으로 실시간 데이터베이스, 인증, 스토리지를 제공하며, NextJS는 React 기반 프로덕션 프레임워크다. `npx create-next-app -e with-supabase` 템플릿을 사용하면 Cookie-based 인증, TypeScript, Tailwind CSS가 사전 구성된 프로젝트를 즉시 시작할 수 있다. 이 템플릿에는 모든 기본 설정이 포함되어 있어 복잡한 설정 없이 바로 개발에 집중할 수 있으며, 필요한 부분만 기존 프로젝트에 이식하는 것도 가능하다."
published: 2025-05-24
modified: 2025-05-24
---
## Supabase + NextJS 소개

[[Hostit]]이라는 사이드 프로젝트를 효율적으로 빠르게 진행할겸, 최신 유행하는 기술들을 사용해보려는 취지로 리서치하던 중 이 조합을 찾게 되었다. [[Hostit 개요|Hostit]]은 LangChain의 Model Context Protocol(MCP)을 활용한 AI 도구 관리 플랫폼으로, 사용자 인증, 서버 관리, 실시간 데이터 동기화 등 복잡한 백엔드 기능이 필요한 프로젝트였다.

Supabase와 NextJS의 조합이 매력적인 이유는 복잡한 설정 없이도 강력한 풀스택 애플리케이션을 빠르게 구축할 수 있기 때문이다. 특히 `with-supabase` 템플릿을 사용하면 모든 기본 설정이 이미 완료된 상태로 시작할 수 있어 매우 편리하다.

> [!info] 핵심 장점
> - **즉시 사용 가능**: 템플릿으로 5분 안에 프로젝트 시작
> - **PostgreSQL**: 강력한 SQL 데이터베이스와 실시간 기능
> - **인증 완료**: 이메일/비밀번호, 소셜 로그인 사전 구성
> - **타입 안전성**: TypeScript와 자동 타입 생성 지원
> - **Zero Config**: 복잡한 백엔드 설정 불필요

[[Hostit 구조|Hostit의 구조]]를 보면 MCP 서버 관리, 사용자별 프로필 저장, 실시간 채팅 등 다양한 백엔드 기능이 필요했는데, Supabase의 인증 시스템과 PostgreSQL, 실시간 구독 기능이 이러한 요구사항들을 완벽하게 해결해주었다.

---

## 빠른 시작 방법

### 방법 1: 새 프로젝트 시작 (권장)

가장 쉬운 방법은 Supabase 템플릿을 사용하는 것이다:

```bash
# 템플릿으로 새 프로젝트 생성
npx create-next-app -e with-supabase my-app

# 프로젝트 이동
cd my-app

# 환경 변수 설정
cp .env.example .env.local
```

> [!check] 템플릿에 포함된 것들
> - ✅ NextJS 13+ App Router
> - ✅ TypeScript 설정
> - ✅ Tailwind CSS
> - ✅ Supabase 클라이언트 (브라우저/서버)
> - ✅ 인증 페이지 및 미들웨어
> - ✅ 기본 레이아웃과 컴포넌트

### 방법 2: 기존 프로젝트에 추가

기존 NextJS 프로젝트가 있다면 필요한 부분만 가져올 수 있다:

```bash
# Supabase 라이브러리 설치
npm install @supabase/supabase-js @supabase/ssr

# 템플릿에서 필요한 파일들 복사:
# - utils/supabase/ (클라이언트 설정)
# - middleware.ts (인증 미들웨어)
# - app/login/, app/auth/ (인증 페이지)
```

---

## 기본 설정

### 1. Supabase 프로젝트 생성 및 환경변수 설정

1. [database.new](https://database.new)에서 새 Supabase 프로젝트 생성
2. 프로젝트 설정에서 **Project URL**과 **anon key** 복사
3. 템플릿의 `.env.example` 파일을 복사해서 `.env.local` 생성:

```bash
# 프로젝트 루트에서 실행
cp .env.example .env.local
```

4. `.env.local` 파일을 열어서 실제 값으로 변경:

```bash
# .env.local
NEXT_PUBLIC_SUPABASE_URL=https://your-project-id.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-anon-key-here
```

> [!warning]
> `.env.local` 파일은 Git에 커밋하지 않도록 주의하세요. 이미 `.gitignore`에 포함되어 있습니다.

### 2. 샘플 테이블 생성

SQL Editor에서 실행:

```sql
-- 간단한 테이블 생성
create table posts (
  id bigint primary key generated always as identity,
  title text not null,
  content text,
  created_at timestamp with time zone default now()
);

-- 공개 읽기 권한
alter table posts enable row level security;
create policy "Public can read posts" on posts for select using (true);
```

### 3. 개발 서버 실행 및 확인

```bash
npm run dev
```

브라우저에서 `http://localhost:3000`에 접속하면 다음과 같은 화면을 볼 수 있다:

`.env.local` 설정 전(Supabase 연결 x) 화면:
![](https://i.imgur.com/mqwVlrI.png)

`.env.local` 설정 후:
![](https://i.imgur.com/v6omMHw.png)

![](https://i.imgur.com/W79HKNb.png)

템플릿에는 이미 로그인/회원가입 페이지가 구성되어 있고, 간단한 예제 페이지들도 포함되어 있다.

사실 이메일 인증 과정도 포함되어있지만, 나는 구글, 깃허브, 카카오 등 소셜 인증만 사용할 예정이기 때문에 제거할 예정이다.

### 4. 데이터 사용하기

이미 설정된 클라이언트로 바로 사용 가능:

```typescript
// app/posts/page.tsx
import { createClient } from '@/utils/supabase/server'

export default async function PostsPage() {
  const supabase = await createClient()
  const { data: posts } = await supabase.from('posts').select('*')

  return (
    <div className="p-8">
      <h1 className="text-2xl font-bold mb-4">Posts</h1>
      {posts?.map(post => (
        <div key={post.id} className="mb-4 p-4 border rounded">
          <h2 className="font-semibold">{post.title}</h2>
          <p className="text-gray-600">{post.content}</p>
        </div>
      ))}
    </div>
  )
}
```

---

## 핵심 기능들

### 1. 실시간 구독

데이터 변경사항을 실시간으로 받기:

```typescript
'use client'
import { useEffect, useState } from 'react'
import { createClient } from '@/utils/supabase/client'

export default function RealtimePosts() {
  const [posts, setPosts] = useState([])
  const supabase = createClient()

  useEffect(() => {
    // 실시간 구독
    const subscription = supabase
      .channel('posts')
      .on('postgres_changes', 
        { event: '*', schema: 'public', table: 'posts' },
        (payload) => {
          if (payload.eventType === 'INSERT') {
            setPosts(prev => [payload.new, ...prev])
          }
        }
      )
      .subscribe()

    return () => subscription.unsubscribe()
  }, [])

  return <div>/* posts 렌더링 */</div>
}
```

### 2. 인증 사용하기

템플릿에 이미 모든 인증 기능이 구현되어 있다:

- `/login` - 로그인 페이지
- `/signup` - 회원가입 페이지  
- `middleware.ts` - 보호된 라우트
- 자동 로그인 상태 관리

### 3. 파일 업로드

```typescript
const uploadFile = async (file: File) => {
  const supabase = createClient()
  const { data, error } = await supabase.storage
    .from('uploads')
    .upload(`${Date.now()}_${file.name}`, file)
  
  if (error) throw error
  return data
}
```

---

## 유용한 팁들

### 템플릿에서 필요한 부분만 가져오기

기존 프로젝트에 Supabase를 추가할 때:

1. **클라이언트 설정** - `utils/supabase/` 폴더 복사
2. **인증 미들웨어** - `middleware.ts` 복사  
3. **인증 페이지** - `app/(auth)` 폴더 복사
4. **타입 정의** - `types/` 폴더 복사

### RLS 정책 기본 패턴

```sql
-- 사용자별 데이터 접근
create policy "Users see own data" on profiles
for all using (auth.uid() = user_id);

-- 공개 읽기, 인증 쓰기  
create policy "Public read" on posts
for select using (published = true);

create policy "Auth write" on posts  
for insert to authenticated
with check (auth.uid() = author_id);
```

### 타입 자동 생성

```bash
# 한 번만 설정
npx supabase gen types typescript --project-id YOUR_PROJECT_ID > types/supabase.ts
```

---

## 주의사항

> [!warning] 보안 주의사항
> - RLS 정책 필수 설정 - 테이블마다 적절한 보안 정책 추가
> - Service Role Key는 서버 사이드에만 사용
> - 환경 변수는 `.env.local`에 보관 (`.env.example`은 빈 값으로)

> [!tip] 성능 최적화
> ```typescript
> // ❌ 잘못된 예
> const { data } = await supabase.from('posts').select('*')
> 
> // ✅ 올바른 예  
> const { data } = await supabase
>   .from('posts')
>   .select('id, title, created_at')
>   .limit(10)
> ```

---

## 배포

### Vercel 배포 (권장)

1. GitHub에 코드 푸시
2. [Vercel](https://vercel.com)에서 Import
3. 환경 변수 설정:
   - `NEXT_PUBLIC_SUPABASE_URL`
   - `NEXT_PUBLIC_SUPABASE_ANON_KEY`
4. 자동 배포 완료

템플릿을 사용했다면 배포 설정도 이미 최적화되어 있다.

---

## 결론

`npx create-next-app -e with-supabase` 템플릿은 복잡한 설정 없이 바로 강력한 풀스택 애플리케이션을 시작할 수 있게 해준다. 모든 기본 설정이 이미 완료되어 있고, 필요한 부분만 골라서 기존 프로젝트에 적용하는 것도 가능하다.

> [!success] 이 조합의 핵심 장점
> - **5분 내 프로젝트 시작**: 템플릿으로 즉시 시작 가능
> - **PostgreSQL + 실시간**: 강력한 데이터베이스와 라이브 업데이트
> - **인증 완료**: 로그인/회원가입 페이지 사전 구현
> - **타입 안전성**: TypeScript 완전 지원
> - **배포 간편**: Vercel에 바로 배포 가능

복잡한 설정이나 긴 학습 곡선 없이 바로 개발에 집중할 수 있는 것이 가장 큰 매력이다. 실제로 프로젝트를 시작해보면 왜 이 템플릿이 권장되는지 바로 알 수 있다.

---

## 관련 리소스

### 시작하기
- [Supabase NextJS 퀵스타트](https://supabase.com/docs/guides/getting-started/quickstarts/nextjs) - 공식 가이드
- [Supabase 유튜브 튜토리얼](https://www.youtube.com/watch?v=WdA6b0jPNv4&list=PL5S4mPUpp4OtMhpnp93EFSo42iQ40XjbF&index=4) - 영상으로 학습

### 도구
- [Supabase CLI](https://github.com/supabase/cli) - 타입 생성 및 마이그레이션
- [Vercel](https://vercel.com) - 배포 플랫폼

### 참고
- 템플릿을 먼저 써보고 필요한 부분만 가져오는 것이 가장 효율적
- 공식 문서보다는 실제 템플릿 코드를 보는 게 더 도움됨
- [[Hostit README|Hostit 프로젝트]]에서도 이 조합을 활용해 빠른 개발이 가능했음

