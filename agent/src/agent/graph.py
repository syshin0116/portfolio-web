"""Deep Agent — LangGraph standard agent with built-in middleware."""

import os
from pathlib import Path

from deepagents import create_deep_agent
from deepagents.backends import (
    CompositeBackend,
    FilesystemBackend,
    StateBackend,
    StoreBackend,
)

from agent.prompts import SYSTEM_PROMPT
from agent.tools import TOOLS

DEFAULT_MODEL = "anthropic:claude-sonnet-4-6"

# Resolve content path relative to agent/ directory
AGENT_DIR = Path(__file__).resolve().parent.parent.parent  # agent/
CONTENT_DIR = str(
    Path(os.environ.get("BLOG_CONTENT_PATH", str(AGENT_DIR / ".." / "content")))
    .resolve()
)
SKILLS_DIR = str(AGENT_DIR / "skills")


def _build_backend(store=None):
    """Build a CompositeBackend with 3 routes:

    /           → StateBackend (ephemeral working files per thread)
    /memories/  → StoreBackend (persistent cross-thread memory, requires store)
    /blog/      → FilesystemBackend (read-only blog content from content/)
    """

    def factory(rt):
        routes = {
            "/blog/": FilesystemBackend(root_dir=CONTENT_DIR, virtual_mode=True),
        }
        # Only add StoreBackend if store is available
        if store is not None:
            routes["/memories/"] = StoreBackend(rt)

        return CompositeBackend(
            default=StateBackend(rt),
            routes=routes,
        )

    return factory


def create_graph(checkpointer=None, store=None):
    """Factory to build a deep agent.

    The checkpointer is injected at startup (main.py lifespan),
    because create_deep_agent returns a CompiledStateGraph that cannot be
    rebound to a different checkpointer after creation.

    Set the MODEL env var to override the default model.
    """
    model = os.environ.get("MODEL", DEFAULT_MODEL)
    # Normalize "provider/model" → "provider:model" for deepagents compatibility
    if "/" in model and ":" not in model:
        model = model.replace("/", ":", 1)

    return create_deep_agent(
        model=model,
        tools=TOOLS,
        system_prompt=SYSTEM_PROMPT,
        backend=_build_backend(store=store),
        skills=[SKILLS_DIR],
        checkpointer=checkpointer,
        store=store,
    )


def _lazy_graph():
    """Lazy graph for langgraph.json — LangGraph Platform injects its own checkpointer."""
    return create_graph()


graph = _lazy_graph

__all__ = ["graph", "create_graph"]
