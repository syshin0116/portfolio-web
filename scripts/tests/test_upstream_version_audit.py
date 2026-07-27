from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import URLError

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "upstream-version-audit"
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import upstream_version_audit as audit  # noqa: E402

PYTHON_VERSIONS = {
    "aegra-api": "0.9.24",
    "aegra-cli": "0.9.24",
    "deepagents": "0.6.12",
    "langgraph": "1.2.9",
    "langgraph-sdk": "0.4.2",
}
NPM_VERSIONS = {
    "@assistant-ui/react": "0.14.28",
    "@assistant-ui/react-langgraph": "0.14.13",
    "@langchain/langgraph-sdk": "1.9.28",
}


def fixture(name: str) -> object:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def pypi_payload(package: str, version: str) -> dict[str, object]:
    major, minor, patch = (int(part) for part in version.split("."))
    prerelease = f"{major + 1}.0.0rc1"
    return {
        "info": {"name": package, "version": version},
        "releases": {
            version: [{"yanked": False}],
            prerelease: [{"yanked": False}],
            f"{major + 2}.0.0": [{"yanked": True}],
            f"{major}.{minor}.{max(0, patch - 1)}": [{"yanked": False}],
        },
    }


def npm_payload(package: str, version: str) -> dict[str, object]:
    major, minor, patch = (int(part) for part in version.split("."))
    prerelease = f"{major}.{minor + 1}.0-rc.1"
    previous = f"{major}.{minor}.{max(0, patch - 1)}"
    return {
        "name": package,
        "dist-tags": {"latest": version, "next": prerelease},
        "versions": {
            previous: {"name": package, "version": previous},
            version: {"name": package, "version": version},
            prerelease: {"name": package, "version": prerelease},
        },
    }


class OfflineFetcher:
    def __init__(
        self,
        *,
        overrides: dict[str, str] | None = None,
        failures: frozenset[str] = frozenset(),
    ) -> None:
        self.overrides = overrides or {}
        self.failures = failures
        self.calls: list[str] = []

    def __call__(self, source: audit.Source) -> audit.JsonResponse:
        self.calls.append(source.package)
        if source.package in self.failures:
            raise audit.SourceError(f"{source.package}: fixture network failure")
        if source.ecosystem == "pypi":
            version = self.overrides.get(
                source.package,
                PYTHON_VERSIONS[source.package],
            )
            payload: object = pypi_payload(source.package, version)
        elif source.ecosystem == "npm":
            version = self.overrides.get(
                source.package,
                NPM_VERSIONS[source.package],
            )
            payload = npm_payload(source.package, version)
        else:
            payload = fixture("github.json")
        return audit.JsonResponse(
            data=payload,
            final_url=source.canonical_url,
            headers={},
        )


def write_base_repository(root: Path) -> None:
    (root / "agent").mkdir(parents=True)
    (root / "protocol").mkdir()
    (root / "web").mkdir()
    dependency_lines = "\n".join(
        f'    "{package}=={version}",' for package, version in PYTHON_VERSIONS.items()
    )
    (root / audit.PYTHON_MANIFEST).write_text(
        (
            "[project]\n"
            'name = "syshin0116-dev-agent"\n'
            "dependencies = [\n"
            f"{dependency_lines}\n"
            "]\n"
        ),
        encoding="utf-8",
    )
    package_blocks = "\n".join(
        (
            "[[package]]\n"
            f'name = "{package}"\n'
            f'version = "{version}"\n'
            'source = { registry = "https://pypi.org/simple" }\n'
        )
        for package, version in PYTHON_VERSIONS.items()
    )
    requirement_lines = "\n".join(
        (f'    {{ name = "{package}", specifier = "=={version}" }},')
        for package, version in PYTHON_VERSIONS.items()
    )
    (root / audit.PYTHON_LOCK).write_text(
        (
            f"{package_blocks}\n"
            "[[package]]\n"
            'name = "syshin0116-dev-agent"\n'
            'version = "0.1.0"\n'
            'source = { editable = "agent" }\n'
            "[package.metadata]\n"
            "requires-dist = [\n"
            f"{requirement_lines}\n"
            "]\n"
        ),
        encoding="utf-8",
    )
    protocol_lock = {
        "lockVersion": 1,
        "protocol": {
            "repository": (
                f"https://github.com/{audit.CANONICAL_AGENT_PROTOCOL_REPOSITORY}"
            ),
            "tag": "langchain-protocol==0.0.18",
            "releaseVersion": "0.0.18",
            "commit": "0" * 40,
            "artifacts": {
                "pythonBinding": {"package": "langchain-protocol==0.0.18"},
                "typescriptBinding": {"package": "@langchain/protocol@0.0.18"},
            },
        },
        "aegra": {
            "repository": audit.CANONICAL_AEGRA_REPOSITORY,
            "tag": "v0.9.24",
        },
    }
    (root / audit.PROTOCOL_LOCK).write_text(
        json.dumps(protocol_lock, indent=2),
        encoding="utf-8",
    )
    (root / audit.NPM_MANIFEST).write_text(
        json.dumps(
            {
                "dependencies": {
                    "@langchain/langgraph-sdk": "^1.0.2",
                },
                "devDependencies": {},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (root / audit.NPM_LOCK).write_text(
        """
{
  "lockfileVersion": 1,
  "configVersion": 0,
  "workspaces": {
    "": {
      "dependencies": {
        "@langchain/langgraph-sdk": "^1.0.2",
      },
      "devDependencies": {},
    },
  },
  "packages": {
    "@langchain/langgraph-sdk": [
      "@langchain/langgraph-sdk@1.9.28",
      "",
      {},
      "sha512-fixture",
    ],
  },
}
""".lstrip(),
        encoding="utf-8",
    )


def activate_assistant_ui(root: Path, *, partial: bool = False) -> None:
    dependencies = {
        "@assistant-ui/react": NPM_VERSIONS["@assistant-ui/react"],
        "@langchain/langgraph-sdk": NPM_VERSIONS["@langchain/langgraph-sdk"],
    }
    if not partial:
        dependencies["@assistant-ui/react-langgraph"] = NPM_VERSIONS[
            "@assistant-ui/react-langgraph"
        ]
    (root / audit.NPM_MANIFEST).write_text(
        json.dumps(
            {"dependencies": dependencies, "devDependencies": {}},
            indent=2,
        ),
        encoding="utf-8",
    )
    packages = {
        package: [f"{package}@{version}", "", {}, "sha512-fixture"]
        for package, version in dependencies.items()
    }
    (root / audit.NPM_LOCK).write_text(
        json.dumps(
            {
                "lockfileVersion": 1,
                "configVersion": 0,
                "workspaces": {
                    "": {
                        "dependencies": dependencies,
                        "devDependencies": {},
                    }
                },
                "packages": packages,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def target(document: dict[str, object], target_id: str) -> dict[str, object]:
    targets = document["targets"]
    if not isinstance(targets, list):
        raise AssertionError("targets must be a list")
    return next(item for item in targets if item["id"] == target_id)


class OfficialShapeTests(unittest.TestCase):
    def test_pypi_fixture_ignores_prerelease_and_yanked_release(self) -> None:
        source = audit._pypi_source("aegra-api")
        release = audit._latest_pypi(
            source,
            audit.JsonResponse(
                fixture("pypi.json"),
                source.canonical_url,
                {},
            ),
        )

        self.assertEqual("0.9.24", release.version.text)

    def test_npm_fixture_ignores_prerelease_and_deprecated_release(self) -> None:
        source = audit._npm_source("@assistant-ui/react")
        release = audit._latest_npm(
            source,
            audit.JsonResponse(
                fixture("npm.json"),
                source.canonical_url,
                {},
            ),
        )

        self.assertEqual("0.14.28", release.version.text)

    def test_github_fixture_ignores_draft_prerelease_and_other_tag_family(
        self,
    ) -> None:
        source = audit._github_releases_source(
            audit.CANONICAL_AGENT_PROTOCOL_REPOSITORY,
            "langchain-protocol==",
        )
        release = audit._latest_github(
            source,
            audit.JsonResponse(
                fixture("github.json"),
                source.canonical_url,
                {},
            ),
        )

        self.assertEqual("0.0.18", release.version.text)
        self.assertIn(
            "langchain-ai/agent-protocol/releases/tag/",
            release.release_url,
        )

    def test_github_release_must_belong_to_canonical_repository(self) -> None:
        payload = copy.deepcopy(fixture("github.json"))
        if not isinstance(payload, list) or not isinstance(payload[0], dict):
            self.fail("invalid fixture")
        payload[0]["url"] = "https://api.github.com/repos/attacker/repo/releases/18"
        source = audit._github_releases_source(
            audit.CANONICAL_AGENT_PROTOCOL_REPOSITORY,
            "langchain-protocol==",
        )

        with self.assertRaisesRegex(audit.SourceError, "canonical repository"):
            audit._latest_github(
                source,
                audit.JsonResponse(payload, source.canonical_url, {}),
            )

    def test_pypi_yanked_rejects_integer_bool_confusion(self) -> None:
        payload = copy.deepcopy(fixture("pypi.json"))
        if not isinstance(payload, dict):
            self.fail("invalid fixture")
        releases = payload["releases"]
        if not isinstance(releases, dict):
            self.fail("invalid fixture")
        files = releases["0.9.24"]
        if not isinstance(files, list) or not isinstance(files[0], dict):
            self.fail("invalid fixture")
        files[0]["yanked"] = 0
        source = audit._pypi_source("aegra-api")

        with self.assertRaisesRegex(audit.SourceError, "must be a boolean"):
            audit._latest_pypi(
                source,
                audit.JsonResponse(payload, source.canonical_url, {}),
            )

    def test_github_flags_reject_integer_bool_confusion(self) -> None:
        payload = copy.deepcopy(fixture("github.json"))
        if not isinstance(payload, list) or not isinstance(payload[0], dict):
            self.fail("invalid fixture")
        payload[0]["draft"] = 0
        source = audit._github_releases_source(
            audit.CANONICAL_AGENT_PROTOCOL_REPOSITORY,
            "langchain-protocol==",
        )

        with self.assertRaisesRegex(audit.SourceError, "must be a boolean"):
            audit._latest_github(
                source,
                audit.JsonResponse(payload, source.canonical_url, {}),
            )

    def test_npm_version_record_rejects_type_confusion(self) -> None:
        payload = copy.deepcopy(fixture("npm.json"))
        if not isinstance(payload, dict):
            self.fail("invalid fixture")
        versions = payload["versions"]
        if not isinstance(versions, dict):
            self.fail("invalid fixture")
        versions["0.14.28"] = True
        source = audit._npm_source("@assistant-ui/react")

        with self.assertRaisesRegex(audit.SourceError, "expected an object"):
            audit._latest_npm(
                source,
                audit.JsonResponse(payload, source.canonical_url, {}),
            )

    def test_npm_deprecated_field_rejects_boolean_string_confusion(self) -> None:
        payload = copy.deepcopy(fixture("npm.json"))
        if not isinstance(payload, dict):
            self.fail("invalid fixture")
        versions = payload["versions"]
        if not isinstance(versions, dict) or not isinstance(versions["1.0.0"], dict):
            self.fail("invalid fixture")
        versions["1.0.0"]["deprecated"] = False
        source = audit._npm_source("@assistant-ui/react")

        with self.assertRaisesRegex(
            audit.SourceError,
            "deprecated must be a string",
        ):
            audit._latest_npm(
                source,
                audit.JsonResponse(payload, source.canonical_url, {}),
            )


class FakeHttpResponse:
    def __init__(
        self,
        *,
        payload: bytes,
        final_url: str,
        headers: dict[str, str] | None = None,
        status: object = 200,
    ) -> None:
        self.payload = payload
        self.final_url = final_url
        self.headers = headers or {"Content-Type": "application/json"}
        self.status = status

    def __enter__(self) -> FakeHttpResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def geturl(self) -> str:
        return self.final_url

    def read(self, count: int) -> bytes:
        return self.payload[:count]


class FakeOpener:
    def __init__(
        self,
        response: FakeHttpResponse | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.timeout: object = None

    def open(self, _request: object, *, timeout: object) -> FakeHttpResponse:
        self.timeout = timeout
        if self.error is not None:
            raise self.error
        if self.response is None:
            raise AssertionError("fake response missing")
        return self.response


class FetchBoundaryTests(unittest.TestCase):
    def test_unknown_target_is_rejected_before_network(self) -> None:
        source = audit._pypi_source("not-reviewed")

        with (
            mock.patch.object(audit, "build_opener") as build,
            self.assertRaisesRegex(audit.SourceError, "compiled target allowlist"),
        ):
            audit._fetch_json(source)

        build.assert_not_called()

    def test_network_error_and_timeout_fail_closed(self) -> None:
        source = audit.REQUIRED_TARGETS[0].source
        opener = FakeOpener(error=URLError("offline"))

        with (
            mock.patch.object(audit, "build_opener", return_value=opener),
            self.assertRaisesRegex(audit.SourceError, "failed closed"),
        ):
            audit._fetch_json(source)

        self.assertEqual(audit.NETWORK_TIMEOUT_SECONDS, opener.timeout)

    def test_oversize_response_fails_closed(self) -> None:
        source = audit.REQUIRED_TARGETS[0].source
        opener = FakeOpener(
            FakeHttpResponse(
                payload=b"x" * (audit.MAX_RESPONSE_BYTES + 1),
                final_url=source.canonical_url,
            )
        )

        with (
            mock.patch.object(audit, "build_opener", return_value=opener),
            self.assertRaisesRegex(audit.SourceError, "response exceeds"),
        ):
            audit._fetch_json(source)

    def test_malformed_json_and_wrong_content_type_fail_closed(self) -> None:
        source = audit.REQUIRED_TARGETS[0].source
        cases = (
            (
                FakeHttpResponse(
                    payload=b"{",
                    final_url=source.canonical_url,
                ),
                "strict JSON",
            ),
            (
                FakeHttpResponse(
                    payload=b"{}",
                    final_url=source.canonical_url,
                    headers={"Content-Type": "text/html"},
                ),
                "application/json",
            ),
        )
        for response, expected in cases:
            with (
                self.subTest(expected=expected),
                mock.patch.object(
                    audit,
                    "build_opener",
                    return_value=FakeOpener(response),
                ),
                self.assertRaisesRegex(audit.SourceError, expected),
            ):
                audit._fetch_json(source)

    def test_redirect_must_end_at_exact_canonical_target(self) -> None:
        source = audit.REQUIRED_TARGETS[0].source
        accepted = FakeHttpResponse(
            payload=b"{}",
            final_url=source.canonical_url,
        )
        with mock.patch.object(
            audit,
            "build_opener",
            return_value=FakeOpener(accepted),
        ):
            response = audit._fetch_json(source)
        self.assertEqual(source.canonical_url, response.final_url)

        rejected = FakeHttpResponse(
            payload=b"{}",
            final_url="https://pypi.org/pypi/other/json",
        )
        with (
            mock.patch.object(
                audit,
                "build_opener",
                return_value=FakeOpener(rejected),
            ),
            self.assertRaisesRegex(audit.SourceError, "non-canonical URL"),
        ):
            audit._fetch_json(source)

    def test_http_status_rejects_boolean_integer_confusion(self) -> None:
        source = audit.REQUIRED_TARGETS[0].source
        response = FakeHttpResponse(
            payload=b"{}",
            final_url=source.canonical_url,
            status=True,
        )

        with (
            mock.patch.object(
                audit,
                "build_opener",
                return_value=FakeOpener(response),
            ),
            self.assertRaisesRegex(audit.SourceError, "expected HTTP 200"),
        ):
            audit._fetch_json(source)


class RepositoryAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        write_base_repository(self.root)

    def test_current_required_targets_and_explicit_inactive_group(self) -> None:
        fetcher = OfflineFetcher()
        before = {
            path.relative_to(self.root): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(self.root.rglob("*"))
            if path.is_file()
        }

        document = audit.audit_repository(self.root, fetch=fetcher)

        after = {
            path.relative_to(self.root): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(self.root.rglob("*"))
            if path.is_file()
        }
        self.assertEqual("current", document["status"])
        self.assertEqual(before, after, "the audit must never update repository pins")
        self.assertEqual(6, document["activeTargetCount"])
        self.assertEqual(3, document["inactiveTargetCount"])
        groups = document["groups"]
        self.assertIsInstance(groups, list)
        self.assertEqual("inactive", groups[0]["status"])
        self.assertIn("Adding either package activates", groups[0]["reason"])
        self.assertFalse(
            any(call.startswith("@") for call in fetcher.calls),
            "inactive npm targets must not become unnecessary network gates",
        )
        inactive = target(document, "assistant-ui-react")
        self.assertEqual("inactive", inactive["status"])
        self.assertEqual(
            "https://registry.npmjs.org/%40assistant-ui%2Freact",
            inactive["source"],
        )

    def test_assistant_ui_activation_requires_and_audits_complete_exact_group(
        self,
    ) -> None:
        activate_assistant_ui(self.root)
        fetcher = OfflineFetcher()

        document = audit.audit_repository(self.root, fetch=fetcher)

        self.assertEqual("current", document["status"])
        self.assertEqual(9, document["activeTargetCount"])
        for target_id, expected in (
            ("assistant-ui-react", "0.14.28"),
            ("assistant-ui-react-langgraph", "0.14.13"),
            ("langgraph-sdk-javascript", "1.9.28"),
        ):
            result = target(document, target_id)
            self.assertEqual("current", result["status"])
            self.assertEqual(expected, result["installed"])
            self.assertEqual(expected, result["latest"])
            self.assertIsInstance(result["releaseUrl"], str)

    def test_one_assistant_ui_package_activates_group_and_missing_pin_fails(
        self,
    ) -> None:
        activate_assistant_ui(self.root, partial=True)

        document = audit.audit_repository(self.root, fetch=OfflineFetcher())

        self.assertEqual("error", document["status"])
        missing = target(document, "assistant-ui-react-langgraph")
        self.assertEqual("error", missing["status"])
        self.assertIn("expected", missing["message"])

    def test_assistant_ui_range_pin_fails_before_upstream_comparison(self) -> None:
        activate_assistant_ui(self.root)
        manifest = self.root / audit.NPM_MANIFEST
        manifest.write_text(
            manifest.read_text(encoding="utf-8").replace(
                '"@assistant-ui/react": "0.14.28"',
                '"@assistant-ui/react": "^0.14.28"',
            ),
            encoding="utf-8",
        )
        fetcher = OfflineFetcher()

        document = audit.audit_repository(self.root, fetch=fetcher)

        result = target(document, "assistant-ui-react")
        self.assertEqual("error", result["status"])
        self.assertIsNone(result["installed"])
        self.assertNotIn("@assistant-ui/react", fetcher.calls)

    def test_missing_and_non_exact_python_pins_fail(self) -> None:
        manifest = self.root / audit.PYTHON_MANIFEST
        original = manifest.read_text(encoding="utf-8")
        mutations = (
            ('    "deepagents==0.6.12",\n', ""),
            ("deepagents==0.6.12", "deepagents>=0.6.12"),
        )
        for old, new in mutations:
            with self.subTest(mutation=new or "missing"):
                manifest.write_text(original.replace(old, new), encoding="utf-8")

                document = audit.audit_repository(
                    self.root,
                    fetch=OfflineFetcher(),
                )

                result = target(document, "deepagents")
                self.assertEqual("error", result["status"])
                self.assertIsNone(result["installed"])
        manifest.write_text(original, encoding="utf-8")

    def test_manifest_and_lock_pin_mismatch_fails(self) -> None:
        lock = self.root / audit.PYTHON_LOCK
        lock.write_text(
            lock.read_text(encoding="utf-8").replace(
                'name = "langgraph"\nversion = "1.2.9"',
                'name = "langgraph"\nversion = "1.2.8"',
            ),
            encoding="utf-8",
        )

        document = audit.audit_repository(self.root, fetch=OfflineFetcher())

        result = target(document, "langgraph")
        self.assertEqual("error", result["status"])
        self.assertIn("project metadata", result["message"])

    def test_protocol_lock_rejects_boolean_lock_version(self) -> None:
        lock_path = self.root / audit.PROTOCOL_LOCK
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        lock["lockVersion"] = True
        lock_path.write_text(json.dumps(lock), encoding="utf-8")

        document = audit.audit_repository(self.root, fetch=OfflineFetcher())

        self.assertEqual("error", document["status"])
        self.assertIn(
            "expected an integer",
            target(document, "agent-protocol")["message"],
        )

    def test_bun_lock_rejects_boolean_lock_version_on_group_activation(
        self,
    ) -> None:
        activate_assistant_ui(self.root)
        lock_path = self.root / audit.NPM_LOCK
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        lock["lockfileVersion"] = True
        lock_path.write_text(json.dumps(lock), encoding="utf-8")

        document = audit.audit_repository(self.root, fetch=OfflineFetcher())

        self.assertEqual("error", document["status"])
        groups = document["groups"]
        self.assertEqual("error", groups[0]["status"])
        self.assertIn("expected an integer", groups[0]["reason"])

    def test_newer_stable_release_is_visible_and_fails_audit(self) -> None:
        document = audit.audit_repository(
            self.root,
            fetch=OfflineFetcher(overrides={"deepagents": "0.6.13"}),
        )

        self.assertEqual("outdated", document["status"])
        self.assertEqual(["deepagents"], document["outdatedTargets"])
        result = target(document, "deepagents")
        self.assertEqual("0.6.12", result["installed"])
        self.assertEqual("0.6.13", result["latest"])
        self.assertEqual(
            "https://pypi.org/pypi/deepagents/json",
            result["source"],
        )

    def test_network_failure_is_an_error_not_a_skipped_target(self) -> None:
        document = audit.audit_repository(
            self.root,
            fetch=OfflineFetcher(failures=frozenset({"langgraph"})),
        )

        self.assertEqual("error", document["status"])
        result = target(document, "langgraph")
        self.assertEqual("error", result["status"])
        self.assertIn("network failure", result["message"])

    def test_machine_output_is_deterministic(self) -> None:
        first = audit.audit_repository(self.root, fetch=OfflineFetcher())
        second = audit.audit_repository(self.root, fetch=OfflineFetcher())

        self.assertEqual(audit.render_json(first), audit.render_json(second))
        parsed = json.loads(audit.render_json(first))
        self.assertEqual(1, parsed["schemaVersion"])

    def test_exit_codes_distinguish_current_outdated_and_error(self) -> None:
        documents = (
            ({"status": "current"}, 0),
            ({"status": "outdated"}, 1),
            ({"status": "error"}, 2),
        )
        for document, expected in documents:
            complete = {
                "activeTargetCount": 0,
                "errors": [],
                "groups": [],
                "inactiveTargetCount": 0,
                "outdatedTargets": [],
                "schemaVersion": 1,
                "targets": [],
                **document,
            }
            with (
                self.subTest(status=document["status"]),
                mock.patch.object(
                    audit,
                    "audit_repository",
                    return_value=complete,
                ),
                mock.patch.object(sys, "stdout"),
            ):
                self.assertEqual(expected, audit.main([]))


if __name__ == "__main__":
    unittest.main()
