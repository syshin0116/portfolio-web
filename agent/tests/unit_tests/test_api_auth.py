"""Tests for Agent API bearer-token verification."""

import base64
import hashlib
import hmac
import json

import pytest

from api.auth import (
    TOKEN_AUDIENCE,
    TOKEN_ISSUER,
    TokenError,
    create_agent_token,
    verify_agent_token,
)

SECRET = "test-secret-that-is-at-least-thirty-two-bytes"
CONTRACT_TOKEN = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJzdWIiOiJ1c2VyLTEyMyIsImlzcyI6InN5c2hpbjAxMTYuZGV2IiwiYXVkIjoiYWdlbnQtYXBpIiwiaWF0IjoxMDAwLCJleHAiOjE5MDB9."
    "EUErDCiSa0A4AbbqPOFlkobzB9k4j7Z9uHHZ4lH-KLY"
)


def _encode(value: dict) -> str:
    raw = json.dumps(value, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _token(**overrides) -> str:
    header = _encode({"alg": "HS256", "typ": "JWT"})
    payload = _encode(
        {
            "sub": "user-123",
            "iss": TOKEN_ISSUER,
            "aud": TOKEN_AUDIENCE,
            "iat": 1_000,
            "exp": 2_000,
            **overrides,
        }
    )
    signing_input = f"{header}.{payload}"
    signature = (
        base64.urlsafe_b64encode(
            hmac.new(SECRET.encode(), signing_input.encode(), hashlib.sha256).digest()
        )
        .decode()
        .rstrip("=")
    )
    return f"{signing_input}.{signature}"


def test_verify_agent_token_accepts_valid_token():
    claims = verify_agent_token(_token(), SECRET, now=1_500)
    assert claims["sub"] == "user-123"


def test_create_agent_token_round_trip():
    token = create_agent_token(
        "user-456",
        SECRET,
        now=1_000,
        ttl_seconds=1_000,
        scopes=["admin"],
    )
    claims = verify_agent_token(token, SECRET, now=1_500)
    assert claims["sub"] == "user-456"
    assert claims["scope"] == "admin"


def test_frontend_contract_token_is_accepted():
    claims = verify_agent_token(CONTRACT_TOKEN, SECRET, now=1_500)
    assert claims["sub"] == "user-123"


def test_verify_agent_token_rejects_malformed_scope():
    with pytest.raises(TokenError, match="scope"):
        verify_agent_token(_token(scope=["admin"]), SECRET, now=1_500)


@pytest.mark.parametrize(
    "token",
    [
        _token(exp=1_000),
        _token(iss="other"),
        _token(aud="other"),
        _token(sub=""),
        _token()[:-1] + "x",
    ],
)
def test_verify_agent_token_rejects_invalid_tokens(token: str):
    with pytest.raises(TokenError):
        verify_agent_token(token, SECRET, now=1_500, leeway_seconds=0)
