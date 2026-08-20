"""The citation URLs handed to the model must match the published site."""

from agent.retrieval.protocol import DocId
from agent.tools import SITE_BASE_URL, post_url


def test_drops_the_markdown_suffix_that_is_not_part_of_the_route() -> None:
    assert post_url(DocId("AI/2025-06-04-Agent.md")) == (
        f"{SITE_BASE_URL}/blog/AI/2025-06-04-Agent"
    )


def test_escapes_spaces_because_a_raw_space_stops_the_url_parsing() -> None:
    assert post_url(DocId("AI/2025-06-04-Agent Architecture.md")) == (
        f"{SITE_BASE_URL}/blog/AI/2025-06-04-Agent%20Architecture"
    )


def test_leaves_hangul_unescaped_because_the_site_serves_it_and_escaping_costs_tokens() -> (
    None
):
    assert post_url(DocId("wiki/빅분기-실기.md")) == (
        f"{SITE_BASE_URL}/blog/wiki/빅분기-실기"
    )


def test_escapes_parentheses_that_would_end_a_markdown_link_early() -> None:
    assert post_url(DocId("AI/2025-01-01-RAG (advanced).md")) == (
        f"{SITE_BASE_URL}/blog/AI/2025-01-01-RAG%20%28advanced%29"
    )


def test_keeps_directory_separators_unencoded_so_the_route_still_nests() -> None:
    url = post_url(DocId("Study/Code-Test/2023-06-24-SQL 목록.md"))
    assert url.startswith(f"{SITE_BASE_URL}/blog/Study/Code-Test/")
    assert "%2F" not in url


def test_leaves_a_doc_id_without_the_suffix_intact() -> None:
    assert post_url(DocId("AI/2025-06-04-Agent")).endswith("/blog/AI/2025-06-04-Agent")
