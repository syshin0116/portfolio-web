"""Provider-native, fail-closed input token counting."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx
from langchain.agents.middleware import ModelRequest
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI
from openai import AsyncOpenAI

from agent.identity import is_anonymous_identity

OPENAI_GUEST_MODEL_NAME = "gpt-5.6-luna"
OPENAI_GUEST_MODEL_SPEC = f"openai:{OPENAI_GUEST_MODEL_NAME}"
OPENAI_GUEST_SAFETY_IDENTIFIER_PREFIX = "guest_"
OPENAI_GUEST_SAFETY_IDENTIFIER_LENGTH = 64
# The official catalogue currently publishes only this alias for Luna. Add a
# snapshot here only after OpenAI publishes one and its response metadata is
# captured by a separately reviewed provider-backed test.
OPENAI_GUEST_RESPONSE_MODEL_NAMES = frozenset({OPENAI_GUEST_MODEL_NAME})
OPENAI_GUEST_MAX_OUTPUT_TOKENS = 1_024
OPENAI_GUEST_TIMEOUT_SECONDS = 60.0

_OPENAI_API_BASE_URL = "https://api.openai.com/v1"
_OPENAI_CAPTURE_API_KEY = "capture-only-no-provider-request"
_OPENAI_CAPTURE_MAX_BODY_BYTES = 1024 * 1024
_OPENAI_GUEST_MODEL_FIELDS_SET = frozenset(
    {
        "async_client",
        "cache",
        "client",
        "extra_body",
        "max_retries",
        "max_tokens",
        "metadata",
        "model_kwargs",
        "model_name",
        "openai_api_base",
        "openai_api_key",
        "openai_organization",
        "output_version",
        "profile",
        "reasoning",
        "request_timeout",
        "root_async_client",
        "root_client",
        "store",
        "stream_usage",
        "truncation",
        "use_responses_api",
    }
)
_OPENAI_INPUT_TOKEN_FIELDS = frozenset(
    {
        "conversation",
        "input",
        "instructions",
        "model",
        "parallel_tool_calls",
        "personality",
        "previous_response_id",
        "reasoning",
        "text",
        "tool_choice",
        "tools",
        "truncation",
    }
)
_OPENAI_GENERATION_ONLY_FIELDS = frozenset(
    {
        "max_output_tokens",
        "safety_identifier",
        "store",
        "stream",
    }
)


class InputTokenCountError(RuntimeError):
    """Raised when an exact provider-native input count is unavailable."""


type InputTokenCounter = Callable[[ModelRequest[Any]], Awaitable[int]]


def openai_guest_safety_identifier(identity: object) -> str:
    """Derive one stable, non-identifying OpenAI abuse-monitoring subject."""
    if not is_anonymous_identity(identity):
        raise ValueError("canonical anonymous identity is required")
    digest = hashlib.sha256(
        f"syshin0116-openai-safety-v1\0{identity}".encode()
    ).hexdigest()
    digest_length = OPENAI_GUEST_SAFETY_IDENTIFIER_LENGTH - len(
        OPENAI_GUEST_SAFETY_IDENTIFIER_PREFIX
    )
    return f"{OPENAI_GUEST_SAFETY_IDENTIFIER_PREFIX}{digest[:digest_length]}"


def _is_openai_guest_safety_identifier(value: object) -> bool:
    prefix_length = len(OPENAI_GUEST_SAFETY_IDENTIFIER_PREFIX)
    return bool(
        isinstance(value, str)
        and value.startswith(OPENAI_GUEST_SAFETY_IDENTIFIER_PREFIX)
        and len(value) == OPENAI_GUEST_SAFETY_IDENTIFIER_LENGTH
        and all(character in "0123456789abcdef" for character in value[prefix_length:])
    )


def require_openai_api_key() -> str:
    """Return the server secret only when it is non-empty and whitespace-free."""
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if (
        not api_key
        or api_key != api_key.strip()
        or any(character.isspace() for character in api_key)
    ):
        raise InputTokenCountError(
            "OPENAI_API_KEY is required for OpenAI guest token counting"
        )
    return api_key


@dataclass(slots=True)
class _OpenAIRequestCapture:
    """Capture one local SDK request without permitting provider I/O."""

    payload: dict[str, Any] | None = None
    calls: int = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if (
            self.calls != 1
            or request.method != "POST"
            or request.url.scheme != "https"
            or request.url.host != "api.openai.com"
            or request.url.path != "/v1/responses"
            or len(request.content) > _OPENAI_CAPTURE_MAX_BODY_BYTES
        ):
            raise InputTokenCountError(
                "OpenAI request capture left its single bounded Responses route"
            )
        try:
            payload = json.loads(request.content)
        except (TypeError, ValueError) as exc:
            raise InputTokenCountError(
                "OpenAI request capture produced malformed JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise InputTokenCountError(
                "OpenAI request capture produced a non-object payload"
            )
        self.payload = payload
        return httpx.Response(
            200,
            request=request,
            json={
                "id": "resp_local_capture",
                "object": "response",
                "created_at": 0,
                "status": "completed",
                "error": None,
                "incomplete_details": None,
                "instructions": None,
                "max_output_tokens": OPENAI_GUEST_MAX_OUTPUT_TOKENS,
                "model": OPENAI_GUEST_MODEL_NAME,
                "output": [
                    {
                        "id": "msg_local_capture",
                        "type": "message",
                        "status": "completed",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "captured",
                                "annotations": [],
                            }
                        ],
                    }
                ],
                "parallel_tool_calls": True,
                "previous_response_id": None,
                "reasoning": {
                    "context": "current_turn",
                    "effort": "none",
                    "summary": None,
                },
                "store": False,
                "temperature": None,
                "text": {"format": {"type": "text"}},
                "tool_choice": "auto",
                "tools": [],
                "top_p": None,
                "truncation": "disabled",
                "usage": {
                    "input_tokens": 0,
                    "input_tokens_details": {
                        "cache_write_tokens": 0,
                        "cached_tokens": 0,
                    },
                    "output_tokens": 0,
                    "output_tokens_details": {"reasoning_tokens": 0},
                    "total_tokens": 0,
                },
                "metadata": {},
            },
        )


def _require_exact_openai_guest_model(model: object) -> ChatOpenAI:
    """Reject any model whose generated payload could diverge from the capture."""
    if not isinstance(model, ChatOpenAI):
        raise InputTokenCountError(
            "exact OpenAI input counting requires the server-owned ChatOpenAI model"
        )
    if (
        model.model_name != OPENAI_GUEST_MODEL_NAME
        or model.max_tokens != OPENAI_GUEST_MAX_OUTPUT_TOKENS
        or model.max_retries != 0
        or model.request_timeout != OPENAI_GUEST_TIMEOUT_SECONDS
        or model.use_responses_api is not True
        or model.reasoning != {"context": "current_turn", "effort": "none"}
        or model.store is not False
        or model.streaming is not False
        or model.model_fields_set != _OPENAI_GUEST_MODEL_FIELDS_SET
        or model.stream_usage is not True
        or model.use_previous_response_id is not False
        or model.output_version != "responses/v1"
        or model.cache is not False
        or model.temperature is not None
        or model.top_p is not None
        or model.truncation != "disabled"
        or model.include is not None
        or model.context_management is not None
        or not isinstance(model.extra_body, dict)
        or set(model.extra_body) != {"safety_identifier"}
        or not _is_openai_guest_safety_identifier(
            model.extra_body.get("safety_identifier")
        )
        or model.model_kwargs != {}
        or model.openai_api_base is not None
        or model.openai_organization is not None
        or model.openai_proxy
    ):
        raise InputTokenCountError(
            "the server-owned OpenAI guest model left its exact request contract"
        )
    return model


def _openai_capture_model(
    model: ChatOpenAI,
    *,
    sync_client: httpx.Client,
    async_client: httpx.AsyncClient,
) -> ChatOpenAI:
    """Recreate the reviewed model with documented no-network HTTP clients."""
    return ChatOpenAI(
        model=model.model_name,
        api_key=_OPENAI_CAPTURE_API_KEY,
        max_tokens=model.max_tokens,
        max_retries=model.max_retries,
        timeout=model.request_timeout,
        use_responses_api=model.use_responses_api,
        output_version=model.output_version,
        reasoning=model.reasoning,
        store=model.store,
        truncation=model.truncation,
        cache=model.cache,
        extra_body=dict(model.extra_body),
        http_client=sync_client,
        http_async_client=async_client,
    )


async def _capture_openai_generation_payload(
    request: ModelRequest[Any],
) -> dict[str, Any]:
    """Use ChatOpenAI's public invocation path against an in-memory transport."""
    model = _require_exact_openai_guest_model(request.model)
    if request.response_format is not None or request.model_settings:
        raise InputTokenCountError(
            "OpenAI guest requests cannot add runtime model settings or output formats"
        )

    capture = _OpenAIRequestCapture()
    transport = httpx.MockTransport(capture)
    sync_client = httpx.Client(transport=transport)
    try:
        async with httpx.AsyncClient(transport=transport) as async_client:
            capture_model = _openai_capture_model(
                model,
                sync_client=sync_client,
                async_client=async_client,
            )
            bound_model = (
                capture_model.bind_tools(
                    request.tools,
                    tool_choice=request.tool_choice,
                )
                if request.tools
                else capture_model
            )
            messages: list[BaseMessage] = []
            if request.system_message is not None:
                messages.append(request.system_message)
            messages.extend(request.messages)
            await bound_model.ainvoke(messages)
    except InputTokenCountError:
        raise
    except Exception as exc:
        raise InputTokenCountError(
            "OpenAI request capture failed before provider token counting"
        ) from exc
    finally:
        await asyncio.to_thread(sync_client.close)

    if capture.calls != 1 or capture.payload is None:
        raise InputTokenCountError(
            "OpenAI request capture did not produce exactly one payload"
        )
    return capture.payload


def _openai_input_count_payload(
    generation_payload: dict[str, Any],
) -> dict[str, Any]:
    """Project only token-bearing fields accepted by `/responses/input_tokens`."""
    unknown = (
        set(generation_payload)
        - _OPENAI_INPUT_TOKEN_FIELDS
        - _OPENAI_GENERATION_ONLY_FIELDS
    )
    if unknown:
        raise InputTokenCountError(
            "OpenAI generation payload contains unreviewed request fields"
        )
    if (
        generation_payload.get("model") != OPENAI_GUEST_MODEL_NAME
        or generation_payload.get("max_output_tokens") != OPENAI_GUEST_MAX_OUTPUT_TOKENS
        or generation_payload.get("reasoning")
        != {"context": "current_turn", "effort": "none"}
        or generation_payload.get("store") is not False
        or generation_payload.get("stream") is not False
        or generation_payload.get("truncation") != "disabled"
        or not _is_openai_guest_safety_identifier(
            generation_payload.get("safety_identifier")
        )
        or "input" not in generation_payload
        or "conversation" in generation_payload
        or "previous_response_id" in generation_payload
        or any(
            not isinstance(tool, dict) or tool.get("type") != "function"
            for tool in generation_payload.get("tools", [])
        )
    ):
        raise InputTokenCountError(
            "OpenAI generation payload left the stateless guest contract"
        )
    return {
        key: value
        for key, value in generation_payload.items()
        if key in _OPENAI_INPUT_TOKEN_FIELDS
    }


async def _count_openai_responses_input_tokens(
    payload: dict[str, Any],
    *,
    http_client: httpx.AsyncClient | None = None,
) -> int:
    """Call only OpenAI's official Responses input-token endpoint."""
    api_key = require_openai_api_key()
    if http_client is not None and not isinstance(http_client, httpx.AsyncClient):
        raise TypeError("http_client must be an httpx.AsyncClient")
    try:
        async with AsyncOpenAI(
            api_key=api_key,
            base_url=_OPENAI_API_BASE_URL,
            max_retries=0,
            timeout=OPENAI_GUEST_TIMEOUT_SECONDS,
            http_client=http_client,
        ) as client:
            response = await client.responses.input_tokens.count(**payload)
    except Exception as exc:
        raise InputTokenCountError(
            "OpenAI input token counting failed before generation"
        ) from exc
    return response.input_tokens


async def count_openai_input_tokens(request: ModelRequest[Any]) -> int:
    """Count the exact Responses payload, including final function schemas.

    `ChatOpenAI.get_num_tokens_from_messages` is intentionally not used: its
    local tokenizer does not count the final tool schemas. The same public
    ChatOpenAI bind/invoke path is replayed through a no-network transport,
    then only the official input-count endpoint receives the captured
    token-bearing fields. Any new wire field fails closed until reviewed.
    """
    generation_payload = await _capture_openai_generation_payload(request)
    count_payload = _openai_input_count_payload(generation_payload)
    token_count = await _count_openai_responses_input_tokens(count_payload)
    if (
        not isinstance(token_count, int)
        or isinstance(token_count, bool)
        or token_count < 0
    ):
        raise InputTokenCountError("OpenAI returned a malformed input token count")
    return token_count


async def count_anthropic_input_tokens(request: ModelRequest[Any]) -> int:
    """Count the exact Anthropic request input, including the final tool schemas.

    ``ChatAnthropic`` exposes Anthropic's official token-counting endpoint through
    ``get_num_tokens_from_messages``. The helper is synchronous, so it runs in a
    worker thread while the caller owns the enclosing run-deadline timeout.
    """
    model = request.model
    if not isinstance(model, ChatAnthropic):
        raise InputTokenCountError(
            "exact input counting requires the server-owned ChatAnthropic model"
        )

    messages: list[BaseMessage] = []
    if request.system_message is not None:
        messages.append(request.system_message)
    messages.extend(request.messages)

    count_kwargs: dict[str, Any] = {}
    cache_control = request.model_settings.get("cache_control")
    if cache_control is not None:
        count_kwargs["cache_control"] = cache_control

    try:
        token_count = await asyncio.to_thread(
            model.get_num_tokens_from_messages,
            messages,
            tools=request.tools,
            **count_kwargs,
        )
    except Exception as exc:
        raise InputTokenCountError(
            "Anthropic input token counting failed before generation"
        ) from exc

    if (
        not isinstance(token_count, int)
        or isinstance(token_count, bool)
        or token_count < 0
    ):
        raise InputTokenCountError("Anthropic returned a malformed input token count")
    return token_count


__all__ = [
    "InputTokenCountError",
    "InputTokenCounter",
    "OPENAI_GUEST_MAX_OUTPUT_TOKENS",
    "OPENAI_GUEST_MODEL_NAME",
    "OPENAI_GUEST_RESPONSE_MODEL_NAMES",
    "OPENAI_GUEST_MODEL_SPEC",
    "OPENAI_GUEST_SAFETY_IDENTIFIER_LENGTH",
    "OPENAI_GUEST_SAFETY_IDENTIFIER_PREFIX",
    "OPENAI_GUEST_TIMEOUT_SECONDS",
    "count_anthropic_input_tokens",
    "count_openai_input_tokens",
    "openai_guest_safety_identifier",
    "require_openai_api_key",
]
