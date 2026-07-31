#!/usr/bin/env python3
"""Verify that the canonical Vercel domain serves one exact main deployment."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

CANONICAL_ENDPOINT = "https://syshin0116.vercel.app/api/deployment-revision"
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
DEPLOYMENT_ID = re.compile(r"^dpl_[A-Za-z0-9]+$")
VERCEL_HOST = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.vercel\.app$")
EXPECTED_KEYS = {
    "schemaVersion",
    "deploymentId",
    "deploymentUrl",
    "gitSha",
}
MAX_RESPONSE_BYTES = 4_096


class VerificationError(RuntimeError):
    """The public deployment does not satisfy the exact contract."""


@dataclass(frozen=True)
class ProductionRevision:
    deployment_id: str
    deployment_url: str
    git_sha: str


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise VerificationError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def parse_revision_payload(payload: bytes) -> ProductionRevision:
    """Parse one bounded, exact public revision document."""
    if len(payload) > MAX_RESPONSE_BYTES:
        raise VerificationError("revision response exceeds the byte limit")
    try:
        document = json.loads(
            payload,
            object_pairs_hook=_unique_object,
            parse_constant=lambda value: (_ for _ in ()).throw(
                VerificationError(f"invalid JSON constant: {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerificationError(f"revision response is not strict JSON: {exc}") from exc

    if not isinstance(document, dict) or set(document) != EXPECTED_KEYS:
        raise VerificationError("revision response keys differ from the exact contract")
    if type(document["schemaVersion"]) is not int or document["schemaVersion"] != 1:
        raise VerificationError("revision schemaVersion must equal integer 1")

    deployment_id = document["deploymentId"]
    deployment_url = document["deploymentUrl"]
    git_sha = document["gitSha"]
    if not isinstance(deployment_id, str) or not DEPLOYMENT_ID.fullmatch(deployment_id):
        raise VerificationError("revision deploymentId is invalid")
    if not isinstance(deployment_url, str) or not VERCEL_HOST.fullmatch(deployment_url):
        raise VerificationError("revision deploymentUrl is invalid")
    if not isinstance(git_sha, str) or not FULL_SHA.fullmatch(git_sha):
        raise VerificationError("revision gitSha is invalid")

    return ProductionRevision(
        deployment_id=deployment_id,
        deployment_url=deployment_url,
        git_sha=git_sha,
    )


def normalize_expected_deployment_url(value: str) -> str | None:
    """Return the expected Vercel hostname, or None when no URL was supplied."""
    if not value:
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise VerificationError("expected deployment URL is invalid") from exc
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or parsed.hostname is None
        or not VERCEL_HOST.fullmatch(parsed.hostname)
    ):
        raise VerificationError(
            "expected deployment URL must be one HTTPS vercel.app origin"
        )
    return parsed.hostname


def fetch_production_revision(timeout_seconds: float) -> ProductionRevision:
    """Read the canonical no-store endpoint without following another origin."""
    request = urllib.request.Request(
        CANONICAL_ENDPOINT,
        headers={
            "Accept": "application/json",
            "Cache-Control": "no-cache",
            "User-Agent": "syshin0116-vercel-production-verifier/1",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        if response.geturl() != CANONICAL_ENDPOINT:
            raise VerificationError("canonical revision endpoint redirected")
        if response.status != 200:
            raise VerificationError(
                f"canonical revision endpoint returned HTTP {response.status}"
            )
        if response.headers.get_content_type() != "application/json":
            raise VerificationError(
                "canonical revision endpoint did not return application/json"
            )
        payload = response.read(MAX_RESPONSE_BYTES + 1)
    return parse_revision_payload(payload)


def wait_for_production_revision(
    *,
    expected_sha: str,
    expected_deployment_url: str = "",
    attempts: int = 60,
    interval_seconds: float = 10,
    timeout_seconds: float = 10,
    fetcher: Callable[[float], ProductionRevision] = fetch_production_revision,
    sleeper: Callable[[float], None] = time.sleep,
) -> ProductionRevision:
    """Poll until the public domain serves the exact expected revision."""
    if not FULL_SHA.fullmatch(expected_sha):
        raise VerificationError("expected SHA must be 40 lowercase hex characters")
    expected_url = normalize_expected_deployment_url(expected_deployment_url)
    if not 1 <= attempts <= 120:
        raise VerificationError("attempts must be between 1 and 120")
    if not 0 <= interval_seconds <= 60:
        raise VerificationError("interval must be between 0 and 60 seconds")
    if not 0 < timeout_seconds <= 60:
        raise VerificationError("timeout must be above 0 and at most 60 seconds")

    last_detail = "no request attempted"
    for attempt in range(1, attempts + 1):
        try:
            revision = fetcher(timeout_seconds)
            mismatches: list[str] = []
            if revision.git_sha != expected_sha:
                mismatches.append(f"gitSha={revision.git_sha}, expected={expected_sha}")
            if expected_url is not None and revision.deployment_url != expected_url:
                mismatches.append(
                    f"deploymentUrl={revision.deployment_url}, expected={expected_url}"
                )
            if not mismatches:
                return revision
            last_detail = "; ".join(mismatches)
        except (
            OSError,
            TimeoutError,
            VerificationError,
            urllib.error.URLError,
        ) as exc:
            last_detail = str(exc)

        if attempt < attempts:
            print(
                f"Vercel production contract pending "
                f"({attempt}/{attempts}): {last_detail}",
                file=sys.stderr,
            )
            sleeper(interval_seconds)

    raise VerificationError(
        "canonical Vercel production did not converge: " + last_detail
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--expected-deployment-url", default="")
    parser.add_argument("--attempts", type=int, default=60)
    parser.add_argument("--interval-seconds", type=float, default=10)
    parser.add_argument("--timeout-seconds", type=float, default=10)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        revision = wait_for_production_revision(
            expected_sha=args.expected_sha,
            expected_deployment_url=args.expected_deployment_url,
            attempts=args.attempts,
            interval_seconds=args.interval_seconds,
            timeout_seconds=args.timeout_seconds,
        )
    except VerificationError as exc:
        print(f"Vercel production verification failed: {exc}", file=sys.stderr)
        return 1

    print(
        "Vercel production contract passed: "
        f"deployment={revision.deployment_id} "
        f"url={revision.deployment_url} sha={revision.git_sha}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
