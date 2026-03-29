"""Deep Agent — LangGraph standard agent with built-in middleware."""

import os

from deepagents import create_deep_agent

from agent.prompts import SYSTEM_PROMPT
from agent.tools import TOOLS

DEFAULT_MODEL = "anthropic:claude-sonnet-4-6"


def create_graph(checkpointer=None, store=None):
    """Factory to build a deep agent.

    The checkpointer is injected at startup (main.py / worker.py lifespan),
    because create_deep_agent returns a CompiledStateGraph that cannot be
    rebound to a different checkpointer after creation.

    Set the MODEL env var to override the default model (e.g. "openai:gpt-5.4").
    """
    model = os.environ.get("MODEL", DEFAULT_MODEL)
    # Normalize "provider/model" → "provider:model" for deepagents compatibility
    if "/" in model and ":" not in model:
        model = model.replace("/", ":", 1)
    return create_deep_agent(
        model=model,
        tools=TOOLS,
        system_prompt=SYSTEM_PROMPT,
        skills=["./skills/"],
        checkpointer=checkpointer,
        store=store,
    )


# For langgraph.json — LangGraph Platform injects its own checkpointer
graph = create_graph()

__all__ = ["graph", "create_graph"]
