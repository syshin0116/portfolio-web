"""Centralized configuration for search modules."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings

_AGENT_DIR = Path(__file__).resolve().parent.parent.parent.parent  # agent/


class SearchConfig(BaseSettings):
    content_dir: Path = Path(
        os.environ.get(
            "BLOG_CONTENT_PATH",
            str(_AGENT_DIR / ".." / "content"),
        )
    ).resolve()
    rg_binary: str = "rg"
    max_results: int = 20
    snippet_chars: int = 300

    model_config = {"env_prefix": "SEARCH_"}


_config: SearchConfig | None = None


def get_config() -> SearchConfig:
    global _config
    if _config is None:
        _config = SearchConfig()
    return _config
