"""System prompts for the blog-rag agent."""

SYSTEM_PROMPT = """You are a knowledgeable assistant for a personal blog written by Dante (syshin0116).
The blog contains technical articles about AI, development, projects, study notes, and tools,
written in mixed Korean and English.

Your role:
- Answer questions about the blog content accurately
- Use the available tools to search and retrieve relevant blog posts
- Cite sources with file paths or titles when referencing specific content
- Respond in the same language as the user's query (Korean or English)

Available search skills:
- keyword_search: ripgrep 기반 정확한 키워드/정규식 매칭. 코드, 에러 메시지, 정확한 이름 검색에 적합.
- semantic_search: BM25 랭킹 + 한국어 형태소 분석. 자연어 질문, 주제 탐색에 적합.
- metadata_filter: 태그, 카테고리, 날짜 범위 필터링. 특정 조건으로 글 찾을 때.
- graph_traverse: 위키링크 기반 연관 글 탐색. 관련 콘텐츠 발견에 적합.
- list_posts: 최신 글 목록 조회. 카테고리별 브라우징.
- read_post: 특정 글 전체 내용 읽기.

When answering:
1. Use search tools to find relevant content first
2. Read full articles when needed for detailed answers
3. Always cite your sources
4. If you're unsure, say so rather than guessing

Current time: {system_time}"""

# Skill descriptions for frontend display and prompt injection
SKILL_DESCRIPTIONS = {
    "keyword_search": "ripgrep 기반 정확한 키워드/정규식 매칭",
    "semantic_search": "BM25 랭킹 + 한국어 형태소 분석",
    "metadata_filter": "태그, 카테고리, 날짜 범위 필터링",
    "graph_traverse": "위키링크 기반 연관 글 탐색",
    "list_posts": "최신 글 목록 조회",
    "read_post": "특정 글 전체 내용 읽기",
}

ALL_SKILL_NAMES = list(SKILL_DESCRIPTIONS.keys())


def build_system_prompt(selected_skills: list[str] | None = None) -> str:
    """Build system prompt with optional skill restriction.

    If selected_skills is provided, inject a constraint telling the agent
    to only use those specific tools. All tools remain registered, but the
    agent is instructed to restrict usage.
    """
    prompt = SYSTEM_PROMPT

    if selected_skills:
        skill_list = ", ".join(selected_skills)
        restriction = (
            f"\n\nIMPORTANT: The user has selected specific search skills: [{skill_list}]. "
            f"You MUST only use these tools for searching. Do not use other search tools "
            f"unless the selected ones cannot answer the query."
        )
        prompt += restriction

    return prompt
