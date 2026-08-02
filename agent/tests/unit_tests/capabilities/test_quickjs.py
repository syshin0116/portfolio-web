"""Security and behavior contracts for the bounded native QuickJS capability."""

from __future__ import annotations

import asyncio
import json
from importlib.metadata import version
from types import SimpleNamespace

import pytest
import pytest_asyncio
from aegra_api.services.graph_factory import build_server_runtime
from langchain_core.messages import ToolMessage
from langchain_quickjs import CodeInterpreterMiddleware
from langgraph.prebuilt import ToolRuntime
from langgraph.store.memory import InMemoryStore
from quickjs_rs import Runtime as QuickJSRuntime

from agent.capabilities.quickjs import (
    QUICKJS_MAX_OUTPUT_BYTES,
    QUICKJS_MAX_SOURCE_BYTES,
    QUICKJS_TOOL_NAME,
    BoundedQuickJSMiddleware,
    quickjs_allowed,
    server_quickjs_enabled,
)

RESULT_SCHEMA = "syshin.quickjs.result.v1"


def _server_runtime(permissions, *, context=None):
    user = SimpleNamespace(
        identity="owner",
        display_name="owner",
        is_authenticated=True,
        permissions=permissions,
    )
    return build_server_runtime(
        access_context="threads.create_run",
        store=InMemoryStore(),
        user=user,
        context=context,
    )


def _tool_runtime(tool_call_id: str = "quickjs-call-1") -> ToolRuntime:
    return ToolRuntime(
        state={},
        context=None,
        config={"configurable": {"thread_id": "quickjs-test-thread"}},
        stream_writer=lambda _event: None,
        tool_call_id=tool_call_id,
        store=None,
    )


def _payload(message: ToolMessage) -> dict[str, object]:
    assert isinstance(message.content, str)
    assert len(message.content.encode("utf-8")) <= QUICKJS_MAX_OUTPUT_BYTES
    payload = json.loads(message.content)
    assert payload["schema"] == RESULT_SCHEMA
    return payload


@pytest_asyncio.fixture
async def middleware():
    instance = BoundedQuickJSMiddleware(enabled=True)
    try:
        yield instance
    finally:
        await instance.aclose()


async def _eval(
    middleware: BoundedQuickJSMiddleware,
    code: str,
    *,
    tool_call_id: str = "quickjs-call-1",
) -> ToolMessage:
    assert len(middleware.tools) == 1
    tool = middleware.tools[0]
    assert tool.name == QUICKJS_TOOL_NAME
    assert tool.coroutine is not None
    result = await tool.coroutine(_tool_runtime(tool_call_id), code)
    assert isinstance(result, ToolMessage)
    return result


def test_server_opt_in_is_strict_and_defaults_off(monkeypatch):
    monkeypatch.delenv("QUICKJS_ENABLED", raising=False)
    assert server_quickjs_enabled() is False

    monkeypatch.setenv("QUICKJS_ENABLED", "true")
    assert server_quickjs_enabled() is True

    monkeypatch.setenv("QUICKJS_ENABLED", "false")
    assert server_quickjs_enabled() is False

    for invalid in ("1", "TRUE", "yes", "on", ""):
        monkeypatch.setenv("QUICKJS_ENABLED", invalid)
        with pytest.raises(RuntimeError, match="QUICKJS_ENABLED"):
            server_quickjs_enabled()


@pytest.mark.parametrize("permission", ["admin", "eval"])
def test_only_owner_and_eval_permissions_can_enable_quickjs(permission):
    assert quickjs_allowed(_server_runtime([permission]), server_enabled=True) is True


@pytest.mark.parametrize(
    "permissions",
    [
        [],
        ["anon"],
        ["authenticated"],
        "admin",
        {"admin": True},
        b"admin",
        ["admin", object()],
    ],
)
def test_public_or_malformed_permissions_fail_closed(permissions):
    assert quickjs_allowed(_server_runtime(permissions), server_enabled=True) is False


def test_client_context_cannot_forge_quickjs_tier():
    runtime = _server_runtime(
        [],
        context={
            "permissions": ["admin"],
            "quickjs": True,
            "capability_quickjs": "on",
        },
    )

    assert quickjs_allowed(runtime, server_enabled=True) is False


def test_unauthenticated_runtime_cannot_use_admin_permission():
    runtime = _server_runtime(["admin"])
    runtime.user.is_authenticated = False

    assert quickjs_allowed(runtime, server_enabled=True) is False


async def test_native_tool_is_async_only_and_does_not_retain_call_state(middleware):
    tool = middleware.tools[0]
    assert tool.func is None
    assert tool._injected_args_keys == frozenset({"runtime"})
    with pytest.raises(NotImplementedError, match="does not support sync"):
        tool.invoke({"code": "21 * 2"})

    first = _payload(await _eval(middleware, "globalThis.retained = 42; retained"))
    second = _payload(await _eval(middleware, "typeof retained"))

    assert first == {
        "output": "42",
        "schema": RESULT_SCHEMA,
        "status": "ok",
        "truncated": False,
    }
    assert second["output"] == "undefined"
    assert second["status"] == "ok"


async def test_exact_native_stack_is_imported_and_used_at_runtime(middleware):
    assert version("langchain-quickjs") == "0.3.5"
    assert version("quickjs-rs") == "0.2.5"
    assert isinstance(middleware, CodeInterpreterMiddleware)

    result = _payload(await _eval(middleware, "21 * 2"))
    assert result["output"] == "42"
    slots = list(middleware._registry._slots.values())
    assert len(slots) == 1
    assert isinstance(slots[0].runtime, QuickJSRuntime)
    assert type(slots[0].worker).__module__ == "quickjs_rs.threading"


async def test_aclose_is_idempotent_and_stops_every_native_worker():
    instance = BoundedQuickJSMiddleware(enabled=True)
    result = _payload(await _eval(instance, "21 * 2"))
    assert result["output"] == "42"
    slots = list(instance._registry._slots.values())
    assert len(slots) == 1
    worker_thread = slots[0].worker._thread
    assert worker_thread is not None
    assert worker_thread.is_alive()

    await asyncio.gather(instance.aclose(), instance.aclose())
    await instance.aclose()

    assert instance._registry._slots == {}
    assert not worker_thread.is_alive()


async def test_pure_data_builtins_work_without_any_host_bridge(middleware):
    result = _payload(
        await _eval(
            middleware,
            "JSON.stringify([1, 2, 3].map((value) => value * 2))",
        )
    )

    assert result["status"] == "ok"
    assert result["output"] == "[2,4,6]"


async def test_host_clock_entropy_and_gc_observers_are_non_redefinable(middleware):
    result = _payload(
        await _eval(
            middleware,
            """\
JSON.stringify(await (async () => {
  const attempts = {};
  const tryDefine = (label, target, name, value) => {
    try {
      Object.defineProperty(target, name, {
        value,
        writable: true,
        configurable: true
      });
      attempts[label] = "changed";
    } catch (_error) {
      attempts[label] = "blocked";
    }
  };
  tryDefine("Date", globalThis, "Date", () => 1);
  tryDefine("performance", globalThis, "performance", {now: () => 1});
  tryDefine("Math", globalThis, "Math", {random: () => 1});
  tryDefine("random", Math, "random", () => 1);
  tryDefine("crypto", globalThis, "crypto", {getRandomValues: () => 1});
  tryDefine("WeakRef", globalThis, "WeakRef", () => 1);
  await Promise.resolve();
  return {
    attempts,
    configurable: {
      Date: Object.getOwnPropertyDescriptor(globalThis, "Date").configurable,
      performance:
        Object.getOwnPropertyDescriptor(globalThis, "performance").configurable,
      Math: Object.getOwnPropertyDescriptor(globalThis, "Math").configurable,
      random: Object.getOwnPropertyDescriptor(Math, "random").configurable
    },
    types: {
      Date: typeof Date,
      performance: typeof performance,
      random: typeof Math.random,
      crypto: typeof crypto,
      Temporal: typeof Temporal,
      WeakRef: typeof WeakRef,
      FinalizationRegistry: typeof FinalizationRegistry
    }
  };
})())
""",
        )
    )

    assert result["status"] == "ok"
    output = json.loads(result["output"])
    assert output["attempts"] == {
        "Date": "blocked",
        "performance": "blocked",
        "Math": "blocked",
        "random": "blocked",
        "crypto": "blocked",
        "WeakRef": "blocked",
    }
    assert output["configurable"] == {
        "Date": False,
        "performance": False,
        "Math": False,
        "random": False,
    }
    assert output["types"] == {
        "Date": "undefined",
        "performance": "undefined",
        "random": "undefined",
        "crypto": "undefined",
        "Temporal": "undefined",
        "WeakRef": "undefined",
        "FinalizationRegistry": "undefined",
    }


@pytest.mark.parametrize(
    "source",
    [
        "Date.now()",
        "performance.now()",
        "Math.random()",
        "crypto.getRandomValues(new Uint8Array(1))",
        "new WeakRef({})",
    ],
    ids=["date", "performance", "random", "crypto", "weakref"],
)
async def test_direct_clock_or_entropy_access_is_redacted(middleware, source):
    result = _payload(await _eval(middleware, source))

    assert result == {
        "output": "",
        "schema": RESULT_SCHEMA,
        "status": "invalid_result",
        "truncated": False,
    }


async def test_host_secrets_filesystem_env_network_and_callables_are_unreachable(
    middleware,
    monkeypatch,
):
    secret = "quickjs-host-secret-sentinel"
    monkeypatch.setenv("QUICKJS_ATTACK_SECRET", secret)
    result = _payload(
        await _eval(
            middleware,
            """\
JSON.stringify({
  process: typeof globalThis.process,
  require: typeof globalThis.require,
  fetch: typeof globalThis.fetch,
  task: typeof globalThis.task,
  tools: typeof globalThis.tools,
  console: typeof globalThis.console,
  python: typeof globalThis.Python,
  deno: typeof globalThis.Deno
})
""",
        )
    )

    assert secret not in json.dumps(result)
    assert result["status"] == "ok"
    assert json.loads(result["output"]) == {
        "process": "undefined",
        "require": "undefined",
        "fetch": "undefined",
        "task": "undefined",
        "tools": "undefined",
        "console": "undefined",
        "python": "undefined",
        "deno": "undefined",
    }


@pytest.mark.parametrize(
    "attack",
    [
        "process.env.QUICKJS_ATTACK_SECRET",
        "require('fs').readFileSync('/etc/passwd', 'utf8')",
        "await fetch('http://169.254.169.254/computeMetadata/v1/')",
        "await task({description: 'escape', subagentType: 'general-purpose'})",
        "await tools.readPost({path: '/etc/passwd'})",
        "Python.eval('open(/etc/passwd).read()')",
    ],
    ids=[
        "environment",
        "filesystem",
        "metadata-network",
        "task-bridge",
        "ptc-bridge",
        "python-host",
    ],
)
async def test_direct_host_escape_attempts_return_only_redacted_failure(
    middleware,
    monkeypatch,
    attack,
):
    monkeypatch.setenv("QUICKJS_ATTACK_SECRET", "quickjs-host-secret-sentinel")

    result = _payload(await _eval(middleware, attack))

    assert result == {
        "output": "",
        "schema": RESULT_SCHEMA,
        "status": "invalid_result",
        "truncated": False,
    }
    encoded = json.dumps(result)
    assert "quickjs-host-secret-sentinel" not in encoded
    assert "/etc/passwd" not in encoded
    assert "169.254.169.254" not in encoded


async def test_dynamic_module_load_and_raw_errors_fail_closed(middleware):
    imported = _payload(await _eval(middleware, "await import('fs')"))
    thrown = _payload(
        await _eval(
            middleware,
            "throw new Error('quickjs-redaction-sentinel')",
        )
    )

    for result in (imported, thrown):
        assert result == {
            "output": "",
            "schema": RESULT_SCHEMA,
            "status": "invalid_result",
            "truncated": False,
        }
        assert "stack" not in json.dumps(result).casefold()
        assert "sentinel" not in json.dumps(result)
        assert "'fs'" not in json.dumps(result)


async def test_source_limit_is_exact_utf8_and_spends_no_guest_execution(middleware):
    syntax_bytes = len(b"''.length")
    accepted_body = "가" * ((QUICKJS_MAX_SOURCE_BYTES - syntax_bytes) // 3)
    accepted = f"'{accepted_body}'.length"
    assert len(accepted.encode("utf-8")) <= QUICKJS_MAX_SOURCE_BYTES
    accepted_result = _payload(await _eval(middleware, accepted))
    assert accepted_result["status"] == "ok"

    rejected = f"'{accepted_body}가'.length"
    assert len(rejected.encode("utf-8")) > QUICKJS_MAX_SOURCE_BYTES
    rejected_result = _payload(await _eval(middleware, rejected))
    assert rejected_result == {
        "output": "",
        "schema": RESULT_SCHEMA,
        "status": "invalid_input",
        "truncated": False,
    }

    non_string_result = _payload(await _eval(middleware, None))
    assert non_string_result == {
        "output": "",
        "schema": RESULT_SCHEMA,
        "status": "invalid_input",
        "truncated": False,
    }


async def test_infinite_loop_returns_structured_timeout_and_recovers(middleware):
    result = _payload(await _eval(middleware, "while (true) {}"))
    recovered = _payload(await _eval(middleware, "6 * 7"))

    assert result == {
        "output": "",
        "schema": RESULT_SCHEMA,
        "status": "timeout",
        "truncated": False,
    }
    assert recovered["status"] == "ok"
    assert recovered["output"] == "42"


async def test_allocation_bomb_returns_structured_oom_and_recovers(middleware):
    result = _payload(await _eval(middleware, "new ArrayBuffer(128 * 1024 * 1024)"))
    recovered = _payload(await _eval(middleware, "21 * 2"))

    assert result == {
        "output": "",
        "schema": RESULT_SCHEMA,
        "status": "out_of_memory",
        "truncated": False,
    }
    assert recovered["status"] == "ok"
    assert recovered["output"] == "42"


async def test_stack_bomb_is_redacted_and_next_execution_recovers(middleware):
    result = _payload(
        await _eval(middleware, "(function recurse(){ return recurse(); })()")
    )
    recovered = _payload(await _eval(middleware, "21 * 2"))

    assert result == {
        "output": "",
        "schema": RESULT_SCHEMA,
        "status": "invalid_result",
        "truncated": False,
    }
    assert recovered["status"] == "ok"
    assert recovered["output"] == "42"


async def test_unicode_output_is_truncated_on_serialized_utf8_bytes(middleware):
    result = _payload(await _eval(middleware, "'🚀'.repeat(10000)"))

    assert result["status"] == "truncated"
    assert result["truncated"] is True
    assert isinstance(result["output"], str)
    assert result["output"]
    assert "\ufffd" not in result["output"]


async def test_opaque_guest_handle_is_an_invalid_pure_data_result(middleware):
    result = _payload(await _eval(middleware, "(left, right) => left + right"))

    assert result == {
        "output": "",
        "schema": RESULT_SCHEMA,
        "status": "invalid_result",
        "truncated": False,
    }


async def test_unpaired_guest_unicode_is_a_structured_invalid_result(middleware):
    result = _payload(await _eval(middleware, r"'\ud800'"))

    assert result == {
        "output": "",
        "schema": RESULT_SCHEMA,
        "status": "invalid_result",
        "truncated": False,
    }


async def test_cancelled_execution_propagates_and_releases_native_session(middleware):
    execution = asyncio.create_task(_eval(middleware, "while (true) {}"))
    await asyncio.sleep(0.05)
    execution.cancel()

    with pytest.raises(asyncio.CancelledError):
        await execution

    recovered = _payload(await _eval(middleware, "21 * 2"))
    assert recovered["status"] == "ok"
    assert recovered["output"] == "42"
