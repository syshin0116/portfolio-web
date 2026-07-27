#!/usr/bin/env python3
"""Fail closed unless an agent release still targets a fully verified source SHA."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from typing import Any

EXPECTED_API_URL = "https://api.github.com"
EXPECTED_REPOSITORY = "syshin0116/syshin0116.dev"
EXPECTED_ENVIRONMENTS = {
    "preview": "Agent Preview",
    "production": "Agent Production",
}
EXPECTED_IMAGE_PREFIXES = {
    "preview": (
        "us-east4-docker.pkg.dev/festive-ally-503605-v7/agent-preview/agent@sha256:"
    ),
    "production": (
        "us-east4-docker.pkg.dev/festive-ally-503605-v7/agent/agent@sha256:"
    ),
}
GITHUB_ACTIONS_APP_ID = 15368
MAX_RESPONSE_BYTES = 1_048_576
MAX_SMOKE_TOKEN_BYTES = 8_192
MAX_SMOKE_TOKEN_LIFETIME_SECONDS = 7_200
MIN_SMOKE_TOKEN_REMAINING_SECONDS = 3_900
REQUIRED_PRODUCTION_CHECKS = frozenset({"ci/check", "protocol/compat", "wiki/verify"})
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
REVISION_PATTERN = re.compile(r"^[a-z][a-z0-9-]*[a-z0-9]$")
JWT_SEGMENT_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


class CandidateError(RuntimeError):
    """The release candidate is unsafe or cannot be verified."""


class CandidatePending(RuntimeError):
    """The release candidate has not finished all required checks."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Mapping[str, str],
        newurl: str,
    ) -> None:
        del req, fp, code, msg, headers, newurl
        return None


class GitHubClient:
    def __init__(self, token: str, api_url: str) -> None:
        if api_url != EXPECTED_API_URL:
            raise CandidateError(
                "GitHub API origin is not the reviewed public endpoint"
            )
        if not 20 <= len(token) <= 4096 or "\n" in token or "\r" in token:
            raise CandidateError("GitHub token has an invalid shape")
        self._token = token
        self._opener = urllib.request.build_opener(
            _NoRedirect(),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        )

    def get(self, path: str, query: Mapping[str, str] | None = None) -> dict[str, Any]:
        if not path.startswith("/") or ".." in path or "\\" in path:
            raise CandidateError("GitHub API path is not canonical")
        url = f"{EXPECTED_API_URL}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "User-Agent": "syshin0116-agent-release-gate",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            method="GET",
        )
        try:
            with self._opener.open(request, timeout=20) as response:
                status = response.status
                content_type = response.headers.get_content_type()
                body = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            raise CandidateError(
                f"GitHub API request failed with HTTP {exc.code}"
            ) from None
        except (TimeoutError, urllib.error.URLError, OSError):
            raise CandidateError("GitHub API request failed") from None

        if status != 200:
            raise CandidateError(f"GitHub API returned HTTP {status}")
        if content_type != "application/json":
            raise CandidateError("GitHub API returned a non-JSON response")
        if not body or len(body) > MAX_RESPONSE_BYTES:
            raise CandidateError("GitHub API returned an invalid response size")
        try:
            document = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise CandidateError("GitHub API returned invalid JSON") from None
        if not isinstance(document, dict):
            raise CandidateError("GitHub API returned a non-object document")
        return document


def _validate_source_sha(source_sha: str) -> None:
    if not SHA_PATTERN.fullmatch(source_sha):
        raise CandidateError("source SHA must be a full lowercase commit SHA")


def _decode_jwt_object(segment: str, *, label: str) -> dict[str, Any]:
    if not JWT_SEGMENT_PATTERN.fullmatch(segment):
        raise CandidateError(f"smoke token {label} is not canonical base64url")
    padding = "=" * (-len(segment) % 4)
    try:
        raw = base64.b64decode(
            segment + padding,
            altchars=b"-_",
            validate=True,
        )
        document = json.loads(raw)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        raise CandidateError(f"smoke token {label} is not valid JSON") from None
    if not isinstance(document, dict):
        raise CandidateError(f"smoke token {label} is not an object")
    return document


def validate_smoke_bearer_token(token: str, *, now: int) -> None:
    if not 1 <= len(token) <= MAX_SMOKE_TOKEN_BYTES or "\n" in token or "\r" in token:
        raise CandidateError("smoke bearer token has an invalid shape")
    segments = token.split(".")
    if (
        len(segments) != 3
        or not all(segments)
        or any(JWT_SEGMENT_PATTERN.fullmatch(segment) is None for segment in segments)
    ):
        raise CandidateError("smoke bearer token is not a compact JWT")
    header = _decode_jwt_object(segments[0], label="header")
    claims = _decode_jwt_object(segments[1], label="payload")
    if header != {"alg": "HS256", "typ": "JWT"}:
        raise CandidateError("smoke token header is not exact")

    issued_at = claims.get("iat")
    expires_at = claims.get("exp")
    subject = claims.get("sub")
    scope = claims.get("scope", "")
    if (
        claims.get("iss") != "syshin0116.dev"
        or claims.get("aud") != "agent-api"
        or type(issued_at) is not int
        or type(expires_at) is not int
        or not isinstance(subject, str)
        or not subject
        or subject.startswith("anon:")
        or not isinstance(scope, str)
        or "anon" in scope.split()
    ):
        raise CandidateError("smoke token claims are not exact")
    if issued_at > now + 30 or expires_at <= issued_at:
        raise CandidateError("smoke token timestamps are invalid")
    if expires_at - issued_at > MAX_SMOKE_TOKEN_LIFETIME_SECONDS:
        raise CandidateError("long-lived smoke bearer tokens are forbidden")
    if expires_at - now < MIN_SMOKE_TOKEN_REMAINING_SECONDS:
        raise CandidateError("smoke bearer token expires before the release window")


def _require_main_at_sha(
    client: GitHubClient,
    repository: str,
    source_sha: str,
) -> None:
    document = client.get(f"/repos/{repository}/git/ref/heads/main")
    target = document.get("object")
    if not isinstance(target, dict) or target.get("type") != "commit":
        raise CandidateError("main ref did not resolve to a commit")
    if target.get("sha") != source_sha:
        raise CandidateError("main moved away from the reviewed release SHA")


def validate_preview_candidate(
    client: GitHubClient,
    *,
    repository: str,
    source_sha: str,
    pull_request_number: int,
) -> None:
    _validate_source_sha(source_sha)
    if pull_request_number < 1:
        raise CandidateError("pull request number must be positive")
    document = client.get(f"/repos/{repository}/pulls/{pull_request_number}")
    head = document.get("head")
    base = document.get("base")
    if document.get("state") != "open":
        raise CandidateError("preview pull request is no longer open")
    if not isinstance(head, dict) or not isinstance(base, dict):
        raise CandidateError("preview pull request refs are malformed")
    if head.get("sha") != source_sha:
        raise CandidateError("pull request head moved away from the built source SHA")
    head_repository = head.get("repo")
    base_repository = base.get("repo")
    if (
        not isinstance(head_repository, dict)
        or head_repository.get("full_name") != repository
        or not isinstance(base_repository, dict)
        or base_repository.get("full_name") != repository
    ):
        raise CandidateError("preview pull request repository boundary drifted")


def validate_production_candidate_once(
    client: GitHubClient,
    *,
    repository: str,
    source_sha: str,
) -> None:
    _validate_source_sha(source_sha)
    _require_main_at_sha(client, repository, source_sha)
    document = client.get(
        f"/repos/{repository}/commits/{source_sha}/check-runs",
        {"filter": "latest", "per_page": "100"},
    )
    total_count = document.get("total_count")
    check_runs = document.get("check_runs")
    if (
        not isinstance(total_count, int)
        or not isinstance(check_runs, list)
        or total_count != len(check_runs)
        or total_count > 100
    ):
        raise CandidateError("check-run response was incomplete or malformed")

    pending: list[str] = []
    for required_name in sorted(REQUIRED_PRODUCTION_CHECKS):
        named = [
            run
            for run in check_runs
            if isinstance(run, dict) and run.get("name") == required_name
        ]
        if not named:
            pending.append(required_name)
            continue
        if len(named) != 1:
            raise CandidateError("required check name was emitted more than once")
        for run in named:
            app = run.get("app")
            if run.get("head_sha") != source_sha:
                raise CandidateError(
                    "required check-run SHA did not match the candidate"
                )
            if (
                not isinstance(app, dict)
                or app.get("id") != GITHUB_ACTIONS_APP_ID
                or app.get("slug") != "github-actions"
            ):
                raise CandidateError(
                    "required check came from an unreviewed GitHub App"
                )
            status = run.get("status")
            if status != "completed":
                pending.append(required_name)
            elif run.get("conclusion") != "success":
                raise CandidateError("a required production check did not succeed")

    if pending:
        raise CandidatePending("required production checks are still pending")
    _require_main_at_sha(client, repository, source_sha)


def wait_for_production_candidate(
    client: GitHubClient,
    *,
    repository: str,
    source_sha: str,
    max_attempts: int,
    interval_seconds: float,
) -> None:
    if max_attempts < 1 or not 0 <= interval_seconds <= 60:
        raise CandidateError("production gate polling bounds are invalid")
    for attempt in range(1, max_attempts + 1):
        try:
            validate_production_candidate_once(
                client,
                repository=repository,
                source_sha=source_sha,
            )
            return
        except CandidatePending:
            if attempt == max_attempts:
                raise CandidateError(
                    "required production checks did not complete before the gate timeout"
                ) from None
            time.sleep(interval_seconds)


def _validate_rollback_revision(rollback_revision: str) -> None:
    if (
        not 1 <= len(rollback_revision) <= 63
        or not REVISION_PATTERN.fullmatch(rollback_revision)
        or not rollback_revision.startswith("agent-")
        or rollback_revision.startswith("agent-preview-")
    ):
        raise CandidateError(
            "rollback revision is not an exact production revision name"
        )


def validate_release_inputs(
    *,
    target: str,
    environment: str,
    mode: str,
    source_sha: str,
    pull_request_number: int | None,
    image_digest: str,
    rollback_revision: str,
) -> None:
    _validate_source_sha(source_sha)
    if (
        target not in EXPECTED_ENVIRONMENTS
        or environment != EXPECTED_ENVIRONMENTS[target]
    ):
        raise CandidateError("release target and environment are not an exact pair")

    if target == "preview":
        if (
            mode != "deploy"
            or pull_request_number is None
            or pull_request_number < 1
            or rollback_revision
        ):
            raise CandidateError("preview release inputs are not exact")
    elif mode == "deploy":
        if pull_request_number is not None or rollback_revision:
            raise CandidateError("production deployment inputs are not exact")
    elif mode == "rollback":
        if pull_request_number is not None or image_digest:
            raise CandidateError("production rollback inputs are not exact")
        _validate_rollback_revision(rollback_revision)
        return
    else:
        raise CandidateError("production release mode is not exact")

    image_prefix = EXPECTED_IMAGE_PREFIXES[target]
    if not image_digest.startswith(image_prefix) or not re.fullmatch(
        r"[0-9a-f]{64}", image_digest.removeprefix(image_prefix)
    ):
        raise CandidateError("release image is not an exact isolated registry digest")


def validate_release_candidate(
    client: GitHubClient,
    *,
    target: str,
    mode: str,
    repository: str,
    source_sha: str,
    event_name: str,
    ref: str,
    pull_request_number: int | None,
    rollback_revision: str,
    production_max_attempts: int = 90,
    production_interval_seconds: float = 10,
) -> None:
    if repository != EXPECTED_REPOSITORY:
        raise CandidateError("repository does not match the reviewed delivery boundary")
    if target == "preview":
        if (
            mode != "deploy"
            or event_name != "pull_request"
            or pull_request_number is None
            or ref != f"refs/pull/{pull_request_number}/merge"
            or rollback_revision
        ):
            raise CandidateError("preview release event identity is not exact")
        validate_preview_candidate(
            client,
            repository=repository,
            source_sha=source_sha,
            pull_request_number=pull_request_number,
        )
        return

    if (
        target != "production"
        or ref != "refs/heads/main"
        or pull_request_number is not None
    ):
        raise CandidateError("production release event identity is not exact")
    if mode == "rollback":
        if event_name != "workflow_dispatch":
            raise CandidateError("production rollback requires workflow_dispatch")
        _validate_source_sha(source_sha)
        _validate_rollback_revision(rollback_revision)
        _require_main_at_sha(client, repository, source_sha)
        return
    if (
        mode != "deploy"
        or event_name not in {"push", "workflow_dispatch"}
        or rollback_revision
    ):
        raise CandidateError("production deployment event identity is not exact")
    wait_for_production_candidate(
        client,
        repository=repository,
        source_sha=source_sha,
        max_attempts=production_max_attempts,
        interval_seconds=production_interval_seconds,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=("preview", "production"), required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--mode", choices=("deploy", "rollback"), required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--pull-request-number", type=int)
    parser.add_argument("--image-digest", default="")
    parser.add_argument("--rollback-revision", default="")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    validate_release_inputs(
        target=args.target,
        environment=args.environment,
        mode=args.mode,
        source_sha=args.source_sha,
        pull_request_number=args.pull_request_number,
        image_digest=args.image_digest,
        rollback_revision=args.rollback_revision,
    )
    validate_smoke_bearer_token(
        os.environ.get("AGENT_SMOKE_BEARER_TOKEN", ""),
        now=int(time.time()),
    )
    token = os.environ.get("GITHUB_TOKEN", "")
    api_url = os.environ.get("GITHUB_API_URL", "")
    client = GitHubClient(token, api_url)
    validate_release_candidate(
        client,
        target=args.target,
        mode=args.mode,
        repository=args.repository,
        source_sha=args.source_sha,
        event_name=args.event_name,
        ref=args.ref,
        pull_request_number=args.pull_request_number,
        rollback_revision=args.rollback_revision,
    )

    print("Agent release candidate verification passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CandidateError as exc:
        raise SystemExit(
            f"Agent release candidate verification failed: {exc}"
        ) from None
