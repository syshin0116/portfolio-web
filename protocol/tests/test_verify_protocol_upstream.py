from __future__ import annotations

import copy
import hashlib
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import verify_protocol_upstream as upstream  # noqa: E402


class UpstreamUrlTests(unittest.TestCase):
    def test_rejects_unapproved_repository(self) -> None:
        with self.assertRaisesRegex(upstream.UpstreamVerificationError, "not allowed"):
            upstream._raw_url(
                "https://example.com/owner/repo",
                "a" * 40,
                "schema.json",
            )

    def test_rejects_non_full_commit(self) -> None:
        with self.assertRaisesRegex(
            upstream.UpstreamVerificationError, "full lowercase"
        ):
            upstream._raw_url(
                "https://github.com/langchain-ai/agent-protocol",
                "main",
                "schema.json",
            )

    def test_rejects_parent_path(self) -> None:
        with self.assertRaisesRegex(upstream.UpstreamVerificationError, "unsafe"):
            upstream._raw_url(
                "https://github.com/langchain-ai/agent-protocol",
                "a" * 40,
                "../schema.json",
            )


class UpstreamArtifactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.binding = (
            REPO_ROOT / "protocol/generated/python/protocol.py"
        ).read_bytes()
        self.aegra_artifact = b"aegra artifact\n"
        self.lock = {
            "protocol": {
                "repository": "https://github.com/langchain-ai/agent-protocol",
                "commit": "a" * 40,
                "artifacts": {
                    "pythonBinding": {
                        "upstreamPath": "streaming/py/protocol.py",
                        "vendoredPath": "protocol/generated/python/protocol.py",
                        "sha256": hashlib.sha256(self.binding).hexdigest(),
                    }
                },
            },
            "aegra": {
                "repository": "https://github.com/ibbybuilds/aegra",
                "commit": "b" * 40,
                "artifacts": {
                    "route": {
                        "upstreamPath": "route.py",
                        "sha256": hashlib.sha256(self.aegra_artifact).hexdigest(),
                    }
                },
            },
        }

    def _fetch(self, url: str) -> bytes:
        if "langchain-ai/agent-protocol" in url:
            return self.binding
        if "ibbybuilds/aegra" in url:
            return self.aegra_artifact
        self.fail(f"unexpected URL: {url}")

    def test_success_with_injected_fetch(self) -> None:
        self.assertEqual(
            ["protocol.pythonBinding", "aegra.route"],
            upstream.verify_upstream(self.lock, fetch=self._fetch),
        )

    def test_rejects_digest_mismatch(self) -> None:
        lock = copy.deepcopy(self.lock)
        lock["aegra"]["artifacts"]["route"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(
            upstream.UpstreamVerificationError, "digest differs"
        ):
            upstream.verify_upstream(lock, fetch=self._fetch)

    def test_rejects_vendored_mismatch(self) -> None:
        different = b"different generated binding\n"
        lock = copy.deepcopy(self.lock)
        lock["protocol"]["artifacts"]["pythonBinding"]["sha256"] = hashlib.sha256(
            different
        ).hexdigest()

        def fetch(url: str) -> bytes:
            if "langchain-ai/agent-protocol" in url:
                return different
            return self._fetch(url)

        with self.assertRaisesRegex(
            upstream.UpstreamVerificationError,
            "vendored bytes differ",
        ):
            upstream.verify_upstream(lock, fetch=fetch)

    def test_rejects_vendored_parent_path(self) -> None:
        lock = copy.deepcopy(self.lock)
        lock["protocol"]["artifacts"]["pythonBinding"]["vendoredPath"] = (
            "../protocol.py"
        )
        with self.assertRaisesRegex(
            upstream.UpstreamVerificationError,
            "unsafe vendored path",
        ):
            upstream.verify_upstream(lock, fetch=self._fetch)


if __name__ == "__main__":
    unittest.main()
