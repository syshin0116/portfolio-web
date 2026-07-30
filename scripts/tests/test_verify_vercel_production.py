from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import verify_vercel_production as verifier  # noqa: E402

SHA = "49e3349a5f4bfc7a7664c9924c842b2a16ce2e53"
OLD_SHA = "099589b31dab28c4993753a666d0475686b860fd"
DEPLOYMENT_URL = "syshin0116-5wwb8dy37-syshin0116.vercel.app"


def payload(**overrides: object) -> bytes:
    document: dict[str, object] = {
        "schemaVersion": 1,
        "deploymentId": "dpl_FciFB9jCy6zHMkACTrySxDGtHUu8",
        "deploymentUrl": DEPLOYMENT_URL,
        "gitSha": SHA,
    }
    document.update(overrides)
    return json.dumps(document).encode()


class VercelProductionVerifierTests(unittest.TestCase):
    def test_parses_the_exact_revision_contract(self) -> None:
        self.assertEqual(
            verifier.parse_revision_payload(payload()),
            verifier.ProductionRevision(
                deployment_id="dpl_FciFB9jCy6zHMkACTrySxDGtHUu8",
                deployment_url=DEPLOYMENT_URL,
                git_sha=SHA,
            ),
        )

    def test_rejects_duplicate_and_extra_keys(self) -> None:
        duplicate = (
            b'{"schemaVersion":1,"deploymentId":"dpl_one",'
            b'"deploymentId":"dpl_two",'
            b'"deploymentUrl":"one.vercel.app",'
            b'"gitSha":"' + SHA.encode() + b'"}'
        )
        with self.assertRaisesRegex(verifier.VerificationError, "duplicate JSON key"):
            verifier.parse_revision_payload(duplicate)
        with self.assertRaisesRegex(verifier.VerificationError, "keys differ"):
            verifier.parse_revision_payload(payload(extra=True))

    def test_rejects_invalid_field_types_and_values(self) -> None:
        invalid_documents = (
            payload(schemaVersion=True),
            payload(deploymentId="not-a-deployment"),
            payload(deploymentUrl="https://one.vercel.app"),
            payload(gitSha="short"),
        )
        for document in invalid_documents:
            with self.subTest(document=document):
                with self.assertRaises(verifier.VerificationError):
                    verifier.parse_revision_payload(document)

    def test_normalizes_only_one_https_vercel_origin(self) -> None:
        self.assertEqual(
            verifier.normalize_expected_deployment_url(f"https://{DEPLOYMENT_URL}"),
            DEPLOYMENT_URL,
        )
        self.assertIsNone(verifier.normalize_expected_deployment_url(""))
        for value in (
            f"http://{DEPLOYMENT_URL}",
            f"https://{DEPLOYMENT_URL}/path",
            "https://example.com",
        ):
            with self.subTest(value=value):
                with self.assertRaises(verifier.VerificationError):
                    verifier.normalize_expected_deployment_url(value)

    def test_retries_until_sha_and_unique_url_both_match(self) -> None:
        revisions = iter(
            (
                verifier.ProductionRevision(
                    deployment_id="dpl_old",
                    deployment_url="old.vercel.app",
                    git_sha=OLD_SHA,
                ),
                verifier.ProductionRevision(
                    deployment_id="dpl_current",
                    deployment_url=DEPLOYMENT_URL,
                    git_sha=SHA,
                ),
            )
        )
        sleeps: list[float] = []

        result = verifier.wait_for_production_revision(
            expected_sha=SHA,
            expected_deployment_url=f"https://{DEPLOYMENT_URL}",
            attempts=2,
            interval_seconds=3,
            timeout_seconds=4,
            fetcher=lambda timeout: next(revisions),
            sleeper=sleeps.append,
        )

        self.assertEqual(result.deployment_id, "dpl_current")
        self.assertEqual(sleeps, [3])

    def test_rejects_a_wrong_unique_url_even_when_the_sha_matches(self) -> None:
        same_commit_old_deployment = verifier.ProductionRevision(
            deployment_id="dpl_old",
            deployment_url="old.vercel.app",
            git_sha=SHA,
        )

        with self.assertRaisesRegex(
            verifier.VerificationError,
            "deploymentUrl=old.vercel.app",
        ):
            verifier.wait_for_production_revision(
                expected_sha=SHA,
                expected_deployment_url=f"https://{DEPLOYMENT_URL}",
                attempts=1,
                interval_seconds=0,
                timeout_seconds=1,
                fetcher=lambda timeout: same_commit_old_deployment,
                sleeper=lambda seconds: None,
            )

    def test_fails_after_the_bounded_attempts(self) -> None:
        old_revision = verifier.ProductionRevision(
            deployment_id="dpl_old",
            deployment_url="old.vercel.app",
            git_sha=OLD_SHA,
        )
        with self.assertRaisesRegex(
            verifier.VerificationError,
            "did not converge",
        ):
            verifier.wait_for_production_revision(
                expected_sha=SHA,
                attempts=2,
                interval_seconds=0,
                timeout_seconds=1,
                fetcher=lambda timeout: old_revision,
                sleeper=lambda seconds: None,
            )


if __name__ == "__main__":
    unittest.main()
