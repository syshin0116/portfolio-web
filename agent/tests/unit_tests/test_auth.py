"""Native Aegra authentication contract tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from langgraph_sdk import Auth

from agent.auth import (
    AGENT_AUTH_SECRET,
    TOKEN_AUDIENCE,
    TOKEN_ISSUER,
    auth,
    authenticate,
)


def _token(*, remove: tuple[str, ...] = (), **overrides) -> str:
    now = datetime.now(UTC)
    claims = {
        "sub": "owner-123",
        "iss": TOKEN_ISSUER,
        "aud": TOKEN_AUDIENCE,
        "iat": now,
        "exp": now + timedelta(minutes=15),
        **overrides,
    }
    for claim in remove:
        claims.pop(claim)
    return jwt.encode(claims, AGENT_AUTH_SECRET, algorithm="HS256")


async def test_aegra_authenticate_accepts_one_positional_headers_mapping():
    user = await authenticate(
        {"authorization": f"Bearer {_token(scope='admin threads:write')}"}
    )

    assert user == {
        "identity": "owner-123",
        "display_name": "owner-123",
        "is_authenticated": True,
        "permissions": ["admin", "threads:write"],
    }
    assert auth._authenticate_handler is authenticate


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"authorization": "Basic nope"},
        {"authorization": "Bearer forged"},
        {"authorization": f"Bearer {_token(iss='other')}"},
        {"authorization": f"Bearer {_token(aud='other')}"},
        {"authorization": f"Bearer {_token(sub='')}"},
        {
            "authorization": f"Bearer {_token(exp=datetime.now(UTC) - timedelta(minutes=5))}"
        },
    ],
    ids=[
        "missing",
        "wrong-scheme",
        "forged",
        "wrong-issuer",
        "wrong-audience",
        "missing-subject",
        "expired",
    ],
)
async def test_aegra_authenticate_rejects_invalid_tokens(headers):
    with pytest.raises(Auth.exceptions.HTTPException) as exc_info:
        await authenticate(headers)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Unauthorized"


@pytest.mark.parametrize(
    "missing_claim",
    ["sub", "iss", "aud", "iat", "exp"],
)
async def test_aegra_authenticate_rejects_each_missing_required_claim(missing_claim):
    with pytest.raises(Auth.exceptions.HTTPException) as exc_info:
        await authenticate(
            {"authorization": (f"Bearer {_token(remove=(missing_claim,))}")}
        )

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Unauthorized"


async def test_aegra_authenticate_rejects_issued_at_beyond_clock_skew():
    with pytest.raises(Auth.exceptions.HTTPException) as exc_info:
        await authenticate(
            {
                "authorization": f"Bearer {_token(iat=datetime.now(UTC) + timedelta(minutes=2))}"
            }
        )

    assert exc_info.value.status_code == 401


async def test_aegra_authenticate_accepts_case_insensitive_header_and_deduplicates_scopes():
    user = await authenticate(
        {
            "Authorization": (
                f"Bearer {_token(scope='threads:write admin threads:write')}"
            )
        }
    )

    assert user["permissions"] == ["admin", "threads:write"]


@pytest.mark.parametrize(
    "claims",
    [
        {"sub": "anon:visitor"},
        {"scope": "anon"},
        {"scope": "bad.permission"},
        {"scope": ["admin"]},
        {"scope": "a" * 513},
    ],
    ids=[
        "anonymous-subject",
        "anonymous-scope",
        "invalid-scope",
        "non-string-scope",
        "oversized-scope",
    ],
)
async def test_owner_preview_does_not_enable_anonymous_or_malformed_scopes(claims):
    with pytest.raises(Auth.exceptions.HTTPException) as exc_info:
        await authenticate({"authorization": f"Bearer {_token(**claims)}"})

    assert exc_info.value.status_code == 401


async def test_core_thread_delete_handler_always_denies():
    handler = auth._handlers[("threads", "delete")][-1]

    assert await handler(None, {"thread_id": "owned"}) is False
