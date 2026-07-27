"""Database URL safety checks shared by runtime and migration entrypoints."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlsplit


def _host_from_spec(spec: str) -> str:
    """Remove an optional port without mis-parsing bracketed IPv6 literals."""
    candidate = spec.strip()
    if candidate.startswith("["):
        closing_bracket = candidate.find("]")
        if closing_bracket >= 0:
            return candidate[1:closing_bracket]
        return candidate

    host, separator, port = candidate.rpartition(":")
    if separator and host and port.isdigit():
        return host
    return candidate


def _effective_hosts(configured: str) -> set[str]:
    """Extract authority and libpq/SQLAlchemy query hosts, including multi-host URLs."""
    parsed = urlsplit(configured)
    hosts: set[str] = set()

    authority = parsed.netloc.rsplit("@", 1)[-1]
    for spec in authority.split(","):
        host = _host_from_spec(spec)
        if host:
            hosts.add(host)

    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if key != "host":
            continue
        for spec in value.split(","):
            host = _host_from_spec(spec)
            if host:
                hosts.add(host)

    return hosts


def _is_neon_pooler(host: str) -> bool:
    normalized = host.lower().rstrip(".")
    return normalized.endswith(".neon.tech") and "-pooler." in normalized


def require_direct_neon_database_url(
    configured: str | None,
    *,
    purpose: str,
) -> None:
    """Reject Neon pooler hosts where session-level database semantics are required."""
    if not configured:
        return

    if any(_is_neon_pooler(host) for host in _effective_hosts(configured)):
        raise RuntimeError(
            f"{purpose} requires the direct Neon DATABASE_URL, not -pooler"
        )


__all__ = ["require_direct_neon_database_url"]
