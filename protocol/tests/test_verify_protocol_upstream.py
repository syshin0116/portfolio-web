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
        self.python_binding = (
            REPO_ROOT / "protocol/generated/python/protocol.py"
        ).read_bytes()
        self.typescript_binding = (
            REPO_ROOT / "protocol/generated/typescript/protocol.ts"
        ).read_bytes()
        self.payloads = {
            "protocol.openapi": b"protocol openapi\n",
            "protocol.cddl": b"protocol cddl\n",
            "protocol.pythonBinding": self.python_binding,
            "protocol.typescriptBinding": self.typescript_binding,
            "aegra.openapi": b"aegra openapi\n",
            "aegra.route": b"aegra route\n",
            "aegra.wireBuilders": b"aegra wire builders\n",
            "aegra.commands": b"aegra commands\n",
        }
        self.lock = {
            "lockVersion": 1,
            "protocol": {
                "repository": "https://github.com/langchain-ai/agent-protocol",
                "commit": "a" * 40,
                "artifacts": {
                    "openapi": self._artifact(
                        "protocol.openapi",
                        "openapi.json",
                    ),
                    "cddl": self._artifact(
                        "protocol.cddl",
                        "streaming/protocol.cddl",
                    ),
                    "pythonBinding": {
                        **self._artifact(
                            "protocol.pythonBinding",
                            "streaming/py/langchain_protocol/protocol.py",
                        ),
                        "vendoredPath": "protocol/generated/python/protocol.py",
                    },
                    "typescriptBinding": {
                        **self._artifact(
                            "protocol.typescriptBinding",
                            "streaming/js/protocol.ts",
                        ),
                        "vendoredPath": "protocol/generated/typescript/protocol.ts",
                    },
                },
            },
            "aegra": {
                "repository": "https://github.com/ibbybuilds/aegra",
                "commit": "b" * 40,
                "artifacts": {
                    "openapi": self._artifact(
                        "aegra.openapi",
                        "docs/openapi.json",
                    ),
                    "route": self._artifact(
                        "aegra.route",
                        "libs/aegra-api/src/aegra_api/api/event_streaming.py",
                    ),
                    "wireBuilders": self._artifact(
                        "aegra.wireBuilders",
                        "libs/aegra-api/src/aegra_api/services/"
                        "event_streaming/protocol.py",
                    ),
                    "commands": self._artifact(
                        "aegra.commands",
                        "libs/aegra-api/src/aegra_api/services/"
                        "event_streaming/commands.py",
                    ),
                },
            },
        }
        self.responses = self._responses()

    def _artifact(self, label: str, upstream_path: str) -> dict[str, str]:
        return {
            "upstreamPath": upstream_path,
            "sha256": hashlib.sha256(self.payloads[label]).hexdigest(),
        }

    def _responses(self) -> dict[str, bytes]:
        responses: dict[str, bytes] = {}
        for section_name in ("protocol", "aegra"):
            section = self.lock[section_name]
            for artifact_name, artifact in section["artifacts"].items():
                label = f"{section_name}.{artifact_name}"
                url = upstream._raw_url(
                    section["repository"],
                    section["commit"],
                    artifact["upstreamPath"],
                )
                responses[url] = self.payloads[label]
        return responses

    def _fetch(self, url: str) -> bytes:
        try:
            return self.responses[url]
        except KeyError:
            self.fail(f"unexpected URL: {url}")

    def test_success_with_injected_fetch(self) -> None:
        self.assertEqual(
            [
                "protocol.openapi",
                "protocol.cddl",
                "protocol.pythonBinding",
                "protocol.typescriptBinding",
                "aegra.openapi",
                "aegra.route",
                "aegra.wireBuilders",
                "aegra.commands",
            ],
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
            if url.endswith("/streaming/py/langchain_protocol/protocol.py"):
                return different
            return self._fetch(url)

        with self.assertRaisesRegex(
            upstream.UpstreamVerificationError,
            "vendored bytes differ",
        ):
            upstream.verify_upstream(lock, fetch=fetch)

    def test_rejects_unsupported_or_non_integer_lock_version(self) -> None:
        for lock_version in (None, 0, True, 2, "1"):
            with self.subTest(lock_version=lock_version):
                lock = copy.deepcopy(self.lock)
                lock["lockVersion"] = lock_version
                with self.assertRaisesRegex(
                    upstream.UpstreamVerificationError,
                    "lockVersion must be the integer 1",
                ):
                    upstream.verify_upstream(lock, fetch=self._fetch)

    def test_rejects_repository_swapped_between_sections(self) -> None:
        lock = copy.deepcopy(self.lock)
        lock["protocol"]["repository"] = "https://github.com/ibbybuilds/aegra"

        def fetch(url: str) -> bytes:
            if url in self.responses:
                return self.responses[url]
            protocol_paths = {
                "/openapi.json": "protocol.openapi",
                "/streaming/protocol.cddl": "protocol.cddl",
                "/streaming/py/langchain_protocol/protocol.py": (
                    "protocol.pythonBinding"
                ),
                "/streaming/js/protocol.ts": "protocol.typescriptBinding",
            }
            for suffix, label in protocol_paths.items():
                if url.endswith(suffix):
                    return self.payloads[label]
            self.fail(f"unexpected URL: {url}")

        with self.assertRaisesRegex(
            upstream.UpstreamVerificationError,
            "protocol must use repository",
        ):
            upstream.verify_upstream(lock, fetch=fetch)

    def test_rejects_deleted_required_artifact(self) -> None:
        required = {
            "protocol": (
                "openapi",
                "cddl",
                "pythonBinding",
                "typescriptBinding",
            ),
            "aegra": (
                "openapi",
                "route",
                "wireBuilders",
                "commands",
            ),
        }
        for section_name, artifact_names in required.items():
            for artifact_name in artifact_names:
                with self.subTest(
                    section=section_name,
                    artifact=artifact_name,
                ):
                    lock = copy.deepcopy(self.lock)
                    del lock[section_name]["artifacts"][artifact_name]
                    with self.assertRaisesRegex(
                        upstream.UpstreamVerificationError,
                        rf"{section_name} artifacts.*missing=.*{artifact_name}",
                    ):
                        upstream.verify_upstream(lock, fetch=self._fetch)

    def test_rejects_extra_artifact(self) -> None:
        lock = copy.deepcopy(self.lock)
        lock["aegra"]["artifacts"]["replacement"] = self._artifact(
            "aegra.openapi",
            "docs/openapi.json",
        )
        with self.assertRaisesRegex(
            upstream.UpstreamVerificationError,
            r"aegra artifacts.*extra=.*replacement",
        ):
            upstream.verify_upstream(lock, fetch=self._fetch)

    def test_rejects_deleted_or_wrong_binding_vendored_path(self) -> None:
        bindings = {
            "pythonBinding": "protocol/generated/python/protocol.py",
            "typescriptBinding": "protocol/generated/typescript/protocol.ts",
        }
        for artifact_name, expected_path in bindings.items():
            for mutation in ("deleted", "wrong"):
                with self.subTest(artifact=artifact_name, mutation=mutation):
                    lock = copy.deepcopy(self.lock)
                    artifact = lock["protocol"]["artifacts"][artifact_name]
                    if mutation == "deleted":
                        del artifact["vendoredPath"]
                    else:
                        artifact["vendoredPath"] = f"wrong/{artifact_name}"
                    with self.assertRaisesRegex(
                        upstream.UpstreamVerificationError,
                        rf"{artifact_name} must use vendoredPath "
                        rf"{expected_path!r}",
                    ):
                        upstream.verify_upstream(lock, fetch=self._fetch)

    def test_rejects_wrong_upstream_path(self) -> None:
        lock = copy.deepcopy(self.lock)
        route = lock["aegra"]["artifacts"]["route"]
        route["upstreamPath"] = "docs/openapi.json"
        route["sha256"] = hashlib.sha256(self.payloads["aegra.openapi"]).hexdigest()
        with self.assertRaisesRegex(
            upstream.UpstreamVerificationError,
            "aegra.route must use upstreamPath",
        ):
            upstream.verify_upstream(lock, fetch=self._fetch)


if __name__ == "__main__":
    unittest.main()
