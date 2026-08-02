"""Provider-native, fail-closed input token counting."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
from langchain.agents.middleware import ModelRequest
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI
from openai import AsyncOpenAI, OpenAI

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

OPENAI_API_BASE_URL = "https://api.openai.com/v1"
_OPENAI_ROOT_CLIENT_BASE_URL = f"{OPENAI_API_BASE_URL}/"
OPENAI_ROUTING_ENVIRONMENT_VARIABLES = frozenset(
    {
        "OPENAI_ADMIN_KEY",
        "OPENAI_API_BASE",
        "OPENAI_BASE_URL",
        "OPENAI_CUSTOM_HEADERS",
        "OPENAI_ORGANIZATION",
        "OPENAI_ORG_ID",
        "OPENAI_PROJECT_ID",
        "OPENAI_PROXY",
    }
)
_OPENAI_CAPTURE_API_KEY = "capture-only-no-provider-request"
_OPENAI_CAPTURE_MAX_BODY_BYTES = 1024 * 1024
# This is a deliberately conservative local admission heuristic, not a provider
# tokenization guarantee. OpenAI does not publish a hard maximum for hidden
# Responses framing, so public launch still requires provider billing evidence
# and an account-level hard spend stop.
_OPENAI_INPUT_TOKEN_FRAMING_TOKENS_PER_JSON_NODE = 8
_OPENAI_INPUT_TOKEN_FIXED_FRAMING_TOKENS = 256
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


@dataclass(frozen=True, slots=True)
class PreparedInputTokenCount:
    """One locally prepared provider count with a conservative reservation.

    Preparation must perform no provider I/O. The run ledger atomically reserves
    ``reserved_input_tokens`` before ``count`` may make a billable request.
    """

    reserved_input_tokens: int
    _count: Callable[[], Awaitable[int]] = field(repr=False)
    _verify_generation_request: Callable[[ModelRequest[Any]], Awaitable[None]] = field(
        repr=False
    )

    def __post_init__(self) -> None:
        if (
            not isinstance(self.reserved_input_tokens, int)
            or isinstance(self.reserved_input_tokens, bool)
            or self.reserved_input_tokens < 0
            or not callable(self._count)
            or not callable(self._verify_generation_request)
        ):
            raise ValueError("prepared input count must have a valid reservation")

    async def count(self) -> int:
        """Execute the already-prepared provider count request exactly once."""
        return await self._count()

    async def verify_generation_request(self, request: ModelRequest[Any]) -> None:
        """Fail if the final token-bearing generation request drifted."""
        await self._verify_generation_request(request)


type InputTokenCountPreparer = Callable[
    [ModelRequest[Any]], Awaitable[PreparedInputTokenCount]
]


def _json_node_count(value: Any) -> int:
    if isinstance(value, dict):
        return 1 + len(value) + sum(_json_node_count(item) for item in value.values())
    if isinstance(value, list):
        return 1 + sum(_json_node_count(item) for item in value)
    return 1


def _canonical_openai_input_payload(payload: dict[str, Any]) -> bytes:
    """Return one deterministic byte representation of token-bearing fields."""
    try:
        return json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise InputTokenCountError(
            "OpenAI input-count payload cannot be bounded as canonical JSON"
        ) from exc


def _openai_input_token_reservation(payload: dict[str, Any]) -> int:
    """Return the reviewed local admission reservation for one count payload.

    The value is intentionally larger than visible canonical bytes, but it is a
    defense-in-depth heuristic rather than a documented provider upper bound.
    """
    canonical = _canonical_openai_input_payload(payload)
    nodes = _json_node_count(payload)
    return (
        len(canonical)
        + nodes * _OPENAI_INPUT_TOKEN_FRAMING_TOKENS_PER_JSON_NODE
        + _OPENAI_INPUT_TOKEN_FIXED_FRAMING_TOKENS
    )


def _validated_openai_input_token_count(
    token_count: object,
    *,
    reserved_input_tokens: int,
) -> int:
    if (
        not isinstance(token_count, int)
        or isinstance(token_count, bool)
        or token_count < 0
    ):
        raise InputTokenCountError("OpenAI returned a malformed input token count")
    if token_count > reserved_input_tokens:
        raise InputTokenCountError(
            "OpenAI input token count exceeded the conservative local reservation"
        )
    return token_count


@dataclass(frozen=True, slots=True)
class OpenAIResponsesInputTokenContract:
    """Reviewed request identity for exact Responses input-token counting."""

    model_name: str
    max_output_tokens: int
    timeout_seconds: float
    safety_identifier: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.model_name, str)
            or not self.model_name
            or not isinstance(self.max_output_tokens, int)
            or isinstance(self.max_output_tokens, bool)
            or self.max_output_tokens < 1
            or not isinstance(self.timeout_seconds, (int, float))
            or isinstance(self.timeout_seconds, bool)
            or self.timeout_seconds <= 0
            or not isinstance(self.safety_identifier, str)
            or not self.safety_identifier
            or len(self.safety_identifier) > OPENAI_GUEST_SAFETY_IDENTIFIER_LENGTH
            or not self.safety_identifier.isascii()
            or any(character.isspace() for character in self.safety_identifier)
        ):
            raise ValueError("OpenAI Responses input-token contract is malformed")


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


def require_official_openai_routing() -> None:
    """Fail before credential access when ambient state could change provider identity."""
    configured = sorted(
        variable
        for variable in OPENAI_ROUTING_ENVIRONMENT_VARIABLES
        if variable in os.environ
    )
    if configured:
        raise InputTokenCountError(
            "ambient OpenAI routing configuration is forbidden: "
            + ", ".join(configured)
        )


def _require_exact_openai_root_client(
    client: object,
    *,
    api_key: str,
    expected_type: type[OpenAI] | type[AsyncOpenAI],
) -> None:
    """Require the SDK client that can transmit credentials to match one route."""
    if (
        type(client) is not expected_type
        or str(client.base_url) != _OPENAI_ROOT_CLIENT_BASE_URL
        or client.organization is not None
        or client.project is not None
        or client.admin_api_key is not None
        or client.api_key != api_key
        or client.auth_headers != {"Authorization": f"Bearer {api_key}"}
        or client._custom_headers != {}
        or client._custom_query != {}
        or client._provider is not None
        or client.workload_identity is not None
    ):
        raise InputTokenCountError(
            "the OpenAI SDK client left the official host and credential contract"
        )


@dataclass(slots=True)
class _OpenAIRequestCapture:
    """Capture one local SDK request without permitting provider I/O."""

    contract: OpenAIResponsesInputTokenContract
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
                "max_output_tokens": self.contract.max_output_tokens,
                "model": self.contract.model_name,
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


def _require_exact_openai_model(
    model: object,
    *,
    contract: OpenAIResponsesInputTokenContract,
) -> ChatOpenAI:
    """Reject any model whose generated payload could diverge from the contract."""
    if not isinstance(contract, OpenAIResponsesInputTokenContract):
        raise TypeError("contract must be an OpenAIResponsesInputTokenContract")
    if not isinstance(model, ChatOpenAI):
        raise InputTokenCountError(
            "exact OpenAI input counting requires the server-owned ChatOpenAI model"
        )
    if (
        model.model_name != contract.model_name
        or model.max_tokens != contract.max_output_tokens
        or model.max_retries != 0
        or model.request_timeout != contract.timeout_seconds
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
        or model.extra_body.get("safety_identifier") != contract.safety_identifier
        or model.model_kwargs != {}
        or model.openai_api_base != OPENAI_API_BASE_URL
        or model.openai_organization is not None
        or model.openai_proxy
        or model.default_headers is not None
        or model.default_query is not None
    ):
        raise InputTokenCountError(
            "the server-owned OpenAI Responses model left its exact request contract"
        )
    api_key = model.openai_api_key.get_secret_value()
    _require_exact_openai_root_client(
        model.root_client,
        api_key=api_key,
        expected_type=OpenAI,
    )
    _require_exact_openai_root_client(
        model.root_async_client,
        api_key=api_key,
        expected_type=AsyncOpenAI,
    )
    return model


def _require_exact_openai_guest_model(model: object) -> ChatOpenAI:
    """Reject any public guest model outside its single reviewed contract."""
    if not isinstance(model, ChatOpenAI):
        raise InputTokenCountError(
            "exact OpenAI input counting requires the server-owned ChatOpenAI model"
        )
    safety_identifier = (
        model.extra_body.get("safety_identifier")
        if isinstance(model.extra_body, dict)
        else None
    )
    if not _is_openai_guest_safety_identifier(safety_identifier):
        raise InputTokenCountError(
            "the server-owned OpenAI guest model left its exact request contract"
        )
    contract = OpenAIResponsesInputTokenContract(
        model_name=OPENAI_GUEST_MODEL_NAME,
        max_output_tokens=OPENAI_GUEST_MAX_OUTPUT_TOKENS,
        timeout_seconds=OPENAI_GUEST_TIMEOUT_SECONDS,
        safety_identifier=safety_identifier,
    )
    return _require_exact_openai_model(model, contract=contract)


def require_exact_openai_responses_model(
    model: object,
    *,
    contract: OpenAIResponsesInputTokenContract,
) -> ChatOpenAI:
    """Expose the reviewed generation-client contract to server constructors."""
    return _require_exact_openai_model(model, contract=contract)


def require_exact_openai_guest_model(model: object) -> ChatOpenAI:
    """Expose the single reviewed anonymous generation-client contract."""
    return _require_exact_openai_guest_model(model)


def _openai_capture_model(
    model: ChatOpenAI,
    *,
    contract: OpenAIResponsesInputTokenContract,
    sync_client: httpx.Client,
    async_client: httpx.AsyncClient,
) -> ChatOpenAI:
    """Recreate the reviewed model with documented no-network HTTP clients."""
    return ChatOpenAI(
        model=contract.model_name,
        api_key=_OPENAI_CAPTURE_API_KEY,
        base_url=OPENAI_API_BASE_URL,
        stream_usage=True,
        max_tokens=contract.max_output_tokens,
        max_retries=model.max_retries,
        timeout=contract.timeout_seconds,
        use_responses_api=model.use_responses_api,
        output_version=model.output_version,
        reasoning=model.reasoning,
        store=model.store,
        truncation=model.truncation,
        cache=model.cache,
        extra_body={"safety_identifier": contract.safety_identifier},
        http_client=sync_client,
        http_async_client=async_client,
    )


async def _capture_openai_generation_payload(
    request: ModelRequest[Any],
    *,
    contract: OpenAIResponsesInputTokenContract | None = None,
) -> dict[str, Any]:
    """Use ChatOpenAI's public invocation path against an in-memory transport."""
    if contract is None:
        model = _require_exact_openai_guest_model(request.model)
        safety_identifier = model.extra_body["safety_identifier"]
        contract = OpenAIResponsesInputTokenContract(
            model_name=OPENAI_GUEST_MODEL_NAME,
            max_output_tokens=OPENAI_GUEST_MAX_OUTPUT_TOKENS,
            timeout_seconds=OPENAI_GUEST_TIMEOUT_SECONDS,
            safety_identifier=safety_identifier,
        )
    else:
        model = _require_exact_openai_model(request.model, contract=contract)
    if request.response_format is not None or request.model_settings:
        raise InputTokenCountError(
            "exact OpenAI Responses requests cannot add runtime settings or formats"
        )

    capture = _OpenAIRequestCapture(contract=contract)
    transport = httpx.MockTransport(capture)
    sync_client = httpx.Client(transport=transport)
    try:
        async with httpx.AsyncClient(transport=transport) as async_client:
            capture_model = _openai_capture_model(
                model,
                contract=contract,
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
    *,
    contract: OpenAIResponsesInputTokenContract | None = None,
) -> dict[str, Any]:
    """Project only token-bearing fields accepted by `/responses/input_tokens`."""
    expected_model_name = (
        OPENAI_GUEST_MODEL_NAME if contract is None else contract.model_name
    )
    expected_max_output_tokens = (
        OPENAI_GUEST_MAX_OUTPUT_TOKENS
        if contract is None
        else contract.max_output_tokens
    )
    safety_identifier = generation_payload.get("safety_identifier")
    safety_identifier_valid = (
        _is_openai_guest_safety_identifier(safety_identifier)
        if contract is None
        else safety_identifier == contract.safety_identifier
    )
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
        generation_payload.get("model") != expected_model_name
        or generation_payload.get("max_output_tokens") != expected_max_output_tokens
        or generation_payload.get("reasoning")
        != {"context": "current_turn", "effort": "none"}
        or generation_payload.get("store") is not False
        or generation_payload.get("stream") is not False
        or generation_payload.get("truncation") != "disabled"
        or not safety_identifier_valid
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
    require_official_openai_routing()
    api_key = require_openai_api_key()
    if http_client is not None and not isinstance(http_client, httpx.AsyncClient):
        raise TypeError("http_client must be an httpx.AsyncClient")
    try:
        async with AsyncOpenAI(
            api_key=api_key,
            base_url=OPENAI_API_BASE_URL,
            max_retries=0,
            timeout=OPENAI_GUEST_TIMEOUT_SECONDS,
            http_client=http_client,
        ) as client:
            _require_exact_openai_root_client(
                client,
                api_key=api_key,
                expected_type=AsyncOpenAI,
            )
            response = await client.responses.input_tokens.count(**payload)
    except Exception as exc:
        raise InputTokenCountError(
            "OpenAI input token counting failed before generation"
        ) from exc
    return response.input_tokens


async def _prepare_openai_input_token_count(
    request: ModelRequest[Any],
    *,
    contract: OpenAIResponsesInputTokenContract | None = None,
) -> PreparedInputTokenCount:
    """Capture one immutable count payload without provider I/O."""
    generation_payload = await _capture_openai_generation_payload(
        request,
        contract=contract,
    )
    count_payload = _openai_input_count_payload(
        generation_payload,
        contract=contract,
    )
    canonical_count_payload = _canonical_openai_input_payload(count_payload)
    reserved_input_tokens = _openai_input_token_reservation(count_payload)
    prepared_request = request
    count_started = False

    async def count() -> int:
        nonlocal count_started
        if count_started:
            raise InputTokenCountError(
                "prepared OpenAI input-count request was already attempted"
            )
        count_started = True
        replayed_payload = json.loads(canonical_count_payload)
        if not isinstance(replayed_payload, dict):
            raise InputTokenCountError(
                "prepared OpenAI input-count payload is not an object"
            )
        token_count = await _count_openai_responses_input_tokens(replayed_payload)
        return _validated_openai_input_token_count(
            token_count,
            reserved_input_tokens=reserved_input_tokens,
        )

    async def verify_generation_request(candidate: ModelRequest[Any]) -> None:
        if candidate is not prepared_request:
            raise InputTokenCountError(
                "OpenAI generation request object changed after input counting"
            )
        replayed_generation_payload = await _capture_openai_generation_payload(
            candidate,
            contract=contract,
        )
        replayed_count_payload = _openai_input_count_payload(
            replayed_generation_payload,
            contract=contract,
        )
        if (
            _canonical_openai_input_payload(replayed_count_payload)
            != canonical_count_payload
        ):
            raise InputTokenCountError(
                "OpenAI token-bearing generation payload changed after input counting"
            )

    return PreparedInputTokenCount(
        reserved_input_tokens=reserved_input_tokens,
        _count=count,
        _verify_generation_request=verify_generation_request,
    )


async def prepare_openai_input_token_count(
    request: ModelRequest[Any],
) -> PreparedInputTokenCount:
    """Prepare the exact guest Responses count before any provider request."""
    return await _prepare_openai_input_token_count(request)


async def count_openai_input_tokens(request: ModelRequest[Any]) -> int:
    """Count the exact Responses payload, including final function schemas.

    `ChatOpenAI.get_num_tokens_from_messages` is intentionally not used: its
    local tokenizer does not count the final tool schemas. The same public
    ChatOpenAI bind/invoke path is replayed through a no-network transport,
    then only the official input-count endpoint receives the captured
    token-bearing fields. Any new wire field fails closed until reviewed.

    The run-budget middleware uses :func:`prepare_openai_input_token_count` so
    its local reservation is atomic before this provider call. This direct
    helper remains available for exact-count tests and non-budgeted callers.
    """
    prepared = await prepare_openai_input_token_count(request)
    return await prepared.count()


def openai_responses_input_token_counter(
    contract: OpenAIResponsesInputTokenContract,
) -> InputTokenCounter:
    """Bind exact provider counting to one code-owned Responses contract."""
    if not isinstance(contract, OpenAIResponsesInputTokenContract):
        raise TypeError("contract must be an OpenAIResponsesInputTokenContract")

    async def count(request: ModelRequest[Any]) -> int:
        prepared = await _prepare_openai_input_token_count(
            request,
            contract=contract,
        )
        return await prepared.count()

    return count


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
    "InputTokenCountPreparer",
    "OpenAIResponsesInputTokenContract",
    "OPENAI_API_BASE_URL",
    "OPENAI_GUEST_MAX_OUTPUT_TOKENS",
    "OPENAI_GUEST_MODEL_NAME",
    "OPENAI_GUEST_RESPONSE_MODEL_NAMES",
    "OPENAI_GUEST_MODEL_SPEC",
    "OPENAI_GUEST_SAFETY_IDENTIFIER_LENGTH",
    "OPENAI_GUEST_SAFETY_IDENTIFIER_PREFIX",
    "OPENAI_GUEST_TIMEOUT_SECONDS",
    "OPENAI_ROUTING_ENVIRONMENT_VARIABLES",
    "PreparedInputTokenCount",
    "count_anthropic_input_tokens",
    "count_openai_input_tokens",
    "openai_guest_safety_identifier",
    "openai_responses_input_token_counter",
    "prepare_openai_input_token_count",
    "require_exact_openai_guest_model",
    "require_exact_openai_responses_model",
    "require_official_openai_routing",
    "require_openai_api_key",
]
