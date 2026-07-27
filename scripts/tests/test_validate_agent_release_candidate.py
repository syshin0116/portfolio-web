from __future__ import annotations

import copy
import base64
import json
import urllib.error
import unittest
from collections.abc import Mapping
from typing import Any
from unittest.mock import patch

from scripts.validate_agent_release_candidate import (
    CandidateError,
    CandidatePending,
    EXPECTED_API_URL,
    GitHubClient,
    validate_preview_candidate,
    validate_production_candidate_once,
    validate_release_candidate,
    validate_release_inputs,
    validate_smoke_bearer_token,
    wait_for_production_candidate,
)

REPOSITORY = "syshin0116/syshin0116.dev"
SOURCE_SHA = "a" * 40
IMAGE_DIGEST = (
    "us-east4-docker.pkg.dev/festive-ally-503605-v7/agent/agent@sha256:" + "b" * 64
)
REQUIRED_CHECKS = ("ci/check", "protocol/compat", "wiki/verify")
REFLECTED_TOKEN = "reflected-github-api-secret-that-must-not-be-logged"


def _main_ref(sha: str = SOURCE_SHA) -> dict[str, object]:
    return {"object": {"type": "commit", "sha": sha}}


def _check_runs(
    *,
    status: str = "completed",
    conclusion: str | None = "success",
    sha: str = SOURCE_SHA,
) -> dict[str, object]:
    runs = [
        {
            "name": name,
            "head_sha": sha,
            "status": status,
            "conclusion": conclusion,
            "app": {"id": 15368, "slug": "github-actions"},
        }
        for name in REQUIRED_CHECKS
    ]
    return {"total_count": len(runs), "check_runs": runs}


def _pull_request(sha: str = SOURCE_SHA) -> dict[str, object]:
    repository = {"full_name": REPOSITORY}
    return {
        "state": "open",
        "head": {"sha": sha, "repo": repository},
        "base": {"repo": repository},
    }


def _smoke_token(*, issued_at: int, expires_at: int) -> str:
    def encode(document: dict[str, object]) -> str:
        payload = json.dumps(document, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(payload).rstrip(b"=").decode()

    return ".".join(
        (
            encode({"alg": "HS256", "typ": "JWT"}),
            encode(
                {
                    "sub": "owner:syshin0116",
                    "iss": "syshin0116.dev",
                    "aud": "agent-api",
                    "iat": issued_at,
                    "exp": expires_at,
                    "scope": "owner",
                }
            ),
            "signature",
        )
    )


class FakeGitHubClient:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = [copy.deepcopy(response) for response in responses]
        self.calls: list[tuple[str, Mapping[str, str] | None]] = []

    def get(
        self,
        path: str,
        query: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        self.calls.append((path, query))
        if not self.responses:
            raise AssertionError("unexpected GitHub API call")
        return self.responses.pop(0)


class FailingOpener:
    def open(self, *_args: object, **_kwargs: object) -> None:
        raise urllib.error.URLError(REFLECTED_TOKEN)


class AgentReleaseCandidateTests(unittest.TestCase):
    def test_production_exact_sha_and_three_successful_checks_pass(self) -> None:
        client = FakeGitHubClient([_main_ref(), _check_runs(), _main_ref()])

        validate_production_candidate_once(
            client,  # type: ignore[arg-type]
            repository=REPOSITORY,
            source_sha=SOURCE_SHA,
        )

        self.assertEqual(
            [
                (f"/repos/{REPOSITORY}/git/ref/heads/main", None),
                (
                    f"/repos/{REPOSITORY}/commits/{SOURCE_SHA}/check-runs",
                    {"filter": "latest", "per_page": "100"},
                ),
                (f"/repos/{REPOSITORY}/git/ref/heads/main", None),
            ],
            client.calls,
        )

    def test_production_pending_check_fails_closed(self) -> None:
        client = FakeGitHubClient(
            [_main_ref(), _check_runs(status="in_progress", conclusion=None)]
        )

        with self.assertRaisesRegex(CandidatePending, "still pending"):
            validate_production_candidate_once(
                client,  # type: ignore[arg-type]
                repository=REPOSITORY,
                source_sha=SOURCE_SHA,
            )

    def test_production_failed_check_fails_closed(self) -> None:
        document = _check_runs()
        document["check_runs"][1]["conclusion"] = "failure"  # type: ignore[index]
        client = FakeGitHubClient([_main_ref(), document])

        with self.assertRaisesRegex(CandidateError, "did not succeed"):
            validate_production_candidate_once(
                client,  # type: ignore[arg-type]
                repository=REPOSITORY,
                source_sha=SOURCE_SHA,
            )

    def test_production_moved_main_fails_before_reading_checks(self) -> None:
        client = FakeGitHubClient([_main_ref("b" * 40)])

        with self.assertRaisesRegex(CandidateError, "main moved"):
            validate_production_candidate_once(
                client,  # type: ignore[arg-type]
                repository=REPOSITORY,
                source_sha=SOURCE_SHA,
            )

        self.assertEqual(
            [(f"/repos/{REPOSITORY}/git/ref/heads/main", None)],
            client.calls,
        )

    def test_production_check_run_sha_mismatch_fails_closed(self) -> None:
        client = FakeGitHubClient([_main_ref(), _check_runs(sha="b" * 40)])

        with self.assertRaisesRegex(CandidateError, "SHA did not match"):
            validate_production_candidate_once(
                client,  # type: ignore[arg-type]
                repository=REPOSITORY,
                source_sha=SOURCE_SHA,
            )

    def test_production_duplicate_required_check_name_fails_closed(self) -> None:
        document = _check_runs()
        document["check_runs"].append(  # type: ignore[union-attr]
            copy.deepcopy(document["check_runs"][0])  # type: ignore[index]
        )
        document["total_count"] = 4
        client = FakeGitHubClient([_main_ref(), document])

        with self.assertRaisesRegex(CandidateError, "more than once"):
            validate_production_candidate_once(
                client,  # type: ignore[arg-type]
                repository=REPOSITORY,
                source_sha=SOURCE_SHA,
            )

    def test_production_pending_checks_time_out_without_passing(self) -> None:
        client = FakeGitHubClient(
            [
                _main_ref(),
                _check_runs(status="queued", conclusion=None),
                _main_ref(),
                _check_runs(status="queued", conclusion=None),
            ]
        )

        with self.assertRaisesRegex(CandidateError, "gate timeout"):
            wait_for_production_candidate(
                client,  # type: ignore[arg-type]
                repository=REPOSITORY,
                source_sha=SOURCE_SHA,
                max_attempts=2,
                interval_seconds=0,
            )

    def test_production_pending_checks_can_become_successful(self) -> None:
        client = FakeGitHubClient(
            [
                _main_ref(),
                _check_runs(status="queued", conclusion=None),
                _main_ref(),
                _check_runs(),
                _main_ref(),
            ]
        )

        wait_for_production_candidate(
            client,  # type: ignore[arg-type]
            repository=REPOSITORY,
            source_sha=SOURCE_SHA,
            max_attempts=2,
            interval_seconds=0,
        )

        self.assertEqual([], client.responses)

    def test_production_main_moving_after_checks_fails_closed(self) -> None:
        client = FakeGitHubClient([_main_ref(), _check_runs(), _main_ref("b" * 40)])

        with self.assertRaisesRegex(CandidateError, "main moved"):
            validate_production_candidate_once(
                client,  # type: ignore[arg-type]
                repository=REPOSITORY,
                source_sha=SOURCE_SHA,
            )

    def test_production_check_from_wrong_app_fails_closed(self) -> None:
        document = _check_runs()
        document["check_runs"][0]["app"] = {  # type: ignore[index]
            "id": 1,
            "slug": "unreviewed",
        }
        client = FakeGitHubClient([_main_ref(), document])

        with self.assertRaisesRegex(CandidateError, "unreviewed GitHub App"):
            validate_production_candidate_once(
                client,  # type: ignore[arg-type]
                repository=REPOSITORY,
                source_sha=SOURCE_SHA,
            )

    def test_production_missing_required_check_stays_pending(self) -> None:
        document = _check_runs()
        document["check_runs"].pop()  # type: ignore[union-attr]
        document["total_count"] = 2
        client = FakeGitHubClient([_main_ref(), document])

        with self.assertRaisesRegex(CandidatePending, "still pending"):
            validate_production_candidate_once(
                client,  # type: ignore[arg-type]
                repository=REPOSITORY,
                source_sha=SOURCE_SHA,
            )

    def test_production_rollback_allows_red_main_without_check_reads(self) -> None:
        client = FakeGitHubClient([_main_ref()])

        validate_release_candidate(
            client,  # type: ignore[arg-type]
            target="production",
            mode="rollback",
            repository=REPOSITORY,
            source_sha=SOURCE_SHA,
            event_name="workflow_dispatch",
            ref="refs/heads/main",
            pull_request_number=None,
            rollback_revision="agent-g12345678-r123-a1",
        )

        self.assertEqual(
            [(f"/repos/{REPOSITORY}/git/ref/heads/main", None)],
            client.calls,
        )

    def test_production_rollback_rejects_non_workflow_dispatch(self) -> None:
        client = FakeGitHubClient([])

        with self.assertRaisesRegex(CandidateError, "requires workflow_dispatch"):
            validate_release_candidate(
                client,  # type: ignore[arg-type]
                target="production",
                mode="rollback",
                repository=REPOSITORY,
                source_sha=SOURCE_SHA,
                event_name="push",
                ref="refs/heads/main",
                pull_request_number=None,
                rollback_revision="agent-g12345678-r123-a1",
            )

        self.assertEqual([], client.calls)

    def test_production_rollback_rejects_nonexact_revision_name(self) -> None:
        client = FakeGitHubClient([])

        with self.assertRaisesRegex(CandidateError, "exact production revision"):
            validate_release_candidate(
                client,  # type: ignore[arg-type]
                target="production",
                mode="rollback",
                repository=REPOSITORY,
                source_sha=SOURCE_SHA,
                event_name="workflow_dispatch",
                ref="refs/heads/main",
                pull_request_number=None,
                rollback_revision="agent-preview-g12345678-r123-a1",
            )

        self.assertEqual([], client.calls)

    def test_release_inputs_require_exact_digest_or_exact_rollback(self) -> None:
        validate_release_inputs(
            target="production",
            environment="Agent Production",
            mode="deploy",
            source_sha=SOURCE_SHA,
            pull_request_number=None,
            image_digest=IMAGE_DIGEST,
            rollback_revision="",
        )
        validate_release_inputs(
            target="production",
            environment="Agent Production",
            mode="rollback",
            source_sha=SOURCE_SHA,
            pull_request_number=None,
            image_digest="",
            rollback_revision="agent-g12345678-r123-a1",
        )

        with self.assertRaisesRegex(CandidateError, "not an exact pair"):
            validate_release_inputs(
                target="production",
                environment="Agent Preview",
                mode="deploy",
                source_sha=SOURCE_SHA,
                pull_request_number=None,
                image_digest=IMAGE_DIGEST,
                rollback_revision="",
            )
        with self.assertRaisesRegex(CandidateError, "isolated registry digest"):
            validate_release_inputs(
                target="production",
                environment="Agent Production",
                mode="deploy",
                source_sha=SOURCE_SHA,
                pull_request_number=None,
                image_digest="agent:latest",
                rollback_revision="",
            )
        with self.assertRaisesRegex(CandidateError, "mode is not exact"):
            validate_release_inputs(
                target="production",
                environment="Agent Production",
                mode="typo",
                source_sha=SOURCE_SHA,
                pull_request_number=None,
                image_digest="",
                rollback_revision="",
            )

    def test_smoke_token_requires_fresh_bounded_owner_jwt(self) -> None:
        now = 2_000_000_000
        validate_smoke_bearer_token(
            _smoke_token(issued_at=now, expires_at=now + 4_500),
            now=now,
        )

        cases = {
            "expired": _smoke_token(issued_at=now - 4_500, expires_at=now - 1),
            "too_short": _smoke_token(issued_at=now, expires_at=now + 3_899),
            "long_lived": _smoke_token(issued_at=now, expires_at=now + 7_201),
        }
        for name, token in cases.items():
            with self.subTest(case=name), self.assertRaises(CandidateError):
                validate_smoke_bearer_token(token, now=now)

    def test_preview_current_same_repository_head_passes(self) -> None:
        client = FakeGitHubClient([_pull_request()])

        validate_preview_candidate(
            client,  # type: ignore[arg-type]
            repository=REPOSITORY,
            source_sha=SOURCE_SHA,
            pull_request_number=127,
        )

        self.assertEqual(
            [(f"/repos/{REPOSITORY}/pulls/127", None)],
            client.calls,
        )

    def test_preview_synchronized_head_mismatch_fails_closed(self) -> None:
        client = FakeGitHubClient([_pull_request("b" * 40)])

        with self.assertRaisesRegex(CandidateError, "head moved"):
            validate_preview_candidate(
                client,  # type: ignore[arg-type]
                repository=REPOSITORY,
                source_sha=SOURCE_SHA,
                pull_request_number=127,
            )

    def test_github_transport_error_never_reflects_server_text(self) -> None:
        with patch(
            "scripts.validate_agent_release_candidate.urllib.request.build_opener",
            return_value=FailingOpener(),
        ):
            client = GitHubClient("x" * 20, EXPECTED_API_URL)
            with self.assertRaises(CandidateError) as raised:
                client.get(f"/repos/{REPOSITORY}/git/ref/heads/main")

        self.assertNotIn(REFLECTED_TOKEN, str(raised.exception))

    def test_unexpected_api_origin_error_never_reflects_origin(self) -> None:
        with self.assertRaises(CandidateError) as raised:
            GitHubClient("x" * 20, f"https://{REFLECTED_TOKEN}.invalid")

        self.assertNotIn(REFLECTED_TOKEN, str(raised.exception))


if __name__ == "__main__":
    unittest.main()
