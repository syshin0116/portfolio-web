---
title: Google Search Console - 도메인 vs URL 접두어 속성
date: 2025-03-22
tags:
- Google
- Search
- Console
- Domain
- Property
- URL
- Prefix
- Property
- SEO
draft: false
enableToc: true
description: Google Search Console's Domain property covers all URLs, while URL Prefix
  tracks only specific URL prefixes, offering different verification methods.
summary: "When registering a website on Google Search Console, users can choose between Domain and URL Prefix property types. Domain properties encompass all URLs within a domain, regardless of protocol or subdomain, verified through DNS authentication, offering comprehensive data collection. URL Prefix properties track only specific URLs, including the designated protocol and subdomain, verifiable through various methods like HTML file uploads or meta tags. Domain properties are recommended for websites with multiple subdomains or both HTTP and HTTPS versions, aiming for comprehensive SEO analysis. URL Prefix properties suit those managing specific subdomains or analyzing only HTTP or HTTPS versions. It's advisable to primarily register as a Domain property and add URL Prefix properties as needed for both comprehensive and granular data insights."
published: 2025-03-22
modified: 2025-03-22
---


구글 서치 콘솔(Google Search Console)에 웹사이트를 등록할 때 선택할 수 있는 두 가지 주요 속성 유형인 도메인(Domain)과 URL 접두어(URL Prefix)의 차이점은 다음과 같다.

   ![](https://i.imgur.com/2HtKzxz.png)
## 도메인 속성(Domain Property)

도메인 속성은 특정 도메인에 속하는 **모든 URL을 포괄적으로 관리**할 수 있게 해줍니다[3](https://namuscience.com/entry/SEO%EB%A5%BC-%EC%9C%84%ED%95%9C-%EA%B5%AC%EA%B8%80-%EC%84%9C%EC%B9%98-%EC%BD%98%EC%86%94-%EC%86%8D%EC%84%B1-%EC%84%A0%ED%83%9D%EB%B2%95-%EB%8F%84%EB%A9%94%EC%9D%B8-vs-URL-%EC%A0%91%EB%91%90%EC%96%B4). 이 속성의 주요 특징은:

- 프로토콜(http, https)이나 서브도메인(www, m, blog 등)에 관계없이 해당 도메인 내의 모든 페이지가 포함됩니다[3](https://namuscience.com/entry/SEO%EB%A5%BC-%EC%9C%84%ED%95%9C-%EA%B5%AC%EA%B8%80-%EC%84%9C%EC%B9%98-%EC%BD%98%EC%86%94-%EC%86%8D%EC%84%B1-%EC%84%A0%ED%83%9D%EB%B2%95-%EB%8F%84%EB%A9%94%EC%9D%B8-vs-URL-%EC%A0%91%EB%91%90%EC%96%B4)
    
- 도메인 전체의 데이터를 한 번에 수집 가능합니다[3](https://namuscience.com/entry/SEO%EB%A5%BC-%EC%9C%84%ED%95%9C-%EA%B5%AC%EA%B8%80-%EC%84%9C%EC%B9%98-%EC%BD%98%EC%86%94-%EC%86%8D%EC%84%B1-%EC%84%A0%ED%83%9D%EB%B2%95-%EB%8F%84%EB%A9%94%EC%9D%B8-vs-URL-%EC%A0%91%EB%91%90%EC%96%B4)
    
- DNS 인증 방식만을 통해 소유권을 확인합니다[5](https://www.moinnet.com/ko/digital-marketing/google-search-console-add-property/)
    

**포함되는 예시**:

- [https://example.com](https://example.com/)
    
- [http://example.com](http://example.com/)
    
- [https://www.example.com](https://www.example.com/)
    
- [http://m.example.com](http://m.example.com/)
    
- [https://sub.example.com](https://sub.example.com/)[3](https://namuscience.com/entry/SEO%EB%A5%BC-%EC%9C%84%ED%95%9C-%EA%B5%AC%EA%B8%80-%EC%84%9C%EC%B9%98-%EC%BD%98%EC%86%94-%EC%86%8D%EC%84%B1-%EC%84%A0%ED%83%9D%EB%B2%95-%EB%8F%84%EB%A9%94%EC%9D%B8-vs-URL-%EC%A0%91%EB%91%90%EC%96%B4)
    

## URL 접두어 속성(URL Prefix Property)

URL 접두어 속성은 **특정 URL 접두사에 해당하는 페이지만** 포함합니다[7](https://qshop.ai/blog/%EC%9D%B4%EC%BB%A4%EB%A8%B8%EC%8A%A4-%EC%9D%B8%EC%82%AC%EC%9D%B4%ED%8A%B8/%EA%B2%80%EC%83%89%EC%97%94%EC%A7%84-%EC%B5%9C%EC%A0%81%ED%99%94%EB%A5%BC-%EC%9C%84%ED%95%9C-%EA%B5%AC%EA%B8%80%EC%84%9C%EC%B9%98%EC%BD%98%EC%86%94-%EC%82%AC%EC%9A%A9%EB%B2%95/). 이 속성의 주요 특징은:

- 지정한 특정 프로토콜과 서브도메인을 포함한 URL만 추적합니다[3](https://namuscience.com/entry/SEO%EB%A5%BC-%EC%9C%84%ED%95%9C-%EA%B5%AC%EA%B8%80-%EC%84%9C%EC%B9%98-%EC%BD%98%EC%86%94-%EC%86%8D%EC%84%B1-%EC%84%A0%ED%83%9D%EB%B2%95-%EB%8F%84%EB%A9%94%EC%9D%B8-vs-URL-%EC%A0%91%EB%91%90%EC%96%B4)
    
- 예를 들어, [https://www.example.com을](https://www.example.xn--com-of0o/) 등록하면 [http://www.example.com이나](http://www.example.xn--com-dh1ml82g/) [https://example.com은](https://example.xn--com-7e0o/) 포함되지 않습니다[3](https://namuscience.com/entry/SEO%EB%A5%BC-%EC%9C%84%ED%95%9C-%EA%B5%AC%EA%B8%80-%EC%84%9C%EC%B9%98-%EC%BD%98%EC%86%94-%EC%86%8D%EC%84%B1-%EC%84%A0%ED%83%9D%EB%B2%95-%EB%8F%84%EB%A9%94%EC%9D%B8-vs-URL-%EC%A0%91%EB%91%90%EC%96%B4)
    
- HTML 파일 업로드, 메타 태그, Google Analytics, 태그 매니저 등 다양한 방법으로 인증 가능합니다[4](https://contactora.com/domain-or-url-prefix-in-google-search-console-which-to-choose/)[7](https://qshop.ai/blog/%EC%9D%B4%EC%BB%A4%EB%A8%B8%EC%8A%A4-%EC%9D%B8%EC%82%AC%EC%9D%B4%ED%8A%B8/%EA%B2%80%EC%83%89%EC%97%94%EC%A7%84-%EC%B5%9C%EC%A0%81%ED%99%94%EB%A5%BC-%EC%9C%84%ED%95%9C-%EA%B5%AC%EA%B8%80%EC%84%9C%EC%B9%98%EC%BD%98%EC%86%94-%EC%82%AC%EC%9A%A9%EB%B2%95/)
    

**포함되지 않는 예시** ([https://www.example.com](https://www.example.com/) 등록 시):

- [http://www.example.com](http://www.example.com/) (프로토콜이 다름)
    
- [https://example.com](https://example.com/) (서브도메인 없음)
    
- [https://m.example.com](https://m.example.com/) (다른 서브도메인)[3](https://namuscience.com/entry/SEO%EB%A5%BC-%EC%9C%84%ED%95%9C-%EA%B5%AC%EA%B8%80-%EC%84%9C%EC%B9%98-%EC%BD%98%EC%86%94-%EC%86%8D%EC%84%B1-%EC%84%A0%ED%83%9D%EB%B2%95-%EB%8F%84%EB%A9%94%EC%9D%B8-vs-URL-%EC%A0%91%EB%91%90%EC%96%B4)
    

## 두 속성의 주요 차이점

|구분|도메인 속성|URL 접두어 속성|
|---|---|---|
|URL 포함 범위|도메인 전체 (http, https, www, m 등 포함)|특정 URL 접두어만 포함|
|소유권 인증 방법|DNS 인증 (도메인 전체 인증)|HTML 파일 업로드, 메타 태그, 태그 매니저 등|
|SEO 데이터 수집|전체 사이트 데이터를 한 번에 수집 가능|특정 프로토콜과 서브도메인만 가능|
|추천 사용 대상|전체 사이트의 검색 성능을 관리할 때|특정 부분(예: 블로그 서브도메인)만 분석할 때|

## 어떤 속성을 선택해야 할까?

**도메인 속성 선택 권장 상황**:

- 여러 서브도메인(www, m, blog 등)으로 운영 중인 웹사이트
    
- http와 https 버전이 혼재되어 있는 경우
    
- 전체 사이트 트래픽과 SEO 성과를 종합적으로 분석하고 싶을 때[3](https://namuscience.com/entry/SEO%EB%A5%BC-%EC%9C%84%ED%95%9C-%EA%B5%AC%EA%B8%80-%EC%84%9C%EC%B9%98-%EC%BD%98%EC%86%94-%EC%86%8D%EC%84%B1-%EC%84%A0%ED%83%9D%EB%B2%95-%EB%8F%84%EB%A9%94%EC%9D%B8-vs-URL-%EC%A0%91%EB%91%90%EC%96%B4)
    

**URL 접두어 속성 선택 권장 상황**:

- 특정 서브도메인(예: blog.example.com)만 따로 관리하고 싶을 때
    
- http와 https 중 하나만 분석하고 싶을 때
    
- 사이트 일부만 모니터링하고 싶을 때[3](https://namuscience.com/entry/SEO%EB%A5%BC-%EC%9C%84%ED%95%9C-%EA%B5%AC%EA%B8%80-%EC%84%9C%EC%B9%98-%EC%BD%98%EC%86%94-%EC%86%8D%EC%84%B1-%EC%84%A0%ED%83%9D%EB%B2%95-%EB%8F%84%EB%A9%94%EC%9D%B8-vs-URL-%EC%A0%91%EB%91%90%EC%96%B4)
    

가능하다면 **도메인 속성을 기본으로 등록하고, 필요한 경우 URL 접두어 속성을 추가로 등록하는 것이 좋습니다**[3](https://namuscience.com/entry/SEO%EB%A5%BC-%EC%9C%84%ED%95%9C-%EA%B5%AC%EA%B8%80-%EC%84%9C%EC%B9%98-%EC%BD%98%EC%86%94-%EC%86%8D%EC%84%B1-%EC%84%A0%ED%83%9D%EB%B2%95-%EB%8F%84%EB%A9%94%EC%9D%B8-vs-URL-%EC%A0%91%EB%91%90%EC%96%B4). 이렇게 하면 포괄적인 데이터와 세부적인 데이터를 모두 확인할 수 있습니다.

구글 서치 콘솔(Google Search Console)에 웹사이트를 등록할 때 선택할 수 있는 두 가지 주요 속성 유형인 도메인(Domain)과 URL 접두어(URL Prefix)의 차이점은 다음과 같다.

   ![](https://i.imgur.com/2HtKzxz.png)
## 도메인 속성(Domain Property)

도메인 속성은 특정 도메인에 속하는 **모든 URL을 포괄적으로 관리**할 수 있게 해줍니다[3](https://namuscience.com/entry/SEO%EB%A5%BC-%EC%9C%84%ED%95%9C-%EA%B5%AC%EA%B8%80-%EC%84%9C%EC%B9%98-%EC%BD%98%EC%86%94-%EC%86%8D%EC%84%B1-%EC%84%A0%ED%83%9D%EB%B2%95-%EB%8F%84%EB%A9%94%EC%9D%B8-vs-URL-%EC%A0%91%EB%91%90%EC%96%B4). 이 속성의 주요 특징은:

- 프로토콜(http, https)이나 서브도메인(www, m, blog 등)에 관계없이 해당 도메인 내의 모든 페이지가 포함됩니다[3](https://namuscience.com/entry/SEO%EB%A5%BC-%EC%9C%84%ED%95%9C-%EA%B5%AC%EA%B8%80-%EC%84%9C%EC%B9%98-%EC%BD%98%EC%86%94-%EC%86%8D%EC%84%B1-%EC%84%A0%ED%83%9D%EB%B2%95-%EB%8F%84%EB%A9%94%EC%9D%B8-vs-URL-%EC%A0%91%EB%91%90%EC%96%B4)
    
- 도메인 전체의 데이터를 한 번에 수집 가능합니다[3](https://namuscience.com/entry/SEO%EB%A5%BC-%EC%9C%84%ED%95%9C-%EA%B5%AC%EA%B8%80-%EC%84%9C%EC%B9%98-%EC%BD%98%EC%86%94-%EC%86%8D%EC%84%B1-%EC%84%A0%ED%83%9D%EB%B2%95-%EB%8F%84%EB%A9%94%EC%9D%B8-vs-URL-%EC%A0%91%EB%91%90%EC%96%B4)
    
- DNS 인증 방식만을 통해 소유권을 확인합니다[5](https://www.moinnet.com/ko/digital-marketing/google-search-console-add-property/)
    

**포함되는 예시**:

- [https://example.com](https://example.com/)
    
- [http://example.com](http://example.com/)
    
- [https://www.example.com](https://www.example.com/)
    
- [http://m.example.com](http://m.example.com/)
    
- [https://sub.example.com](https://sub.example.com/)[3](https://namuscience.com/entry/SEO%EB%A5%BC-%EC%9C%84%ED%95%9C-%EA%B5%AC%EA%B8%80-%EC%84%9C%EC%B9%98-%EC%BD%98%EC%86%94-%EC%86%8D%EC%84%B1-%EC%84%A0%ED%83%9D%EB%B2%95-%EB%8F%84%EB%A9%94%EC%9D%B8-vs-URL-%EC%A0%91%EB%91%90%EC%96%B4)
    

## URL 접두어 속성(URL Prefix Property)

URL 접두어 속성은 **특정 URL 접두사에 해당하는 페이지만** 포함합니다[7](https://qshop.ai/blog/%EC%9D%B4%EC%BB%A4%EB%A8%B8%EC%8A%A4-%EC%9D%B8%EC%82%AC%EC%9D%B4%ED%8A%B8/%EA%B2%80%EC%83%89%EC%97%94%EC%A7%84-%EC%B5%9C%EC%A0%81%ED%99%94%EB%A5%BC-%EC%9C%84%ED%95%9C-%EA%B5%AC%EA%B8%80%EC%84%9C%EC%B9%98%EC%BD%98%EC%86%94-%EC%82%AC%EC%9A%A9%EB%B2%95/). 이 속성의 주요 특징은:

- 지정한 특정 프로토콜과 서브도메인을 포함한 URL만 추적합니다[3](https://namuscience.com/entry/SEO%EB%A5%BC-%EC%9C%84%ED%95%9C-%EA%B5%AC%EA%B8%80-%EC%84%9C%EC%B9%98-%EC%BD%98%EC%86%94-%EC%86%8D%EC%84%B1-%EC%84%A0%ED%83%9D%EB%B2%95-%EB%8F%84%EB%A9%94%EC%9D%B8-vs-URL-%EC%A0%91%EB%91%90%EC%96%B4)
    
- 예를 들어, [https://www.example.com을](https://www.example.xn--com-of0o/) 등록하면 [http://www.example.com이나](http://www.example.xn--com-dh1ml82g/) [https://example.com은](https://example.xn--com-7e0o/) 포함되지 않습니다[3](https://namuscience.com/entry/SEO%EB%A5%BC-%EC%9C%84%ED%95%9C-%EA%B5%AC%EA%B8%80-%EC%84%9C%EC%B9%98-%EC%BD%98%EC%86%94-%EC%86%8D%EC%84%B1-%EC%84%A0%ED%83%9D%EB%B2%95-%EB%8F%84%EB%A9%94%EC%9D%B8-vs-URL-%EC%A0%91%EB%91%90%EC%96%B4)
    
- HTML 파일 업로드, 메타 태그, Google Analytics, 태그 매니저 등 다양한 방법으로 인증 가능합니다[4](https://contactora.com/domain-or-url-prefix-in-google-search-console-which-to-choose/)[7](https://qshop.ai/blog/%EC%9D%B4%EC%BB%A4%EB%A8%B8%EC%8A%A4-%EC%9D%B8%EC%82%AC%EC%9D%B4%ED%8A%B8/%EA%B2%80%EC%83%89%EC%97%94%EC%A7%84-%EC%B5%9C%EC%A0%81%ED%99%94%EB%A5%BC-%EC%9C%84%ED%95%9C-%EA%B5%AC%EA%B8%80%EC%84%9C%EC%B9%98%EC%BD%98%EC%86%94-%EC%82%AC%EC%9A%A9%EB%B2%95/)
    

**포함되지 않는 예시** ([https://www.example.com](https://www.example.com/) 등록 시):

- [http://www.example.com](http://www.example.com/) (프로토콜이 다름)
    
- [https://example.com](https://example.com/) (서브도메인 없음)
    
- [https://m.example.com](https://m.example.com/) (다른 서브도메인)[3](https://namuscience.com/entry/SEO%EB%A5%BC-%EC%9C%84%ED%95%9C-%EA%B5%AC%EA%B8%80-%EC%84%9C%EC%B9%98-%EC%BD%98%EC%86%94-%EC%86%8D%EC%84%B1-%EC%84%A0%ED%83%9D%EB%B2%95-%EB%8F%84%EB%A9%94%EC%9D%B8-vs-URL-%EC%A0%91%EB%91%90%EC%96%B4)
    

## 두 속성의 주요 차이점

|구분|도메인 속성|URL 접두어 속성|
|---|---|---|
|URL 포함 범위|도메인 전체 (http, https, www, m 등 포함)|특정 URL 접두어만 포함|
|소유권 인증 방법|DNS 인증 (도메인 전체 인증)|HTML 파일 업로드, 메타 태그, 태그 매니저 등|
|SEO 데이터 수집|전체 사이트 데이터를 한 번에 수집 가능|특정 프로토콜과 서브도메인만 가능|
|추천 사용 대상|전체 사이트의 검색 성능을 관리할 때|특정 부분(예: 블로그 서브도메인)만 분석할 때|

## 어떤 속성을 선택해야 할까?

**도메인 속성 선택 권장 상황**:

- 여러 서브도메인(www, m, blog 등)으로 운영 중인 웹사이트
    
- http와 https 버전이 혼재되어 있는 경우
    
- 전체 사이트 트래픽과 SEO 성과를 종합적으로 분석하고 싶을 때[3](https://namuscience.com/entry/SEO%EB%A5%BC-%EC%9C%84%ED%95%9C-%EA%B5%AC%EA%B8%80-%EC%84%9C%EC%B9%98-%EC%BD%98%EC%86%94-%EC%86%8D%EC%84%B1-%EC%84%A0%ED%83%9D%EB%B2%95-%EB%8F%84%EB%A9%94%EC%9D%B8-vs-URL-%EC%A0%91%EB%91%90%EC%96%B4)
    

**URL 접두어 속성 선택 권장 상황**:

- 특정 서브도메인(예: blog.example.com)만 따로 관리하고 싶을 때
    
- http와 https 중 하나만 분석하고 싶을 때
    
- 사이트 일부만 모니터링하고 싶을 때[3](https://namuscience.com/entry/SEO%EB%A5%BC-%EC%9C%84%ED%95%9C-%EA%B5%AC%EA%B8%80-%EC%84%9C%EC%B9%98-%EC%BD%98%EC%86%94-%EC%86%8D%EC%84%B1-%EC%84%A0%ED%83%9D%EB%B2%95-%EB%8F%84%EB%A9%94%EC%9D%B8-vs-URL-%EC%A0%91%EB%91%90%EC%96%B4)
    

가능하다면 **도메인 속성을 기본으로 등록하고, 필요한 경우 URL 접두어 속성을 추가로 등록하는 것이 좋습니다**[3](https://namuscience.com/entry/SEO%EB%A5%BC-%EC%9C%84%ED%95%9C-%EA%B5%AC%EA%B8%80-%EC%84%9C%EC%B9%98-%EC%BD%98%EC%86%94-%EC%86%8D%EC%84%B1-%EC%84%A0%ED%83%9D%EB%B2%95-%EB%8F%84%EB%A9%94%EC%9D%B8-vs-URL-%EC%A0%91%EB%91%90%EC%96%B4). 이렇게 하면 포괄적인 데이터와 세부적인 데이터를 모두 확인할 수 있습니다.