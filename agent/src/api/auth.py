"""Authentication helpers for the public Agent API."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import time
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

TOKEN_ISSUER = "syshin0116.dev"
TOKEN_AUDIENCE = "agent-api"
PUBLIC_PATHS = frozenset({"/ok", "/info"})
MIN_SECRET_LENGTH = 32
MAX_SCOPE_LENGTH = 512
_SCOPE_PATTERN = re.compile(r"^[A-Za-z0-9:_-]+$")


class TokenError(ValueError):
    """Raised when an Agent API token is missing or invalid."""


def _decode_segment(segment: str) -> dict[str, Any]:
    try:
        padding = "=" * (-len(segment) % 4)
        raw = base64.urlsafe_b64decode(segment + padding)
        value = json.loads(raw)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TokenError("malformed token") from exc
    if not isinstance(value, dict):
        raise TokenError("malformed token")
    return value


def _encode_segment(value: dict[str, Any]) -> str:
    raw = json.dumps(value, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def create_agent_token(
    subject: str,
    secret: str,
    *,
    now: int | None = None,
    ttl_seconds: int = 900,
    scopes: tuple[str, ...] | list[str] = (),
) -> str:
    """Create a short-lived token for tests and trusted server clients."""
    if not subject:
        raise TokenError("token subject is missing")
    if len(secret) < MIN_SECRET_LENGTH:
        raise TokenError("authentication secret is too short")
    issued_at = int(time.time()) if now is None else now
    header = _encode_segment({"alg": "HS256", "typ": "JWT"})
    payload_data: dict[str, Any] = {
        "sub": subject,
        "iss": TOKEN_ISSUER,
        "aud": TOKEN_AUDIENCE,
        "iat": issued_at,
        "exp": issued_at + ttl_seconds,
    }
    normalized_scopes = sorted(set(scopes))
    if any(not _SCOPE_PATTERN.fullmatch(scope) for scope in normalized_scopes):
        raise TokenError("invalid token scope")
    if normalized_scopes:
        scope_value = " ".join(normalized_scopes)
        if len(scope_value) > MAX_SCOPE_LENGTH:
            raise TokenError("invalid token scope")
        payload_data["scope"] = scope_value
    payload = _encode_segment(payload_data)
    signing_input = f"{header}.{payload}"
    signature = (
        base64.urlsafe_b64encode(
            hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
        )
        .decode()
        .rstrip("=")
    )
    return f"{signing_input}.{signature}"


def verify_agent_token(
    token: str,
    secret: str,
    *,
    now: int | None = None,
    leeway_seconds: int = 30,
) -> dict[str, Any]:
    """Verify the short-lived HS256 token issued by the Next.js frontend."""
    if len(secret) < MIN_SECRET_LENGTH:
        raise TokenError("authentication secret is too short")
    if len(token) > 8192:
        raise TokenError("token is too large")

    parts = token.split(".")
    if len(parts) != 3:
        raise TokenError("malformed token")
    encoded_header, encoded_payload, encoded_signature = parts

    header = _decode_segment(encoded_header)
    if header.get("alg") != "HS256" or header.get("typ") != "JWT":
        raise TokenError("unsupported token algorithm")

    signing_input = f"{encoded_header}.{encoded_payload}".encode()
    expected = base64.urlsafe_b64encode(
        hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    ).rstrip(b"=")
    if not hmac.compare_digest(expected, encoded_signature.encode()):
        raise TokenError("invalid token signature")

    claims = _decode_segment(encoded_payload)
    current_time = int(time.time()) if now is None else now
    try:
        issued_at = int(claims["iat"])
        expires_at = int(claims["exp"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TokenError("invalid token timestamps") from exc

    if issued_at > current_time + leeway_seconds:
        raise TokenError("token is not active")
    if expires_at <= current_time - leeway_seconds:
        raise TokenError("token has expired")
    if claims.get("iss") != TOKEN_ISSUER or claims.get("aud") != TOKEN_AUDIENCE:
        raise TokenError("invalid token scope")
    if not isinstance(claims.get("sub"), str) or not claims["sub"]:
        raise TokenError("token subject is missing")
    scope = claims.get("scope", "")
    if not isinstance(scope, str) or len(scope) > MAX_SCOPE_LENGTH:
        raise TokenError("invalid token scope")
    if any(not _SCOPE_PATTERN.fullmatch(value) for value in scope.split()):
        raise TokenError("invalid token scope")
    return claims


def allowed_origins() -> list[str]:
    configured = os.environ.get("AGENT_ALLOWED_ORIGINS", "http://localhost:3000")
    return [
        origin.strip().rstrip("/") for origin in configured.split(",") if origin.strip()
    ]


class AgentAuthMiddleware(BaseHTTPMiddleware):
    """Require a signed frontend token for every non-health endpoint."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.method == "OPTIONS" or request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        secret = os.environ.get("AGENT_AUTH_SECRET", "")
        if len(secret) < MIN_SECRET_LENGTH:
            return JSONResponse(
                {"detail": "Agent API authentication is not configured"},
                status_code=503,
            )

        scheme, _, token = request.headers.get("Authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not token:
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)

        try:
            claims = verify_agent_token(token, secret)
        except TokenError:
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)

        request.state.user_id = claims["sub"]
        request.state.scopes = frozenset(claims.get("scope", "").split())
        return await call_next(request)
