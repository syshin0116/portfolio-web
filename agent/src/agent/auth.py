"""Fail-closed Aegra authentication for owner preview traffic."""

from __future__ import annotations

import os
import re
from typing import Any

import jwt
from langgraph_sdk import Auth

from agent.identity import (
    ANONYMOUS_PERMISSION,
    ANONYMOUS_SUBJECT_PREFIX,
    CANONICAL_ANONYMOUS_SUBJECT_PATTERN,
    is_anonymous_identity,
)

TOKEN_ISSUER = "syshin0116.dev"
TOKEN_AUDIENCE = "agent-api"
MIN_SECRET_LENGTH = 32
MAX_SCOPE_LENGTH = 512
ANONYMOUS_TOKEN_TTL_SECONDS = 300
_SCOPE_PATTERN = re.compile(r"^[A-Za-z0-9:_-]+$")


def _required_secret() -> str:
    secret = os.environ.get("AGENT_AUTH_SECRET", "")
    if len(secret) < MIN_SECRET_LENGTH:
        raise RuntimeError("AGENT_AUTH_SECRET must be at least 32 characters")
    return secret


AGENT_AUTH_SECRET = _required_secret()
auth = Auth()


def server_anonymous_access_enabled() -> bool:
    """Resolve the independent agent-side public-access gate."""
    value = os.environ.get("AGENT_ANONYMOUS_ACCESS_ENABLED", "false")
    if value == "true":
        return True
    if value == "false":
        return False
    raise RuntimeError(
        "AGENT_ANONYMOUS_ACCESS_ENABLED must be exactly 'true' or 'false'"
    )


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
    """Verify the signed frontend JWT using Aegra 0.9.25's headers contract."""
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
    if not isinstance(identity, str) or not identity:
        raise Auth.exceptions.HTTPException(status_code=401, detail="Unauthorized")

    permissions = _permissions(claims)
    if is_anonymous_identity(identity):
        issued_at = claims.get("iat")
        expires_at = claims.get("exp")
        if (
            not server_anonymous_access_enabled()
            or claims.get("scope") != ANONYMOUS_PERMISSION
            or permissions != [ANONYMOUS_PERMISSION]
            or not isinstance(issued_at, int)
            or isinstance(issued_at, bool)
            or not isinstance(expires_at, int)
            or isinstance(expires_at, bool)
            or expires_at - issued_at != ANONYMOUS_TOKEN_TTL_SECONDS
        ):
            raise Auth.exceptions.HTTPException(status_code=401, detail="Unauthorized")
        return {
            "identity": identity,
            "display_name": "anonymous",
            "is_authenticated": True,
            "permissions": [ANONYMOUS_PERMISSION],
        }

    if (
        identity.startswith(ANONYMOUS_SUBJECT_PREFIX)
        or ANONYMOUS_PERMISSION in permissions
    ):
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
    """Disable deletion: Aegra 0.9.25 cannot atomically delete metadata/checkpoints."""
    del ctx, value
    return False


__all__ = [
    "AGENT_AUTH_SECRET",
    "ANONYMOUS_PERMISSION",
    "ANONYMOUS_SUBJECT_PREFIX",
    "ANONYMOUS_TOKEN_TTL_SECONDS",
    "CANONICAL_ANONYMOUS_SUBJECT_PATTERN",
    "MAX_SCOPE_LENGTH",
    "MIN_SECRET_LENGTH",
    "TOKEN_AUDIENCE",
    "TOKEN_ISSUER",
    "auth",
    "authenticate",
    "is_anonymous_identity",
    "server_anonymous_access_enabled",
]
