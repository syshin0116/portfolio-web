"""Side-effect-free identity contracts shared by auth and maintenance jobs."""

from __future__ import annotations

import re

ANONYMOUS_PERMISSION = "anon"
ANONYMOUS_SUBJECT_PREFIX = "anon:"
CANONICAL_ANONYMOUS_SUBJECT_PATTERN = (
    r"^anon:[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_CANONICAL_ANONYMOUS_SUBJECT = re.compile(CANONICAL_ANONYMOUS_SUBJECT_PATTERN)


def is_anonymous_identity(identity: object) -> bool:
    """Accept only the canonical lower-case ``anon:<uuid4>`` subject."""
    return bool(
        isinstance(identity, str)
        and _CANONICAL_ANONYMOUS_SUBJECT.fullmatch(identity) is not None
    )


__all__ = [
    "ANONYMOUS_PERMISSION",
    "ANONYMOUS_SUBJECT_PREFIX",
    "CANONICAL_ANONYMOUS_SUBJECT_PATTERN",
    "is_anonymous_identity",
]
