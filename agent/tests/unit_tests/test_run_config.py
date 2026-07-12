"""Tests for server-owned LangGraph execution configuration."""

from unittest.mock import MagicMock

from api.resource_scope import scoped_checkpoint_thread_id
from api.run_manager import RunManager
from api.run_manager_base import build_graph_config


def _untrusted_config(source: str) -> dict:
    return {
        "configurable": {
            "thread_id": f"{source}-thread",
            "user_id": f"{source}-user",
            "checkpoint_id": f"{source}-checkpoint",
            "checkpoint_ns": f"{source}-namespace",
            "checkpoint_map": {"forged": source},
            "model": source,
        }
    }


def test_build_graph_config_keeps_server_checkpoint_identity_authoritative():
    checkpoint_thread_id = scoped_checkpoint_thread_id("server-user", "server-thread")
    config = build_graph_config(
        "server-thread",
        user_id="server-user",
        assistant_config=_untrusted_config("assistant"),
        run_config=_untrusted_config("run"),
        checkpoint_id="server-checkpoint",
    )

    assert config == {
        "configurable": {
            "thread_id": checkpoint_thread_id,
            "user_id": "server-user",
            "checkpoint_id": "server-checkpoint",
            "model": "run",
        }
    }


def test_build_graph_config_drops_client_checkpoint_when_server_has_none():
    checkpoint_thread_id = scoped_checkpoint_thread_id("server-user", "server-thread")
    config = build_graph_config(
        "server-thread",
        user_id="server-user",
        assistant_config=_untrusted_config("assistant"),
        run_config={"configurable": "invalid"},
    )

    assert config == {
        "configurable": {
            "thread_id": checkpoint_thread_id,
            "user_id": "server-user",
            "model": "assistant",
        }
    }


def test_asyncio_run_manager_uses_shared_config_policy():
    manager = RunManager(MagicMock(), MagicMock(), {})
    checkpoint_thread_id = scoped_checkpoint_thread_id("server-user", "server-thread")

    config = manager._build_config(
        "server-thread",
        user_id="server-user",
        assistant_config=_untrusted_config("assistant"),
        run_config=_untrusted_config("run"),
        checkpoint_id="server-checkpoint",
    )

    assert config["configurable"] == {
        "thread_id": checkpoint_thread_id,
        "user_id": "server-user",
        "checkpoint_id": "server-checkpoint",
        "model": "run",
    }
