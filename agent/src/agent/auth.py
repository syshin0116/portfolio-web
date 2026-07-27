"""Fail-closed Aegra authentication for owner preview traffic."""

from __future__ import annotations

import os
import re
from typing import Any

import jwt
from langgraph_sdk import Auth

TOKEN_ISSUER = "syshin0116.dev"
TOKEN_AUDIENCE = "agent-api"
MIN_SECRET_LENGTH = 32
MAX_SCOPE_LENGTH = 512
_SCOPE_PATTERN = re.compile(r"^[A-Za-z0-9:_-]+$")


def _required_secret() -> str:
    secret = os.environ.get("AGENT_AUTH_SECRET", "")
    if len(secret) < MIN_SECRET_LENGTH:
        raise RuntimeError("AGENT_AUTH_SECRET must be at least 32 characters")
    return secret


AGENT_AUTH_SECRET = _required_secret()
auth = Auth()


def _bearer_token(headers: dict[str, str]) -> str:
    authorization = next(
        (value for key, value in headers.items() if key.lower() == "authorization"),
        "",
    )
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token:
        raise Auth.exceptions.HTTPException(status_code=401, detail="Unauthorized")
    return token


def _permissions(claims: dict[str, Any]) -> list[str]:
    scope = claims.get("scope", "")
    if not isinstance(scope, str) or len(scope) > MAX_SCOPE_LENGTH:
        raise Auth.exceptions.HTTPException(status_code=401, detail="Unauthorized")
    permissions = scope.split()
    if any(_SCOPE_PATTERN.fullmatch(value) is None for value in permissions):
        raise Auth.exceptions.HTTPException(status_code=401, detail="Unauthorized")
    return sorted(set(permissions))


@auth.authenticate
async def authenticate(headers: dict[str, str]) -> Auth.types.MinimalUserDict:
    """Verify the signed frontend JWT using Aegra 0.9.24's headers contract."""
    try:
        claims = jwt.decode(
            _bearer_token(headers),
            AGENT_AUTH_SECRET,
            algorithms=["HS256"],
            audience=TOKEN_AUDIENCE,
            issuer=TOKEN_ISSUER,
            leeway=30,
            options={"require": ["sub", "iss", "aud", "iat", "exp"]},
        )
    except Auth.exceptions.HTTPException:
        raise
    except jwt.PyJWTError as exc:
        raise Auth.exceptions.HTTPException(
            status_code=401,
            detail="Unauthorized",
        ) from exc

    identity = claims.get("sub")
    if not isinstance(identity, str) or not identity or identity.startswith("anon:"):
        raise Auth.exceptions.HTTPException(status_code=401, detail="Unauthorized")

    permissions = _permissions(claims)
    if "anon" in permissions:
        raise Auth.exceptions.HTTPException(status_code=401, detail="Unauthorized")

    return {
        "identity": identity,
        "display_name": identity,
        "is_authenticated": True,
        "permissions": permissions,
    }


@auth.on.threads.delete
async def deny_unsafe_core_thread_delete(
    ctx: Auth.types.AuthContext,
    value: Any,
) -> bool:
    """Disable deletion: Aegra 0.9.24 cannot atomically delete metadata/checkpoints."""
    del ctx, value
    return False


__all__ = [
    "AGENT_AUTH_SECRET",
    "MAX_SCOPE_LENGTH",
    "MIN_SECRET_LENGTH",
    "TOKEN_AUDIENCE",
    "TOKEN_ISSUER",
    "auth",
    "authenticate",
]
