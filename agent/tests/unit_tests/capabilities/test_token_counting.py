"""Provider-native input token counting contracts."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from langchain.agents.middleware import ModelRequest, ModelResponse
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    message_chunk_to_message,
)
from langchain_core.runnables.config import var_child_runnable_config
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.pregel._messages import StreamMessagesHandlerV2
from openai.resources.responses.input_tokens import AsyncInputTokens

import agent.capabilities.token_counting as token_counting
from agent import tools as blog_tools
from agent.capabilities.budget import (
    DEFAULT_RUN_BUDGET_POLICY,
    RunBudget,
    RunBudgetMiddleware,
)
from agent.capabilities.token_counting import (
    _OPENAI_INPUT_TOKEN_FIELDS,
    OPENAI_API_BASE_URL,
    OPENAI_GUEST_MAX_OUTPUT_TOKENS,
    OPENAI_GUEST_MODEL_NAME,
    OPENAI_GUEST_RESPONSE_MODEL_NAMES,
    OPENAI_GUEST_SAFETY_IDENTIFIER_LENGTH,
    OPENAI_GUEST_TIMEOUT_SECONDS,
    OPENAI_ROUTING_ENVIRONMENT_VARIABLES,
    InputTokenCountError,
    OpenAIResponsesInputTokenContract,
    _capture_openai_generation_payload,
    _count_openai_responses_input_tokens,
    _openai_input_count_payload,
    _openai_input_token_reservation,
    count_anthropic_input_tokens,
    count_openai_input_tokens,
    openai_guest_safety_identifier,
    openai_responses_input_token_counter,
    openai_responses_input_token_preparer,
    prepare_openai_input_token_count,
    require_exact_openai_guest_model,
)
from agent.prompts import GUEST_SYSTEM_PROMPT
from agent.retrieval.corpus_build import build_index
from agent.retrieval.serving import ServingRuntime
from agent.tools import TOOLS

_GUEST_IDENTITY = "anon:00000000-0000-4000-8000-000000000001"
_GUEST_SAFETY_IDENTIFIER = openai_guest_safety_identifier(_GUEST_IDENTITY)
_PUBLISHED_CORPUS_QUERY = "LangGraph 에이전트 RAG 검색 방법 비교"


@pytest.fixture(scope="module")
def published_guest_transcripts(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, object]:
    """Build the immutable published corpus and capture two real top-10 paths."""
    agent_root = Path(__file__).resolve().parents[3]
    index = tmp_path_factory.mktemp("guest-count-risk-corpus") / "index"
    report = build_index(
        content_root=agent_root.parent / "content",
        policy_path=agent_root / "corpus-policy.toml",
        output_root=index,
    )
    assert report.document_count == 335
    runtime = ServingRuntime(index)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(blog_tools, "get_serving_runtime", lambda: runtime)
        semantic_output = blog_tools.semantic_search.invoke(
            {"query": _PUBLISHED_CORPUS_QUERY, "top_k": 10}
        )
        first_result = re.search(r"\[([^\]]+\.md)\]", semantic_output)
        assert first_result is not None
        post_path = first_result.group(1)
        post_output = blog_tools.read_post.invoke({"path": post_path})

    semantic_messages = [
        HumanMessage(content=_PUBLISHED_CORPUS_QUERY),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "semantic_search",
                    "args": {"query": _PUBLISHED_CORPUS_QUERY, "top_k": 10},
                    "id": "call_semantic_1",
                    "type": "tool_call",
                }
            ],
        ),
        ToolMessage(content=semantic_output, tool_call_id="call_semantic_1"),
    ]
    read_messages = [
        *semantic_messages,
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "read_post",
                    "args": {"path": post_path},
                    "id": "call_read_1",
                    "type": "tool_call",
                }
            ],
        ),
        ToolMessage(content=post_output, tool_call_id="call_read_1"),
    ]
    return {
        "post_path": post_path,
        "initial_messages": [HumanMessage(content=_PUBLISHED_CORPUS_QUERY)],
        "semantic_messages": semantic_messages,
        "read_messages": read_messages,
    }


@pytest.fixture(autouse=True)
def _clear_openai_routing_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in OPENAI_ROUTING_ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(variable, raising=False)


@tool
def exact_count_tool(query: str) -> str:
    """Tool whose complete schema must reach the provider's official counter."""
    return query


def _openai_guest_model(**overrides) -> ChatOpenAI:
    settings = {
        "model": OPENAI_GUEST_MODEL_NAME,
        "api_key": "test-provider-token-count-key",
        "base_url": OPENAI_API_BASE_URL,
        "stream_usage": True,
        "max_tokens": OPENAI_GUEST_MAX_OUTPUT_TOKENS,
        "max_retries": 0,
        "timeout": OPENAI_GUEST_TIMEOUT_SECONDS,
        "use_responses_api": True,
        "output_version": "responses/v1",
        "reasoning": {"context": "current_turn", "effort": "none"},
        "store": False,
        "truncation": "disabled",
        "cache": False,
        "extra_body": {"safety_identifier": _GUEST_SAFETY_IDENTIFIER},
    }
    settings.update(overrides)
    return ChatOpenAI(**settings)


def _guest_count_risk_budget() -> RunBudget:
    return RunBudget(
        replace(
            DEFAULT_RUN_BUDGET_POLICY,
            policy_id="anonymous-public-v6",
            max_model_calls=8,
            max_output_tokens=OPENAI_GUEST_MAX_OUTPUT_TOKENS,
            max_total_tokens=64_000,
            max_count_risk_tokens_per_attempt=128_000,
            max_count_risk_tokens_per_run=128_000,
        )
    )


def _guest_count_risk_middleware(budget: RunBudget) -> RunBudgetMiddleware:
    async def legacy_count_must_not_run(_request: ModelRequest) -> int:
        pytest.fail("the prepared OpenAI counter must own guest admission")

    return RunBudgetMiddleware(
        budget,
        depth=0,
        allow_subagents=False,
        allowed_subagents=frozenset(),
        input_token_counter=legacy_count_must_not_run,
        input_token_count_preparer=prepare_openai_input_token_count,
        model_provider="openai",
        expected_response_models=OPENAI_GUEST_RESPONSE_MODEL_NAMES,
    )


def _guest_request(messages: list) -> ModelRequest:
    return ModelRequest(
        model=_openai_guest_model(),
        system_message=SystemMessage(content=GUEST_SYSTEM_PROMPT),
        messages=messages,
        tools=TOOLS,
    )


def _openai_fixture_response(
    *,
    input_tokens: int,
    output_tokens: int = 64,
    content: str = "bounded fixture response",
) -> ModelResponse:
    # These counts are deliberately local, non-network fixtures. They prove
    # admission/settlement plumbing, not Luna tokenizer parity or pricing.
    return ModelResponse(
        result=[
            AIMessage(
                content=content,
                response_metadata={
                    "model_provider": "openai",
                    "model_name": OPENAI_GUEST_MODEL_NAME,
                },
                usage_metadata={
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": input_tokens + output_tokens,
                    "input_token_details": {
                        "cache_read": 0,
                        "cache_creation": 0,
                    },
                    "output_token_details": {"reasoning": 0},
                },
            )
        ]
    )


async def _async_response(*, input_tokens: int) -> ModelResponse:
    return _openai_fixture_response(input_tokens=input_tokens)


def test_openai_guest_model_pins_exact_sync_and_async_sdk_routing() -> None:
    model = _openai_guest_model()

    assert require_exact_openai_guest_model(model) is model
    assert model.openai_api_base == OPENAI_API_BASE_URL
    assert "openai_api_base" in model.model_fields_set
    assert "stream_usage" in model.model_fields_set
    for client in (model.root_client, model.root_async_client):
        assert str(client.base_url) == f"{OPENAI_API_BASE_URL}/"
        assert client.organization is None
        assert client.project is None
        assert client._custom_headers == {}
        assert client.auth_headers == {
            "Authorization": "Bearer test-provider-token-count-key"
        }


@pytest.mark.parametrize(
    ("client_name", "attribute", "value"),
    [
        ("root_client", "base_url", httpx.URL("https://attacker.invalid/v1/")),
        ("root_async_client", "organization", "attacker-organization"),
        ("root_client", "project", "attacker-project"),
        (
            "root_async_client",
            "_custom_headers",
            {
                "Authorization": "Bearer attacker",
                "OpenAI-Project": "attacker-project",
            },
        ),
    ],
)
def test_openai_model_rejects_actual_root_client_routing_drift(
    client_name: str,
    attribute: str,
    value: object,
) -> None:
    model = _openai_guest_model()
    setattr(getattr(model, client_name), attribute, value)

    with pytest.raises(
        InputTokenCountError,
        match="SDK client left the official host and credential contract",
    ):
        require_exact_openai_guest_model(model)


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("OPENAI_ADMIN_KEY", "attacker-admin"),
        ("OPENAI_API_BASE", ""),
        ("OPENAI_BASE_URL", "https://attacker.invalid/v1"),
        (
            "OPENAI_CUSTOM_HEADERS",
            "Authorization: Bearer attacker\nOpenAI-Project: attacker-project",
        ),
        ("OPENAI_ORGANIZATION", "attacker-organization"),
        ("OPENAI_ORG_ID", "attacker-organization"),
        ("OPENAI_PROJECT_ID", "attacker-project"),
        ("OPENAI_PROXY", "http://attacker.invalid:8080"),
    ],
)
async def test_openai_count_rejects_ambient_routing_before_credential_read(
    monkeypatch: pytest.MonkeyPatch,
    variable: str,
    value: str,
) -> None:
    credential_reads = 0

    def unexpected_credential_read() -> str:
        nonlocal credential_reads
        credential_reads += 1
        raise AssertionError("ambient routing reached credential access")

    monkeypatch.setenv(variable, value)
    monkeypatch.setattr(
        token_counting,
        "require_openai_api_key",
        unexpected_credential_read,
    )

    with pytest.raises(
        InputTokenCountError,
        match="ambient OpenAI routing configuration is forbidden",
    ):
        await _count_openai_responses_input_tokens(
            {"input": "never transmit", "model": OPENAI_GUEST_MODEL_NAME}
        )

    assert credential_reads == 0


def test_openai_guest_safety_identifier_is_stable_private_and_scoped():
    other_identity = "anon:00000000-0000-4000-8000-000000000002"

    assert openai_guest_safety_identifier(_GUEST_IDENTITY) == _GUEST_SAFETY_IDENTIFIER
    assert openai_guest_safety_identifier(other_identity) != _GUEST_SAFETY_IDENTIFIER
    assert _GUEST_SAFETY_IDENTIFIER.startswith("guest_")
    assert len(_GUEST_SAFETY_IDENTIFIER) == OPENAI_GUEST_SAFETY_IDENTIFIER_LENGTH
    assert _GUEST_IDENTITY not in _GUEST_SAFETY_IDENTIFIER
    with pytest.raises(ValueError, match="canonical anonymous identity"):
        openai_guest_safety_identifier("owner@example.com")


def test_openai_canonical_payload_reservation_includes_defense_in_depth_margin():
    # Canonical UTF-8 is 14 bytes. The local admission heuristic reserves eight
    # units for each JSON node/key plus 256 fixed units; it is not a provider
    # tokenization guarantee.
    assert _openai_input_token_reservation({"input": "é"}) == 14 + 3 * 8 + 256


async def test_openai_oversized_count_payload_prepares_without_provider_io(
    monkeypatch,
):
    credential_reads = 0
    provider_calls = 0

    def unexpected_credential_read() -> str:
        nonlocal credential_reads
        credential_reads += 1
        raise AssertionError("local preflight reached credential access")

    async def unexpected_provider_call(_self, **_payload):
        nonlocal provider_calls
        provider_calls += 1
        raise AssertionError("local preflight reached provider I/O")

    monkeypatch.setattr(
        token_counting,
        "require_openai_api_key",
        unexpected_credential_read,
    )
    monkeypatch.setattr(AsyncInputTokens, "count", unexpected_provider_call)
    request = ModelRequest(
        model=_openai_guest_model(),
        messages=[HumanMessage(content="x" * 20_000)],
        tools=[exact_count_tool],
    )

    prepared = await prepare_openai_input_token_count(request)

    assert prepared.reserved_input_tokens > 10_976
    assert credential_reads == 0
    assert provider_calls == 0


async def test_openai_prepared_count_reaches_provider_exactly_once(monkeypatch):
    provider_calls = 0

    async def official_count(_self, **_payload):
        nonlocal provider_calls
        provider_calls += 1
        return SimpleNamespace(input_tokens=17)

    monkeypatch.setenv("OPENAI_API_KEY", "test-provider-token-count-key")
    monkeypatch.setattr(AsyncInputTokens, "count", official_count)
    request = ModelRequest(
        model=_openai_guest_model(),
        messages=[HumanMessage(content="bounded request")],
        tools=[],
    )
    prepared = await prepare_openai_input_token_count(request)

    assert await prepared.count() == 17
    assert provider_calls == 1
    with pytest.raises(InputTokenCountError, match="already attempted"):
        await prepared.count()
    assert provider_calls == 1


async def test_published_semantic_top10_answer_fits_both_guest_ledgers(
    monkeypatch: pytest.MonkeyPatch,
    published_guest_transcripts: dict[str, object],
) -> None:
    """Pin one real-corpus capture while keeping the provider count offline."""
    exact_count_fixture = 2_500
    observed_reservations: list[int] = []
    ledger_reservations: list[int] = []

    async def safe_exact_count(_self, **payload):
        observed_reservations.append(_openai_input_token_reservation(payload))
        ledger_reservations.append(budget.snapshot().count_risk_tokens_in_flight)
        return SimpleNamespace(input_tokens=exact_count_fixture)

    monkeypatch.setenv("OPENAI_API_KEY", "test-provider-token-count-key")
    monkeypatch.setattr(AsyncInputTokens, "count", safe_exact_count)
    assert published_guest_transcripts["post_path"] == "AI/LangGraph.md"
    messages = published_guest_transcripts["semantic_messages"]
    assert isinstance(messages, list)
    budget = _guest_count_risk_budget()
    middleware = _guest_count_risk_middleware(budget)

    async def respond(_request: ModelRequest) -> ModelResponse:
        snapshot = budget.snapshot()
        assert (
            snapshot.charged_tokens
            == exact_count_fixture + OPENAI_GUEST_MAX_OUTPUT_TOKENS
        )
        assert snapshot.count_risk_tokens == exact_count_fixture
        assert snapshot.count_risk_tokens_in_flight == 0
        return _openai_fixture_response(input_tokens=exact_count_fixture)

    await middleware.awrap_model_call(_guest_request(messages), respond)
    snapshot = budget.finalize()

    # ChatOpenAI's runtime-generated tool schema contributes 76-77 more
    # canonical bytes on pinned CPython 3.12 than on local CPython 3.13. This
    # independently reviewed literal interval accepts both and rejects material
    # payload/schema drift without becoming a production-derived constant.
    assert len(observed_reservations) == 1
    assert 11_000 <= observed_reservations[0] <= 11_350
    assert observed_reservations == ledger_reservations
    assert sum(observed_reservations) < 64_000
    assert snapshot.charged_tokens == 2_564
    assert snapshot.count_risk_tokens == exact_count_fixture
    assert snapshot.provider_input_tokens == exact_count_fixture
    assert snapshot.provider_output_tokens == 64
    assert snapshot.provider_usage_complete is True


async def test_published_semantic_then_read_post_is_cumulatively_admitted(
    monkeypatch: pytest.MonkeyPatch,
    published_guest_transcripts: dict[str, object],
) -> None:
    """Exercise semantic -> read_post -> answer in one shared guest budget."""
    # 693 was observed in one provider-gated Luna smoke on 2026-08-03. It remains
    # a non-network fixture here, not proof of tokenizer behavior or provider pricing.
    safe_exact_count_fixtures = iter((693, 2_500, 4_100))
    observed_reservations: list[int] = []
    ledger_reservations: list[int] = []

    async def safe_exact_count(_self, **payload):
        observed_reservations.append(_openai_input_token_reservation(payload))
        ledger_reservations.append(budget.snapshot().count_risk_tokens_in_flight)
        return SimpleNamespace(input_tokens=next(safe_exact_count_fixtures))

    monkeypatch.setenv("OPENAI_API_KEY", "test-provider-token-count-key")
    monkeypatch.setattr(AsyncInputTokens, "count", safe_exact_count)
    budget = _guest_count_risk_budget()
    middleware = _guest_count_risk_middleware(budget)
    initial_messages = published_guest_transcripts["initial_messages"]
    semantic_messages = published_guest_transcripts["semantic_messages"]
    read_messages = published_guest_transcripts["read_messages"]
    assert isinstance(initial_messages, list)
    assert isinstance(semantic_messages, list)
    assert isinstance(read_messages, list)

    await middleware.awrap_model_call(
        _guest_request(initial_messages),
        lambda _request: _async_response(input_tokens=693),
    )
    await middleware.awrap_model_call(
        _guest_request(semantic_messages),
        lambda _request: _async_response(input_tokens=2_500),
    )

    async def answer(_request: ModelRequest) -> ModelResponse:
        snapshot = budget.snapshot()
        assert snapshot.charged_tokens == 7_933
        assert snapshot.count_risk_tokens == 7_293
        assert snapshot.count_risk_tokens_in_flight == 0
        return _openai_fixture_response(input_tokens=4_100)

    await middleware.awrap_model_call(_guest_request(read_messages), answer)
    snapshot = budget.finalize()

    assert len(observed_reservations) == 3
    assert all(earlier < later for earlier, later in pairwise(observed_reservations))
    # The first interval also covers the 76-77 canonical-byte tool schema
    # variance between the pinned CPython 3.12 runner and local CPython 3.13.
    for reservation, (minimum, maximum) in zip(
        observed_reservations,
        ((6_100, 6_425), (11_000, 11_350), (16_250, 16_600)),
        strict=True,
    ):
        assert minimum <= reservation <= maximum
    assert observed_reservations == ledger_reservations
    assert sum(observed_reservations) < 64_000
    assert snapshot.charged_tokens == 7_485
    assert snapshot.count_risk_tokens == 7_293
    assert snapshot.provider_input_tokens == 7_293
    assert snapshot.provider_output_tokens == 192
    assert snapshot.model_calls == 3
    assert snapshot.provider_usage_complete is True


@pytest.mark.parametrize(
    ("attack", "minimum_reservation", "maximum_reservation"),
    [("user", 22_400, 22_750), ("read-post", 22_750, 23_100)],
)
async def test_16_kib_guest_input_is_admitted_within_the_actual_token_cap(
    monkeypatch: pytest.MonkeyPatch,
    attack: str,
    minimum_reservation: int,
    maximum_reservation: int,
) -> None:
    """A bounded 16 KiB payload fits the reviewed specialist generation budget."""
    if attack == "user":
        messages = [HumanMessage(content="x" * (16 * 1_024))]
    else:
        read_output = blog_tools._cap_read_post_output("x" * (16 * 1_024 + 1))
        assert len(read_output.encode("utf-8")) == 16 * 1_024
        messages = [
            HumanMessage(content="read the adversarial post"),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "read_post",
                        "args": {"path": "AI/adversarial.md"},
                        "id": "call_read_attack",
                        "type": "tool_call",
                    }
                ],
            ),
            ToolMessage(content=read_output, tool_call_id="call_read_attack"),
        ]
    observed_reservations: list[int] = []
    ledger_reservations: list[int] = []

    async def safe_exact_count(_self, **payload):
        observed_reservations.append(_openai_input_token_reservation(payload))
        ledger_reservations.append(budget.snapshot().count_risk_tokens_in_flight)
        return SimpleNamespace(input_tokens=16_000)

    monkeypatch.setenv("OPENAI_API_KEY", "test-provider-token-count-key")
    monkeypatch.setattr(AsyncInputTokens, "count", safe_exact_count)
    budget = _guest_count_risk_budget()
    middleware = _guest_count_risk_middleware(budget)

    await middleware.awrap_model_call(
        _guest_request(messages),
        lambda _request: _async_response(input_tokens=16_000),
    )

    snapshot = budget.snapshot()
    assert len(observed_reservations) == 1
    reservation = observed_reservations[0]
    assert minimum_reservation <= reservation <= maximum_reservation
    assert observed_reservations == ledger_reservations
    assert reservation < 128_000
    assert snapshot.charged_tokens == 16_064
    assert snapshot.count_risk_tokens == 16_000
    assert snapshot.count_risk_tokens_in_flight == 0
    assert snapshot.model_reservations_in_flight == 0
    assert snapshot.exhausted is False
    assert snapshot.provider_usage_complete is True


async def test_openai_prepared_count_detects_token_bearing_generation_drift():
    request = ModelRequest(
        model=_openai_guest_model(),
        messages=[HumanMessage(content="bounded request")],
        tools=[],
    )
    prepared = await prepare_openai_input_token_count(request)

    await prepared.verify_generation_request(request)
    request.messages.append(HumanMessage(content="late mutation"))
    with pytest.raises(InputTokenCountError, match="payload changed"):
        await prepared.verify_generation_request(request)


async def test_openai_official_counter_receives_final_stateless_payload(
    monkeypatch,
):
    observed = {}

    async def official_count(_self, **payload):
        observed["payload"] = payload
        return SimpleNamespace(input_tokens=321)

    monkeypatch.setenv("OPENAI_API_KEY", "test-provider-token-count-key")
    monkeypatch.setattr(AsyncInputTokens, "count", official_count)
    request = ModelRequest(
        model=_openai_guest_model(),
        system_message=SystemMessage(content="final system prompt"),
        messages=[
            HumanMessage(content="first dense 🧑🏽‍💻 input"),
            AIMessage(content="prior answer", id="resp_must_not_be_reused"),
            HumanMessage(content="final question"),
        ],
        tools=[exact_count_tool],
        tool_choice="required",
    )

    count = await count_openai_input_tokens(request)

    assert count == 321
    assert "safety_identifier" not in observed["payload"]
    assert observed["payload"] == {
        "input": [
            {
                "content": "final system prompt",
                "role": "system",
                "type": "message",
            },
            {
                "content": "first dense 🧑🏽‍💻 input",
                "role": "user",
                "type": "message",
            },
            {
                "type": "message",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": "prior answer",
                        "annotations": [],
                    }
                ],
            },
            {
                "content": "final question",
                "role": "user",
                "type": "message",
            },
        ],
        "model": OPENAI_GUEST_MODEL_NAME,
        "reasoning": {"context": "current_turn", "effort": "none"},
        "tool_choice": "required",
        "tools": [
            {
                "type": "function",
                "name": "exact_count_tool",
                "description": (
                    "Tool whose complete schema must reach the provider's official "
                    "counter."
                ),
                "parameters": {
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                    "type": "object",
                },
            }
        ],
        "truncation": "disabled",
    }


async def test_openai_counter_can_bind_one_exact_local_luna_contract(monkeypatch):
    owner_safety_identifier = "owner_" + "1" * 58
    contract = OpenAIResponsesInputTokenContract(
        model_name=OPENAI_GUEST_MODEL_NAME,
        max_output_tokens=256,
        timeout_seconds=OPENAI_GUEST_TIMEOUT_SECONDS,
        safety_identifier=owner_safety_identifier,
    )
    counter = openai_responses_input_token_counter(contract)
    observed = {}

    async def official_count(_self, **payload):
        observed["payload"] = payload
        return SimpleNamespace(input_tokens=17)

    monkeypatch.setenv("OPENAI_API_KEY", "test-provider-token-count-key")
    monkeypatch.setattr(AsyncInputTokens, "count", official_count)
    request = ModelRequest(
        model=_openai_guest_model(
            max_tokens=256,
            extra_body={"safety_identifier": owner_safety_identifier},
        ),
        messages=[HumanMessage(content="bounded local evaluation")],
        tools=[],
    )

    assert await counter(request) == 17
    assert observed["payload"]["model"] == OPENAI_GUEST_MODEL_NAME
    assert "safety_identifier" not in observed["payload"]

    mismatched_request = request.override(
        model=_openai_guest_model(max_tokens=OPENAI_GUEST_MAX_OUTPUT_TOKENS)
    )
    with pytest.raises(InputTokenCountError, match="exact request contract"):
        await counter(mismatched_request)


async def test_openai_preparer_binds_atomic_count_and_parity_to_local_contract(
    monkeypatch,
):
    owner_safety_identifier = "owner_" + "1" * 58
    contract = OpenAIResponsesInputTokenContract(
        model_name=OPENAI_GUEST_MODEL_NAME,
        max_output_tokens=256,
        timeout_seconds=OPENAI_GUEST_TIMEOUT_SECONDS,
        safety_identifier=owner_safety_identifier,
    )
    preparer = openai_responses_input_token_preparer(contract)
    observed = {}
    provider_calls = 0

    async def official_count(_self, **payload):
        nonlocal provider_calls
        provider_calls += 1
        observed["payload"] = payload
        return SimpleNamespace(input_tokens=17)

    monkeypatch.setenv("OPENAI_API_KEY", "test-provider-token-count-key")
    monkeypatch.setattr(AsyncInputTokens, "count", official_count)
    request = ModelRequest(
        model=_openai_guest_model(
            max_tokens=256,
            extra_body={"safety_identifier": owner_safety_identifier},
        ),
        messages=[HumanMessage(content="bounded local evaluation")],
        tools=[],
    )

    prepared = await preparer(request)

    assert provider_calls == 0
    assert await prepared.count() == 17
    assert provider_calls == 1
    assert prepared.reserved_input_tokens == _openai_input_token_reservation(
        observed["payload"]
    )
    await prepared.verify_generation_request(request)
    request.messages.append(HumanMessage(content="late mutation"))
    with pytest.raises(InputTokenCountError, match="payload changed"):
        await prepared.verify_generation_request(request)

    mismatched_request = request.override(
        model=_openai_guest_model(max_tokens=OPENAI_GUEST_MAX_OUTPUT_TOKENS)
    )
    with pytest.raises(InputTokenCountError, match="exact request contract"):
        await preparer(mismatched_request)


async def test_openai_counter_preserves_the_complete_stateless_tool_transcript(
    monkeypatch,
):
    observed = {}

    async def official_count(_self, **payload):
        observed["payload"] = payload
        return SimpleNamespace(input_tokens=42)

    monkeypatch.setenv("OPENAI_API_KEY", "test-provider-token-count-key")
    monkeypatch.setattr(AsyncInputTokens, "count", official_count)
    request = ModelRequest(
        model=_openai_guest_model(),
        messages=[
            HumanMessage(content="use the exact tool"),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "exact_count_tool",
                        "args": {"query": "needle"},
                        "id": "call_exact_1",
                        "type": "tool_call",
                    }
                ],
            ),
            ToolMessage(content="found", tool_call_id="call_exact_1"),
            HumanMessage(content="finish without provider state"),
        ],
        tools=[exact_count_tool],
    )

    assert await count_openai_input_tokens(request) == 42
    assert observed["payload"]["input"] == [
        {
            "content": "use the exact tool",
            "role": "user",
            "type": "message",
        },
        {
            "type": "function_call",
            "name": "exact_count_tool",
            "arguments": '{"query": "needle"}',
            "call_id": "call_exact_1",
        },
        {
            "type": "function_call_output",
            "output": "found",
            "call_id": "call_exact_1",
        },
        {
            "content": "finish without provider state",
            "role": "user",
            "type": "message",
        },
    ]
    assert "previous_response_id" not in observed["payload"]
    assert "conversation" not in observed["payload"]


async def test_openai_counter_sdk_boundary_is_exact_and_has_no_retry(monkeypatch):
    payload = {
        "input": [{"type": "message", "role": "user", "content": "count me"}],
        "model": OPENAI_GUEST_MODEL_NAME,
        "reasoning": {"context": "current_turn", "effort": "none"},
        "truncation": "disabled",
    }
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "POST"
        assert str(request.url) == "https://api.openai.com/v1/responses/input_tokens"
        assert request.headers.get("authorization") == (
            "Bearer test-provider-token-count-key"
        )
        assert "openai-project" not in request.headers
        assert "openai-organization" not in request.headers
        assert json.loads(request.content) == payload
        assert set(request.extensions["timeout"].values()) == {
            OPENAI_GUEST_TIMEOUT_SECONDS
        }
        return httpx.Response(
            200,
            request=request,
            json={
                "object": "response.input_tokens",
                "input_tokens": 321,
            },
        )

    monkeypatch.setenv("OPENAI_API_KEY", "test-provider-token-count-key")
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    assert (
        await _count_openai_responses_input_tokens(
            payload,
            http_client=client,
        )
        == 321
    )
    assert len(requests) == 1

    failures = 0

    async def fail_once(request: httpx.Request) -> httpx.Response:
        nonlocal failures
        failures += 1
        return httpx.Response(
            500,
            request=request,
            json={"error": {"message": "do not retry"}},
        )

    failing_client = httpx.AsyncClient(transport=httpx.MockTransport(fail_once))
    with pytest.raises(InputTokenCountError, match="failed before generation"):
        await _count_openai_responses_input_tokens(
            payload,
            http_client=failing_client,
        )
    assert failures == 1


def _stream_response_fixture() -> dict:
    return {
        "id": "resp_mock_stream",
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
                "id": "msg_mock_stream",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": "hello",
                        "annotations": [],
                        "logprobs": [],
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
            "input_tokens": 3,
            "input_tokens_details": {
                "cache_write_tokens": 1,
                "cached_tokens": 0,
            },
            "output_tokens": 2,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": 5,
        },
        "metadata": {},
    }


async def test_openai_native_stream_and_capture_have_identical_token_payloads():
    streamed_payload = {}
    response = _stream_response_fixture()
    events = [
        {
            "type": "response.created",
            "sequence_number": 0,
            "response": response,
        },
        {
            "type": "response.output_text.delta",
            "sequence_number": 1,
            "output_index": 0,
            "content_index": 0,
            "item_id": "msg_mock_stream",
            "delta": "hel",
            "logprobs": [],
        },
        {
            "type": "response.output_text.delta",
            "sequence_number": 2,
            "output_index": 0,
            "content_index": 0,
            "item_id": "msg_mock_stream",
            "delta": "lo",
            "logprobs": [],
        },
        {
            "type": "response.output_text.done",
            "sequence_number": 3,
            "output_index": 0,
            "content_index": 0,
            "item_id": "msg_mock_stream",
            "text": "hello",
            "logprobs": [],
        },
        {
            "type": "response.completed",
            "sequence_number": 4,
            "response": response,
        },
    ]

    async def stream_handler(request: httpx.Request) -> httpx.Response:
        streamed_payload.update(json.loads(request.content))
        body = "".join(
            f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events
        )
        return httpx.Response(
            200,
            request=request,
            headers={"content-type": "text/event-stream"},
            content=body,
        )

    request = ModelRequest(
        model=_openai_guest_model(),
        system_message=SystemMessage(content="same stream system"),
        messages=[HumanMessage(content="same stream question")],
        tools=[exact_count_tool],
        tool_choice="required",
    )
    captured_payload = await _capture_openai_generation_payload(request)

    async_transport = httpx.MockTransport(stream_handler)
    sync_transport = httpx.MockTransport(
        lambda _request: pytest.fail("native async streaming used the sync client")
    )
    with httpx.Client(transport=sync_transport) as sync_client:
        async with httpx.AsyncClient(transport=async_transport) as async_client:
            stream_model = _openai_guest_model(
                http_client=sync_client,
                http_async_client=async_client,
            ).bind_tools(request.tools, tool_choice=request.tool_choice)
            chunks = [
                chunk
                async for chunk in stream_model.astream(
                    [request.system_message, *request.messages]
                )
            ]

    assert (
        "".join(
            block["text"]
            for chunk in chunks
            for block in chunk.content
            if isinstance(block, dict)
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        )
        == "hello"
    )
    assert chunks[-1].usage_metadata == {
        "input_tokens": 3,
        "output_tokens": 2,
        "total_tokens": 5,
        "input_token_details": {
            "cache_creation": 1,
            "cache_read": 0,
        },
        "output_token_details": {"reasoning": 0},
    }
    assert chunks[-1].response_metadata["model_provider"] == "openai"
    assert (
        chunks[-1].response_metadata["model_name"] in OPENAI_GUEST_RESPONSE_MODEL_NAMES
    )
    assert captured_payload["stream"] is False
    assert captured_payload["safety_identifier"] == _GUEST_SAFETY_IDENTIFIER
    assert streamed_payload["stream"] is True
    assert set(captured_payload) == set(streamed_payload)
    assert {
        key
        for key in captured_payload
        if captured_payload[key] != streamed_payload[key]
    } == {"stream"}
    assert {
        key: captured_payload[key]
        for key in captured_payload
        if key in _OPENAI_INPUT_TOKEN_FIELDS
    } == {
        key: streamed_payload[key]
        for key in streamed_payload
        if key in _OPENAI_INPUT_TOKEN_FIELDS
    }

    assembled_chunk = chunks[0]
    for chunk in chunks[1:]:
        assembled_chunk += chunk
    assembled = message_chunk_to_message(assembled_chunk)
    budget = RunBudget()
    attempt = budget.reserve_model_attempt()
    reservation = budget.reserve_model_input(attempt, input_tokens=3)
    budget._settle_model_response(
        reservation,
        ModelResponse(result=[assembled]),
        model_provider="openai",
        expected_response_models=OPENAI_GUEST_RESPONSE_MODEL_NAMES,
    )
    snapshot = budget.finalize()
    assert snapshot.charged_tokens == 5
    assert snapshot.provider_usage_complete is True
    assert (
        snapshot.provider_input_tokens,
        snapshot.provider_output_tokens,
        snapshot.provider_cache_read_input_tokens,
        snapshot.provider_cache_write_input_tokens,
    ) == (2, 2, 0, 1)


async def test_openai_capture_ignores_ambient_v2_streaming_callback():
    request = ModelRequest(
        model=_openai_guest_model(),
        system_message=SystemMessage(content="ambient stream system"),
        messages=[HumanMessage(content="ambient stream question")],
        tools=[exact_count_tool],
    )
    emitted = []
    handler = StreamMessagesHandlerV2(emitted.append, False)
    token = var_child_runnable_config.set(
        {
            "callbacks": [handler],
            "metadata": {"langgraph_checkpoint_ns": "model"},
        }
    )
    try:
        captured_payload = await _capture_openai_generation_payload(request)
    finally:
        var_child_runnable_config.reset(token)

    assert captured_payload["stream"] is False
    assert emitted == []


@pytest.mark.parametrize("result", [-1, True, "321"])
async def test_openai_malformed_official_count_fails_closed(
    monkeypatch,
    result,
):
    async def malformed_count(_self, **_payload):
        return SimpleNamespace(input_tokens=result)

    monkeypatch.setenv("OPENAI_API_KEY", "test-provider-token-count-key")
    monkeypatch.setattr(AsyncInputTokens, "count", malformed_count)
    request = ModelRequest(
        model=_openai_guest_model(),
        messages=[HumanMessage(content="never estimate this")],
        tools=[],
    )

    with pytest.raises(InputTokenCountError, match="malformed"):
        await count_openai_input_tokens(request)


async def test_openai_official_counter_error_is_wrapped_without_fallback(
    monkeypatch,
):
    async def unavailable(_self, **_payload):
        raise ConnectionError("count endpoint unavailable")

    monkeypatch.setenv("OPENAI_API_KEY", "test-provider-token-count-key")
    monkeypatch.setattr(AsyncInputTokens, "count", unavailable)
    request = ModelRequest(
        model=_openai_guest_model(),
        messages=[HumanMessage(content="never estimate this")],
        tools=[],
    )

    with pytest.raises(
        InputTokenCountError,
        match="failed before generation",
    ) as exc_info:
        await count_openai_input_tokens(request)

    assert isinstance(exc_info.value.__cause__, ConnectionError)


@pytest.mark.parametrize("invalid_key", ["", " ", "test key", "\ttest-key"])
async def test_openai_invalid_counter_key_fails_before_provider_boundary(
    monkeypatch,
    invalid_key,
):
    async def unexpected_provider_call(_self, **_payload):
        pytest.fail("missing-key requests must not reach the provider boundary")

    monkeypatch.setenv("OPENAI_API_KEY", invalid_key)
    monkeypatch.setattr(AsyncInputTokens, "count", unexpected_provider_call)
    request = ModelRequest(
        model=_openai_guest_model(),
        messages=[HumanMessage(content="never estimate this")],
        tools=[],
    )

    with pytest.raises(InputTokenCountError, match="OPENAI_API_KEY is required"):
        await count_openai_input_tokens(request)


@pytest.mark.parametrize(
    "model_override",
    [
        {"model": "gpt-5.4-mini"},
        {"reasoning": {"effort": "none"}},
        {"reasoning": {"context": "all_turns", "effort": "none"}},
        {"use_previous_response_id": True},
        {"max_tokens": OPENAI_GUEST_MAX_OUTPUT_TOKENS + 1},
        {"streaming": False},
        {"verbosity": "high"},
        {"service_tier": "flex"},
        {"stream_usage": False},
        {"seed": 7},
        {"organization": "unreviewed-organization"},
        {"extra_body": {"safety_identifier": "guest_invalid"}},
    ],
)
async def test_openai_server_model_contract_drift_fails_before_counter(
    monkeypatch,
    model_override,
):
    async def unexpected_provider_call(_self, **_payload):
        pytest.fail("drifted models must not reach the provider boundary")

    monkeypatch.setenv("OPENAI_API_KEY", "test-provider-token-count-key")
    monkeypatch.setattr(AsyncInputTokens, "count", unexpected_provider_call)
    request = ModelRequest(
        model=_openai_guest_model(**model_override),
        messages=[HumanMessage(content="never count a drifted request")],
        tools=[],
    )

    with pytest.raises(InputTokenCountError, match="left its exact request contract"):
        await count_openai_input_tokens(request)


@pytest.mark.parametrize(
    "payload_drift",
    [
        {"previous_response_id": "resp_stateful"},
        {"conversation": "conv_stateful"},
    ],
)
def test_openai_stateful_generation_payload_drift_fails_closed(payload_drift):
    generation_payload = {
        "input": [{"type": "message", "role": "user", "content": "question"}],
        "max_output_tokens": OPENAI_GUEST_MAX_OUTPUT_TOKENS,
        "model": OPENAI_GUEST_MODEL_NAME,
        "reasoning": {"context": "current_turn", "effort": "none"},
        "safety_identifier": _GUEST_SAFETY_IDENTIFIER,
        "store": False,
        "stream": False,
        "truncation": "disabled",
        **payload_drift,
    }

    with pytest.raises(InputTokenCountError, match="stateless guest contract"):
        _openai_input_count_payload(generation_payload)


def test_openai_unreviewed_generation_field_fails_closed():
    generation_payload = {
        "input": [{"type": "message", "role": "user", "content": "question"}],
        "max_output_tokens": OPENAI_GUEST_MAX_OUTPUT_TOKENS,
        "model": OPENAI_GUEST_MODEL_NAME,
        "reasoning": {"context": "current_turn", "effort": "none"},
        "safety_identifier": _GUEST_SAFETY_IDENTIFIER,
        "store": False,
        "stream": False,
        "truncation": "disabled",
        "unreviewed_future_field": "changes tokenization",
    }

    with pytest.raises(InputTokenCountError, match="unreviewed request fields"):
        _openai_input_count_payload(generation_payload)


async def test_anthropic_official_counter_receives_final_messages_and_tools(
    monkeypatch,
):
    observed = {}

    def official_count(self, messages, tools=None, **kwargs):
        observed["self"] = self
        observed["messages"] = messages
        observed["tools"] = tools
        observed["kwargs"] = kwargs
        return 321

    monkeypatch.setattr(
        ChatAnthropic,
        "get_num_tokens_from_messages",
        official_count,
    )
    model = ChatAnthropic(
        model="claude-sonnet-4-6",
        anthropic_api_key="test-provider-token-count-key",
        max_tokens=2_048,
        max_retries=0,
        timeout=60,
    )
    request = ModelRequest(
        model=model,
        system_message=SystemMessage(content="final system prompt"),
        messages=[HumanMessage(content="dense 🧑🏽‍💻 input")],
        tools=[exact_count_tool],
        model_settings={
            "cache_control": {
                "type": "ephemeral",
                "ttl": "5m",
            }
        },
    )

    count = await count_anthropic_input_tokens(request)

    assert count == 321
    assert observed == {
        "self": model,
        "messages": [
            request.system_message,
            *request.messages,
        ],
        "tools": [exact_count_tool],
        "kwargs": {
            "cache_control": {
                "type": "ephemeral",
                "ttl": "5m",
            }
        },
    }


@pytest.mark.parametrize("result", [-1, True, "321"])
async def test_anthropic_malformed_official_count_fails_closed(
    monkeypatch,
    result,
):
    monkeypatch.setattr(
        ChatAnthropic,
        "get_num_tokens_from_messages",
        lambda _self, _messages, **_kwargs: result,
    )
    model = ChatAnthropic(
        model="claude-sonnet-4-6",
        anthropic_api_key="test-provider-token-count-key",
        max_tokens=2_048,
        max_retries=0,
        timeout=60,
    )
    request = ModelRequest(
        model=model,
        messages=[HumanMessage(content="never estimate this")],
        tools=[],
    )

    with pytest.raises(InputTokenCountError, match="malformed"):
        await count_anthropic_input_tokens(request)


async def test_anthropic_counter_error_is_wrapped_without_fallback(monkeypatch):
    def unavailable(_self, _messages, **_kwargs):
        raise ConnectionError("count endpoint unavailable")

    monkeypatch.setattr(
        ChatAnthropic,
        "get_num_tokens_from_messages",
        unavailable,
    )
    model = ChatAnthropic(
        model="claude-sonnet-4-6",
        anthropic_api_key="test-provider-token-count-key",
        max_tokens=2_048,
        max_retries=0,
        timeout=60,
    )
    request = ModelRequest(
        model=model,
        messages=[HumanMessage(content="never estimate this")],
        tools=[],
    )

    with pytest.raises(InputTokenCountError, match="failed before generation"):
        await count_anthropic_input_tokens(request)
