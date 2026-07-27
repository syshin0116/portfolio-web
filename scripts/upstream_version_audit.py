#!/usr/bin/env python3
"""Audit exact framework pins against the latest stable official releases."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

REPO_ROOT = Path(__file__).resolve().parents[1]
NETWORK_TIMEOUT_SECONDS = 15
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_LOCAL_FILE_BYTES = 16 * 1024 * 1024
USER_AGENT = "syshin0116.dev-upstream-version-audit/1"

PYTHON_MANIFEST = "agent/pyproject.toml"
PYTHON_LOCK = "uv.lock"
PROTOCOL_LOCK = "protocol/agent-protocol.lock.json"
NPM_MANIFEST = "web/package.json"
NPM_LOCK = "web/bun.lock"

CANONICAL_AGENT_PROTOCOL_REPOSITORY = "langchain-ai/agent-protocol"
CANONICAL_AEGRA_REPOSITORY = "https://github.com/ibbybuilds/aegra"
FULL_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
PYTHON_REQUIREMENT_NAME_PATTERN = re.compile(
    r"^\s*(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)"
)
PYTHON_EXACT_REQUIREMENT_PATTERN = re.compile(
    r"^\s*(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)"
    r"==(?P<version>[A-Za-z0-9.+-]+)\s*$"
)
PEP440_RELEASE_PATTERN = re.compile(
    r"^[vV]?"
    r"(?P<release>(?:0|[1-9]\d*)(?:\.(?:0|[1-9]\d*)){1,3})"
    r"(?:(?P<pre>a|b|rc)(?P<pre_number>\d+))?"
    r"(?:\.post(?P<post>\d+))?"
    r"(?:\.dev(?P<dev>\d+))?"
    r"(?:\+(?P<local>[0-9A-Za-z.-]+))?$"
)
SEMVER_PATTERN = re.compile(
    r"^[vV]?"
    r"(?P<major>0|[1-9]\d*)\."
    r"(?P<minor>0|[1-9]\d*)\."
    r"(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<pre>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+(?P<build>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


class AuditError(RuntimeError):
    """Base class for a fail-closed audit error."""


class PinError(AuditError):
    """A repository pin is missing, non-exact, or internally inconsistent."""


class SourceError(AuditError):
    """An official release source failed its transport or schema contract."""


@dataclass(frozen=True)
class Source:
    """One immutable official release endpoint."""

    ecosystem: Literal["pypi", "npm", "github"]
    package: str
    request_url: str
    canonical_url: str
    repository: str | None = None
    tag_prefix: str = ""


@dataclass(frozen=True)
class Target:
    """One allowlisted repository pin and its official release source."""

    id: str
    display_name: str
    package: str
    pin_kind: Literal["python", "protocol", "npm"]
    source: Source
    pin_sources: tuple[str, ...]
    validate_aegra_protocol_pin: bool = False


@dataclass(frozen=True)
class OptionalTargetGroup:
    """A group that becomes mandatory as soon as one activation package appears."""

    id: str
    display_name: str
    activation_packages: tuple[str, ...]
    targets: tuple[Target, ...]
    inactive_reason: str


@dataclass(frozen=True)
class StableVersion:
    """A final release with a deterministic comparison key."""

    text: str
    key: tuple[int, ...]


@dataclass(frozen=True)
class JsonResponse:
    """A bounded JSON response plus the transport metadata used to validate it."""

    data: Any
    final_url: str
    headers: Mapping[str, str]


@dataclass(frozen=True)
class LatestRelease:
    """The selected stable release and its human-facing URL."""

    version: StableVersion
    release_url: str


def _pypi_source(package: str) -> Source:
    encoded = quote(package, safe="")
    url = f"https://pypi.org/pypi/{encoded}/json"
    return Source("pypi", package, url, url)


def _npm_source(package: str) -> Source:
    encoded = quote(package, safe="")
    url = f"https://registry.npmjs.org/{encoded}"
    return Source("npm", package, url, url)


def _github_releases_source(repository: str, tag_prefix: str) -> Source:
    url = f"https://api.github.com/repos/{repository}/releases?per_page=100"
    return Source(
        "github",
        repository,
        url,
        url,
        repository=repository,
        tag_prefix=tag_prefix,
    )


REQUIRED_TARGETS = (
    Target(
        id="aegra-api",
        display_name="Aegra API",
        package="aegra-api",
        pin_kind="python",
        source=_pypi_source("aegra-api"),
        pin_sources=(PYTHON_MANIFEST, PYTHON_LOCK, PROTOCOL_LOCK),
        validate_aegra_protocol_pin=True,
    ),
    Target(
        id="aegra-cli",
        display_name="Aegra CLI",
        package="aegra-cli",
        pin_kind="python",
        source=_pypi_source("aegra-cli"),
        pin_sources=(PYTHON_MANIFEST, PYTHON_LOCK),
    ),
    Target(
        id="agent-protocol",
        display_name="Agent Protocol",
        package="langchain-protocol",
        pin_kind="protocol",
        source=_github_releases_source(
            CANONICAL_AGENT_PROTOCOL_REPOSITORY,
            "langchain-protocol==",
        ),
        pin_sources=(PROTOCOL_LOCK,),
    ),
    Target(
        id="deepagents",
        display_name="Deep Agents",
        package="deepagents",
        pin_kind="python",
        source=_pypi_source("deepagents"),
        pin_sources=(PYTHON_MANIFEST, PYTHON_LOCK),
    ),
    Target(
        id="langgraph",
        display_name="LangGraph",
        package="langgraph",
        pin_kind="python",
        source=_pypi_source("langgraph"),
        pin_sources=(PYTHON_MANIFEST, PYTHON_LOCK),
    ),
    Target(
        id="langgraph-sdk-python",
        display_name="LangGraph SDK (Python)",
        package="langgraph-sdk",
        pin_kind="python",
        source=_pypi_source("langgraph-sdk"),
        pin_sources=(PYTHON_MANIFEST, PYTHON_LOCK),
    ),
    Target(
        id="langchain-quickjs",
        display_name="LangChain QuickJS",
        package="langchain-quickjs",
        pin_kind="python",
        source=_pypi_source("langchain-quickjs"),
        pin_sources=(PYTHON_MANIFEST, PYTHON_LOCK),
    ),
    Target(
        id="quickjs-rs",
        display_name="QuickJS Rust binding",
        package="quickjs-rs",
        pin_kind="python",
        source=_pypi_source("quickjs-rs"),
        pin_sources=(PYTHON_MANIFEST, PYTHON_LOCK),
    ),
)

ASSISTANT_UI_GROUP = OptionalTargetGroup(
    id="assistant-ui",
    display_name="assistant-ui native client",
    activation_packages=(
        "@assistant-ui/react",
        "@assistant-ui/react-langgraph",
    ),
    targets=(
        Target(
            id="assistant-ui-react",
            display_name="assistant-ui React",
            package="@assistant-ui/react",
            pin_kind="npm",
            source=_npm_source("@assistant-ui/react"),
            pin_sources=(NPM_MANIFEST, NPM_LOCK),
        ),
        Target(
            id="assistant-ui-react-langgraph",
            display_name="assistant-ui LangGraph adapter",
            package="@assistant-ui/react-langgraph",
            pin_kind="npm",
            source=_npm_source("@assistant-ui/react-langgraph"),
            pin_sources=(NPM_MANIFEST, NPM_LOCK),
        ),
        Target(
            id="langgraph-sdk-javascript",
            display_name="LangGraph SDK (JavaScript)",
            package="@langchain/langgraph-sdk",
            pin_kind="npm",
            source=_npm_source("@langchain/langgraph-sdk"),
            pin_sources=(NPM_MANIFEST, NPM_LOCK),
        ),
    ),
    inactive_reason=(
        "Neither @assistant-ui/react nor @assistant-ui/react-langgraph is present "
        "in web/package.json or web/bun.lock. Adding either package activates exact "
        "manifest/lock and upstream checks for both assistant-ui packages and the "
        "JavaScript LangGraph SDK."
    ),
)

OPTIONAL_TARGET_GROUPS = (ASSISTANT_UI_GROUP,)
ALL_TARGETS = REQUIRED_TARGETS + tuple(
    target for group in OPTIONAL_TARGET_GROUPS for target in group.targets
)
TARGET_IDS = tuple(target.id for target in ALL_TARGETS)
if len(TARGET_IDS) != len(set(TARGET_IDS)):
    raise RuntimeError("upstream audit target IDs must be unique")
ALLOWED_SOURCE_URLS = frozenset(target.source.request_url for target in ALL_TARGETS)


def _canonical_python_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _strict_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _repo_file(repo_root: Path, relative: str) -> Path:
    root = repo_root.resolve()
    candidate = root / relative
    if candidate.is_symlink():
        raise PinError(f"{relative}: repository inputs must not be symlinks")
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        raise PinError(f"{relative}: repository input escapes the repository")
    if not resolved.is_file():
        raise PinError(f"{relative}: required repository input is missing")
    try:
        size = resolved.stat().st_size
    except OSError as exc:
        raise PinError(f"{relative}: cannot stat repository input: {exc}") from exc
    if size > MAX_LOCAL_FILE_BYTES:
        raise PinError(
            f"{relative}: repository input exceeds {MAX_LOCAL_FILE_BYTES} bytes"
        )
    return resolved


def _read_repo_text(repo_root: Path, relative: str) -> str:
    path = _repo_file(repo_root, relative)
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise PinError(f"{relative}: cannot read UTF-8 input: {exc}") from exc


def _load_json_text(text: str, *, context: str) -> Any:
    try:
        return json.loads(text, object_pairs_hook=_strict_object_pairs)
    except (
        json.JSONDecodeError,
        UnicodeDecodeError,
        ValueError,
        RecursionError,
    ) as exc:
        raise PinError(f"{context}: invalid strict JSON: {exc}") from exc


def _load_repo_json(repo_root: Path, relative: str) -> Any:
    return _load_json_text(
        _read_repo_text(repo_root, relative),
        context=relative,
    )


def _strip_json_trailing_commas(text: str, *, context: str) -> str:
    output: list[str] = []
    in_string = False
    escaped = False
    for index, character in enumerate(text):
        if in_string:
            output.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
            output.append(character)
            continue
        if character == ",":
            lookahead = index + 1
            while lookahead < len(text) and text[lookahead].isspace():
                lookahead += 1
            if lookahead < len(text) and text[lookahead] in "]}":
                continue
        output.append(character)
    if in_string or escaped:
        raise PinError(f"{context}: unterminated JSON string")
    return "".join(output)


def _load_bun_lock(repo_root: Path) -> dict[str, Any]:
    text = _read_repo_text(repo_root, NPM_LOCK)
    data = _load_json_text(
        _strip_json_trailing_commas(text, context=NPM_LOCK),
        context=NPM_LOCK,
    )
    return _require_object(data, NPM_LOCK, PinError)


def _load_repo_toml(repo_root: Path, relative: str) -> dict[str, Any]:
    text = _read_repo_text(repo_root, relative)
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise PinError(f"{relative}: invalid TOML: {exc}") from exc
    return _require_object(data, relative, PinError)


def _require_object(
    value: Any,
    context: str,
    error_type: type[AuditError],
) -> dict[str, Any]:
    if type(value) is not dict:
        raise error_type(f"{context}: expected an object, got {type(value).__name__}")
    return value


def _require_list(
    value: Any,
    context: str,
    error_type: type[AuditError],
) -> list[Any]:
    if type(value) is not list:
        raise error_type(f"{context}: expected a list, got {type(value).__name__}")
    return value


def _require_string(
    value: Any,
    context: str,
    error_type: type[AuditError],
) -> str:
    if type(value) is not str or not value:
        raise error_type(f"{context}: expected a non-empty string, got {value!r}")
    return value


def _require_integer(
    value: Any,
    context: str,
    error_type: type[AuditError],
) -> int:
    if type(value) is not int:
        raise error_type(f"{context}: expected an integer, got {value!r}")
    return value


def _parse_stable_version(
    value: str,
    ecosystem: Literal["pypi", "npm", "github"],
    *,
    context: str,
    error_type: type[AuditError],
) -> StableVersion | None:
    if ecosystem in {"pypi", "github"}:
        match = PEP440_RELEASE_PATTERN.fullmatch(value)
        if match is None:
            raise error_type(f"{context}: malformed PEP 440 release {value!r}")
        if match.group("pre") is not None or match.group("dev") is not None:
            return None
        release = tuple(int(part) for part in match.group("release").split("."))
        padded = release + (0,) * (4 - len(release))
        post = match.group("post")
        post_key = (0, -1) if post is None else (1, int(post))
        return StableVersion(
            value.removeprefix("v").removeprefix("V"), padded + post_key
        )

    match = SEMVER_PATTERN.fullmatch(value)
    if match is None:
        raise error_type(f"{context}: malformed semantic release {value!r}")
    if match.group("pre") is not None:
        return None
    release_key = (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
    )
    return StableVersion(value.removeprefix("v").removeprefix("V"), release_key)


def _require_stable_pin(
    value: str,
    ecosystem: Literal["pypi", "npm", "github"],
    *,
    context: str,
) -> StableVersion:
    parsed = _parse_stable_version(
        value,
        ecosystem,
        context=context,
        error_type=PinError,
    )
    if parsed is None:
        raise PinError(f"{context}: exact pins must use a stable final release")
    return parsed


def _highest_stable(
    candidates: list[StableVersion],
    *,
    context: str,
) -> StableVersion:
    if not candidates:
        raise SourceError(f"{context}: no non-yanked stable release exists")
    highest_key = max(candidate.key for candidate in candidates)
    winners = {
        candidate.text for candidate in candidates if candidate.key == highest_key
    }
    if len(winners) != 1:
        raise SourceError(
            f"{context}: ambiguous stable versions share one ordering key: "
            f"{sorted(winners)!r}"
        )
    winner = next(iter(winners))
    return next(candidate for candidate in candidates if candidate.text == winner)


def _extract_python_manifest_pin(repo_root: Path, package: str) -> StableVersion:
    manifest = _load_repo_toml(repo_root, PYTHON_MANIFEST)
    project = _require_object(
        manifest.get("project"), f"{PYTHON_MANIFEST} project", PinError
    )
    dependencies = _require_list(
        project.get("dependencies"),
        f"{PYTHON_MANIFEST} project.dependencies",
        PinError,
    )
    matches: list[str] = []
    for index, dependency in enumerate(dependencies):
        if type(dependency) is not str:
            raise PinError(
                f"{PYTHON_MANIFEST} project.dependencies[{index}] must be a string"
            )
        name_match = PYTHON_REQUIREMENT_NAME_PATTERN.match(dependency)
        if name_match is not None and _canonical_python_name(
            name_match.group("name")
        ) == _canonical_python_name(package):
            matches.append(dependency)
    if len(matches) != 1:
        raise PinError(
            f"{PYTHON_MANIFEST}: expected exactly one dependency for {package!r}, "
            f"found {len(matches)}"
        )
    exact = PYTHON_EXACT_REQUIREMENT_PATTERN.fullmatch(matches[0])
    if exact is None:
        raise PinError(
            f"{PYTHON_MANIFEST}: {package!r} must use one exact '==<version>' pin, "
            f"got {matches[0]!r}"
        )
    return _require_stable_pin(
        exact.group("version"),
        "pypi",
        context=f"{PYTHON_MANIFEST} {package}",
    )


def _extract_uv_lock_pin(repo_root: Path, package: str) -> StableVersion:
    lock = _load_repo_toml(repo_root, PYTHON_LOCK)
    packages = _require_list(lock.get("package"), f"{PYTHON_LOCK} package", PinError)
    canonical = _canonical_python_name(package)
    matches: list[dict[str, Any]] = []
    project_entries: list[dict[str, Any]] = []
    for index, value in enumerate(packages):
        entry = _require_object(value, f"{PYTHON_LOCK} package[{index}]", PinError)
        name = _require_string(
            entry.get("name"),
            f"{PYTHON_LOCK} package[{index}].name",
            PinError,
        )
        if _canonical_python_name(name) == canonical:
            matches.append(entry)
        if name == "syshin0116-dev-agent":
            project_entries.append(entry)
    if len(matches) != 1:
        raise PinError(
            f"{PYTHON_LOCK}: expected exactly one resolved package for {package!r}, "
            f"found {len(matches)}"
        )
    entry = matches[0]
    source = _require_object(
        entry.get("source"),
        f"{PYTHON_LOCK} {package}.source",
        PinError,
    )
    if source != {"registry": "https://pypi.org/simple"}:
        raise PinError(
            f"{PYTHON_LOCK}: {package!r} must resolve only from official PyPI, "
            f"got {source!r}"
        )
    resolved = _require_stable_pin(
        _require_string(
            entry.get("version"),
            f"{PYTHON_LOCK} {package}.version",
            PinError,
        ),
        "pypi",
        context=f"{PYTHON_LOCK} {package}",
    )

    if len(project_entries) != 1:
        raise PinError(
            f"{PYTHON_LOCK}: expected one syshin0116-dev-agent project entry, "
            f"found {len(project_entries)}"
        )
    metadata = _require_object(
        project_entries[0].get("metadata"),
        f"{PYTHON_LOCK} syshin0116-dev-agent.metadata",
        PinError,
    )
    requirements = _require_list(
        metadata.get("requires-dist"),
        f"{PYTHON_LOCK} syshin0116-dev-agent.metadata.requires-dist",
        PinError,
    )
    requirement_matches: list[dict[str, Any]] = []
    for index, value in enumerate(requirements):
        requirement = _require_object(
            value,
            f"{PYTHON_LOCK} requires-dist[{index}]",
            PinError,
        )
        name = _require_string(
            requirement.get("name"),
            f"{PYTHON_LOCK} requires-dist[{index}].name",
            PinError,
        )
        if _canonical_python_name(name) == canonical:
            requirement_matches.append(requirement)
    if len(requirement_matches) != 1:
        raise PinError(
            f"{PYTHON_LOCK}: expected one project requirement for {package!r}, "
            f"found {len(requirement_matches)}"
        )
    specifier = requirement_matches[0].get("specifier")
    if specifier != f"=={resolved.text}":
        raise PinError(
            f"{PYTHON_LOCK}: {package!r} project metadata must pin "
            f"'=={resolved.text}', got {specifier!r}"
        )
    return resolved


def _load_protocol_lock(repo_root: Path) -> dict[str, Any]:
    lock = _require_object(
        _load_repo_json(repo_root, PROTOCOL_LOCK),
        PROTOCOL_LOCK,
        PinError,
    )
    lock_version = _require_integer(
        lock.get("lockVersion"),
        f"{PROTOCOL_LOCK} lockVersion",
        PinError,
    )
    if lock_version != 1:
        raise PinError(
            f"{PROTOCOL_LOCK}: lockVersion must equal integer 1, got {lock_version!r}"
        )
    return lock


def _validate_aegra_protocol_pin(
    repo_root: Path,
    expected: StableVersion,
) -> None:
    lock = _load_protocol_lock(repo_root)
    aegra = _require_object(lock.get("aegra"), f"{PROTOCOL_LOCK} aegra", PinError)
    repository = _require_string(
        aegra.get("repository"),
        f"{PROTOCOL_LOCK} aegra.repository",
        PinError,
    )
    if repository != CANONICAL_AEGRA_REPOSITORY:
        raise PinError(
            f"{PROTOCOL_LOCK}: Aegra repository must remain "
            f"{CANONICAL_AEGRA_REPOSITORY!r}, got {repository!r}"
        )
    tag = _require_string(
        aegra.get("tag"),
        f"{PROTOCOL_LOCK} aegra.tag",
        PinError,
    )
    if tag != f"v{expected.text}":
        raise PinError(
            f"{PROTOCOL_LOCK}: Aegra tag must match the manifest/lock pin "
            f"'v{expected.text}', got {tag!r}"
        )


def _extract_protocol_pin(repo_root: Path) -> StableVersion:
    lock = _load_protocol_lock(repo_root)
    protocol = _require_object(
        lock.get("protocol"),
        f"{PROTOCOL_LOCK} protocol",
        PinError,
    )
    repository = _require_string(
        protocol.get("repository"),
        f"{PROTOCOL_LOCK} protocol.repository",
        PinError,
    )
    expected_repository = f"https://github.com/{CANONICAL_AGENT_PROTOCOL_REPOSITORY}"
    if repository != expected_repository:
        raise PinError(
            f"{PROTOCOL_LOCK}: Agent Protocol repository must remain "
            f"{expected_repository!r}, got {repository!r}"
        )
    commit = _require_string(
        protocol.get("commit"),
        f"{PROTOCOL_LOCK} protocol.commit",
        PinError,
    )
    if FULL_SHA_PATTERN.fullmatch(commit) is None:
        raise PinError(
            f"{PROTOCOL_LOCK}: Agent Protocol commit must be a full lowercase SHA"
        )
    release = _require_stable_pin(
        _require_string(
            protocol.get("releaseVersion"),
            f"{PROTOCOL_LOCK} protocol.releaseVersion",
            PinError,
        ),
        "github",
        context=f"{PROTOCOL_LOCK} Agent Protocol",
    )
    expected_tag = f"langchain-protocol=={release.text}"
    if protocol.get("tag") != expected_tag:
        raise PinError(
            f"{PROTOCOL_LOCK}: protocol.tag must equal {expected_tag!r}, "
            f"got {protocol.get('tag')!r}"
        )
    artifacts = _require_object(
        protocol.get("artifacts"),
        f"{PROTOCOL_LOCK} protocol.artifacts",
        PinError,
    )
    python_binding = _require_object(
        artifacts.get("pythonBinding"),
        f"{PROTOCOL_LOCK} protocol.artifacts.pythonBinding",
        PinError,
    )
    typescript_binding = _require_object(
        artifacts.get("typescriptBinding"),
        f"{PROTOCOL_LOCK} protocol.artifacts.typescriptBinding",
        PinError,
    )
    if python_binding.get("package") != expected_tag:
        raise PinError(
            f"{PROTOCOL_LOCK}: Python binding package must equal "
            f"{expected_tag!r}, got {python_binding.get('package')!r}"
        )
    expected_typescript = f"@langchain/protocol@{release.text}"
    if typescript_binding.get("package") != expected_typescript:
        raise PinError(
            f"{PROTOCOL_LOCK}: TypeScript binding package must equal "
            f"{expected_typescript!r}, got {typescript_binding.get('package')!r}"
        )
    return release


def _npm_documents(
    repo_root: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = _require_object(
        _load_repo_json(repo_root, NPM_MANIFEST),
        NPM_MANIFEST,
        PinError,
    )
    lock = _load_bun_lock(repo_root)
    lock_version = _require_integer(
        lock.get("lockfileVersion"),
        f"{NPM_LOCK} lockfileVersion",
        PinError,
    )
    if lock_version != 1:
        raise PinError(
            f"{NPM_LOCK}: lockfileVersion must equal integer 1, got {lock_version!r}"
        )
    return manifest, lock


def _dependency_mappings(
    document: dict[str, Any],
    *,
    context: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    mappings: list[dict[str, Any]] = []
    for key in ("dependencies", "devDependencies"):
        value = document.get(key, {})
        mappings.append(_require_object(value, f"{context} {key}", PinError))
    return mappings[0], mappings[1]


def _optional_group_active(
    repo_root: Path,
    group: OptionalTargetGroup,
) -> bool:
    manifest, lock = _npm_documents(repo_root)
    manifest_dependencies = _dependency_mappings(
        manifest,
        context=NPM_MANIFEST,
    )
    workspaces = _require_object(
        lock.get("workspaces"),
        f"{NPM_LOCK} workspaces",
        PinError,
    )
    root_workspace = _require_object(
        workspaces.get(""),
        f"{NPM_LOCK} workspaces['']",
        PinError,
    )
    lock_dependencies = _dependency_mappings(
        root_workspace,
        context=f"{NPM_LOCK} root workspace",
    )
    packages = _require_object(
        lock.get("packages"),
        f"{NPM_LOCK} packages",
        PinError,
    )
    for package in group.activation_packages:
        if any(
            package in mapping
            for mapping in (*manifest_dependencies, *lock_dependencies)
        ):
            return True
        if package in packages:
            return True
    return False


def _extract_npm_pin(repo_root: Path, package: str) -> StableVersion:
    manifest, lock = _npm_documents(repo_root)
    manifest_dependencies = _dependency_mappings(
        manifest,
        context=NPM_MANIFEST,
    )
    manifest_values = [
        mapping[package] for mapping in manifest_dependencies if package in mapping
    ]
    if len(manifest_values) != 1:
        raise PinError(
            f"{NPM_MANIFEST}: expected {package!r} in exactly one direct dependency "
            f"mapping, found {len(manifest_values)}"
        )
    manifest_pin = _require_stable_pin(
        _require_string(
            manifest_values[0],
            f"{NPM_MANIFEST} {package}",
            PinError,
        ),
        "npm",
        context=f"{NPM_MANIFEST} {package}",
    )
    if manifest_values[0] != manifest_pin.text:
        raise PinError(
            f"{NPM_MANIFEST}: {package!r} must be an exact version without "
            f"a range or prefix, got {manifest_values[0]!r}"
        )

    workspaces = _require_object(
        lock.get("workspaces"),
        f"{NPM_LOCK} workspaces",
        PinError,
    )
    root_workspace = _require_object(
        workspaces.get(""),
        f"{NPM_LOCK} workspaces['']",
        PinError,
    )
    lock_dependencies = _dependency_mappings(
        root_workspace,
        context=f"{NPM_LOCK} root workspace",
    )
    lock_values = [
        mapping[package] for mapping in lock_dependencies if package in mapping
    ]
    if lock_values != [manifest_pin.text]:
        raise PinError(
            f"{NPM_LOCK}: root workspace must repeat exact {package!r} pin "
            f"{manifest_pin.text!r}, got {lock_values!r}"
        )
    packages = _require_object(
        lock.get("packages"),
        f"{NPM_LOCK} packages",
        PinError,
    )
    entry = _require_list(
        packages.get(package),
        f"{NPM_LOCK} packages[{package!r}]",
        PinError,
    )
    if not entry or entry[0] != f"{package}@{manifest_pin.text}":
        raise PinError(
            f"{NPM_LOCK}: {package!r} resolution must start with "
            f"{package}@{manifest_pin.text!s}, got {entry[:1]!r}"
        )
    return manifest_pin


def _extract_target_pin(repo_root: Path, target: Target) -> StableVersion:
    if target.pin_kind == "python":
        manifest_pin = _extract_python_manifest_pin(repo_root, target.package)
        lock_pin = _extract_uv_lock_pin(repo_root, target.package)
        if manifest_pin.text != lock_pin.text:
            raise PinError(
                f"{target.display_name}: manifest pin {manifest_pin.text!r} and "
                f"lock pin {lock_pin.text!r} differ"
            )
        if target.validate_aegra_protocol_pin:
            _validate_aegra_protocol_pin(repo_root, manifest_pin)
        return manifest_pin
    if target.pin_kind == "protocol":
        return _extract_protocol_pin(repo_root)
    return _extract_npm_pin(repo_root, target.package)


def _assert_source_contract(source: Source) -> None:
    if source.ecosystem == "pypi":
        expected = f"https://pypi.org/pypi/{quote(source.package, safe='')}/json"
    elif source.ecosystem == "npm":
        expected = f"https://registry.npmjs.org/{quote(source.package, safe='')}"
    else:
        if source.repository is None or source.package != source.repository:
            raise SourceError("GitHub source must bind one canonical repository")
        expected = (
            f"https://api.github.com/repos/{source.repository}/releases?per_page=100"
        )
    if source.request_url != expected or source.canonical_url != expected:
        raise SourceError(
            f"source target is outside its reviewed canonical endpoint: "
            f"request={source.request_url!r}, canonical={source.canonical_url!r}, "
            f"expected={expected!r}"
        )
    parsed = urlsplit(expected)
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.hostname not in {"pypi.org", "registry.npmjs.org", "api.github.com"}
    ):
        raise SourceError(f"invalid reviewed source endpoint: {expected!r}")


class _StrictRedirectHandler(HTTPRedirectHandler):
    """Permit a redirect only when it terminates at the reviewed canonical URL."""

    def __init__(self, canonical_url: str) -> None:
        super().__init__()
        self._canonical_url = canonical_url

    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> Request | None:
        if newurl != self._canonical_url:
            raise HTTPError(
                newurl,
                code,
                "redirect target is not the reviewed canonical endpoint",
                headers,
                fp,
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _fetch_json(source: Source) -> JsonResponse:
    _assert_source_contract(source)
    if source.request_url not in ALLOWED_SOURCE_URLS:
        raise SourceError(
            f"source URL is not in the compiled target allowlist: "
            f"{source.request_url!r}"
        )
    headers = {
        "Accept": (
            "application/vnd.github+json"
            if source.ecosystem == "github"
            else "application/json"
        ),
        "User-Agent": USER_AGENT,
    }
    if source.ecosystem == "github":
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    request = Request(source.request_url, headers=headers)
    opener = build_opener(_StrictRedirectHandler(source.canonical_url))
    try:
        with opener.open(  # noqa: S310
            request,
            timeout=NETWORK_TIMEOUT_SECONDS,
        ) as response:
            status = getattr(response, "status", None)
            if type(status) is not int or status != 200:
                raise SourceError(
                    f"{source.package}: expected HTTP 200, got {status!r}"
                )
            final_url = response.geturl()
            if final_url != source.canonical_url:
                raise SourceError(
                    f"{source.package}: response ended at non-canonical URL "
                    f"{final_url!r}"
                )
            response_headers = {
                str(key).lower(): str(value) for key, value in response.headers.items()
            }
            content_type = response_headers.get("content-type", "")
            if content_type.partition(";")[0].strip().lower() != "application/json":
                raise SourceError(
                    f"{source.package}: expected application/json, got {content_type!r}"
                )
            content_length = response_headers.get("content-length")
            if content_length is not None:
                if not content_length.isascii() or not content_length.isdecimal():
                    raise SourceError(
                        f"{source.package}: invalid Content-Length {content_length!r}"
                    )
                if int(content_length) > MAX_RESPONSE_BYTES:
                    raise SourceError(
                        f"{source.package}: response exceeds {MAX_RESPONSE_BYTES} bytes"
                    )
            payload = response.read(MAX_RESPONSE_BYTES + 1)
    except SourceError:
        raise
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise SourceError(
            f"{source.package}: official release request failed closed: {exc}"
        ) from exc
    if len(payload) > MAX_RESPONSE_BYTES:
        raise SourceError(
            f"{source.package}: response exceeds {MAX_RESPONSE_BYTES} bytes"
        )
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SourceError(f"{source.package}: response is not valid UTF-8") from exc
    try:
        data = json.loads(text, object_pairs_hook=_strict_object_pairs)
    except (json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise SourceError(
            f"{source.package}: response is not strict JSON: {exc}"
        ) from exc
    return JsonResponse(data=data, final_url=final_url, headers=response_headers)


def _latest_pypi(source: Source, response: JsonResponse) -> LatestRelease:
    payload = _require_object(response.data, source.package, SourceError)
    info = _require_object(
        payload.get("info"),
        f"{source.package} info",
        SourceError,
    )
    reported_name = _require_string(
        info.get("name"),
        f"{source.package} info.name",
        SourceError,
    )
    if _canonical_python_name(reported_name) != _canonical_python_name(source.package):
        raise SourceError(
            f"{source.package}: PyPI response reports a different package "
            f"{reported_name!r}"
        )
    reported_latest = _require_string(
        info.get("version"),
        f"{source.package} info.version",
        SourceError,
    )
    releases = _require_object(
        payload.get("releases"),
        f"{source.package} releases",
        SourceError,
    )
    candidates: list[StableVersion] = []
    for version_text, raw_files in releases.items():
        if type(version_text) is not str:
            raise SourceError(f"{source.package}: release keys must be strings")
        version = _parse_stable_version(
            version_text,
            "pypi",
            context=f"{source.package} release",
            error_type=SourceError,
        )
        files = _require_list(
            raw_files,
            f"{source.package} release {version_text}",
            SourceError,
        )
        has_non_yanked_file = False
        for index, raw_file in enumerate(files):
            file_record = _require_object(
                raw_file,
                f"{source.package} release {version_text} file[{index}]",
                SourceError,
            )
            yanked = file_record.get("yanked")
            if type(yanked) is not bool:
                raise SourceError(
                    f"{source.package} release {version_text} file[{index}]."
                    f"yanked must be a boolean, got {yanked!r}"
                )
            if not yanked:
                has_non_yanked_file = True
        if version is not None and has_non_yanked_file:
            candidates.append(version)
    latest = _highest_stable(candidates, context=source.package)
    reported = _parse_stable_version(
        reported_latest,
        "pypi",
        context=f"{source.package} info.version",
        error_type=SourceError,
    )
    if reported is None or reported.text != latest.text:
        raise SourceError(
            f"{source.package}: PyPI info.version {reported_latest!r} does not "
            f"identify the highest non-yanked stable release {latest.text!r}"
        )
    return LatestRelease(
        latest,
        f"https://pypi.org/project/{quote(source.package, safe='')}/{latest.text}/",
    )


def _latest_npm(source: Source, response: JsonResponse) -> LatestRelease:
    payload = _require_object(response.data, source.package, SourceError)
    reported_name = _require_string(
        payload.get("name"),
        f"{source.package} name",
        SourceError,
    )
    if reported_name != source.package:
        raise SourceError(
            f"{source.package}: npm response reports a different package "
            f"{reported_name!r}"
        )
    dist_tags = _require_object(
        payload.get("dist-tags"),
        f"{source.package} dist-tags",
        SourceError,
    )
    reported_latest = _require_string(
        dist_tags.get("latest"),
        f"{source.package} dist-tags.latest",
        SourceError,
    )
    versions = _require_object(
        payload.get("versions"),
        f"{source.package} versions",
        SourceError,
    )
    candidates: list[StableVersion] = []
    for version_text, raw_record in versions.items():
        if type(version_text) is not str:
            raise SourceError(f"{source.package}: version keys must be strings")
        version = _parse_stable_version(
            version_text,
            "npm",
            context=f"{source.package} version",
            error_type=SourceError,
        )
        record = _require_object(
            raw_record,
            f"{source.package} version {version_text}",
            SourceError,
        )
        if (
            record.get("name") != source.package
            or record.get("version") != version_text
        ):
            raise SourceError(
                f"{source.package}: npm version record {version_text!r} has "
                "inconsistent name/version fields"
            )
        deprecated = record.get("deprecated")
        if deprecated is not None and type(deprecated) is not str:
            raise SourceError(
                f"{source.package}: npm version record {version_text!r} "
                f"deprecated must be a string when present, got {deprecated!r}"
            )
        if version is not None and deprecated is None:
            candidates.append(version)
    latest = _highest_stable(candidates, context=source.package)
    reported = _parse_stable_version(
        reported_latest,
        "npm",
        context=f"{source.package} dist-tags.latest",
        error_type=SourceError,
    )
    if reported is None or reported.text != latest.text:
        raise SourceError(
            f"{source.package}: npm latest tag {reported_latest!r} does not "
            "identify the highest non-deprecated stable release "
            f"{latest.text!r}"
        )
    encoded = quote(source.package, safe="")
    return LatestRelease(
        latest,
        f"https://www.npmjs.com/package/{encoded}/v/{latest.text}",
    )


def _latest_github(source: Source, response: JsonResponse) -> LatestRelease:
    if source.repository is None:
        raise SourceError("GitHub source is missing its canonical repository")
    link = response.headers.get("link", "")
    if 'rel="next"' in link:
        raise SourceError(
            f"{source.repository}: more than 100 releases require a reviewed "
            "pagination extension"
        )
    releases = _require_list(
        response.data,
        f"{source.repository} releases",
        SourceError,
    )
    candidates: list[tuple[StableVersion, str]] = []
    api_prefix = f"https://api.github.com/repos/{source.repository}/releases/"
    html_prefix = f"https://github.com/{source.repository}/releases/tag/"
    for index, raw_release in enumerate(releases):
        release = _require_object(
            raw_release,
            f"{source.repository} release[{index}]",
            SourceError,
        )
        release_id = release.get("id")
        if type(release_id) is not int or release_id <= 0:
            raise SourceError(
                f"{source.repository} release[{index}].id must be a positive integer"
            )
        for field in ("draft", "prerelease"):
            if type(release.get(field)) is not bool:
                raise SourceError(
                    f"{source.repository} release[{index}].{field} must be a boolean"
                )
        tag = _require_string(
            release.get("tag_name"),
            f"{source.repository} release[{index}].tag_name",
            SourceError,
        )
        api_url = _require_string(
            release.get("url"),
            f"{source.repository} release[{index}].url",
            SourceError,
        )
        html_url = _require_string(
            release.get("html_url"),
            f"{source.repository} release[{index}].html_url",
            SourceError,
        )
        if not api_url.startswith(api_prefix) or not html_url.startswith(html_prefix):
            raise SourceError(
                f"{source.repository} release[{index}] is not bound to the "
                "canonical repository"
            )
        if (
            release["draft"]
            or release["prerelease"]
            or not tag.startswith(source.tag_prefix)
        ):
            continue
        raw_version = tag.removeprefix(source.tag_prefix)
        version = _parse_stable_version(
            raw_version,
            "github",
            context=f"{source.repository} release tag",
            error_type=SourceError,
        )
        if version is not None:
            candidates.append((version, html_url))
    latest = _highest_stable(
        [candidate[0] for candidate in candidates],
        context=source.repository,
    )
    release_urls = {
        release_url
        for version, release_url in candidates
        if version.text == latest.text
    }
    if len(release_urls) != 1:
        raise SourceError(
            f"{source.repository}: stable release {latest.text!r} has ambiguous URLs"
        )
    return LatestRelease(latest, next(iter(release_urls)))


def _latest_release(source: Source, response: JsonResponse) -> LatestRelease:
    if response.final_url != source.canonical_url:
        raise SourceError(
            f"{source.package}: fixture/transport final URL is not canonical: "
            f"{response.final_url!r}"
        )
    if source.ecosystem == "pypi":
        return _latest_pypi(source, response)
    if source.ecosystem == "npm":
        return _latest_npm(source, response)
    return _latest_github(source, response)


def _target_result(
    target: Target,
    *,
    active: bool,
    status: str,
    message: str,
    installed: str | None = None,
    latest: str | None = None,
    release_url: str | None = None,
) -> dict[str, Any]:
    return {
        "active": active,
        "displayName": target.display_name,
        "ecosystem": target.source.ecosystem,
        "id": target.id,
        "installed": installed,
        "latest": latest,
        "message": message,
        "package": target.package,
        "pinSources": list(target.pin_sources),
        "releaseUrl": release_url,
        "source": target.source.canonical_url,
        "status": status,
    }


def _audit_target(
    repo_root: Path,
    target: Target,
    fetch: Callable[[Source], JsonResponse],
) -> dict[str, Any]:
    try:
        installed = _extract_target_pin(repo_root, target)
        response = fetch(target.source)
        latest = _latest_release(target.source, response)
    except AuditError as exc:
        return _target_result(
            target,
            active=True,
            status="error",
            message=str(exc),
        )

    if installed.text == latest.version.text:
        return _target_result(
            target,
            active=True,
            status="current",
            message="The exact repository pin matches the latest stable release.",
            installed=installed.text,
            latest=latest.version.text,
            release_url=latest.release_url,
        )
    if installed.key < latest.version.key:
        return _target_result(
            target,
            active=True,
            status="outdated",
            message=(
                "A newer stable release exists. Review compatibility and update "
                "the manifest and lock in a focused PR; this audit never writes them."
            ),
            installed=installed.text,
            latest=latest.version.text,
            release_url=latest.release_url,
        )
    relation = (
        "uses a different spelling for the same semantic version"
        if installed.key == latest.version.key
        else "is newer than the highest official stable release"
    )
    return _target_result(
        target,
        active=True,
        status="error",
        message=(
            f"The repository pin {installed.text!r} {relation}; "
            "manual upstream verification is required."
        ),
        installed=installed.text,
        latest=latest.version.text,
        release_url=latest.release_url,
    )


def audit_repository(
    repo_root: Path = REPO_ROOT,
    *,
    fetch: Callable[[Source], JsonResponse] = _fetch_json,
) -> dict[str, Any]:
    """Return the complete deterministic audit document without changing pins."""
    results = [_audit_target(repo_root, target, fetch) for target in REQUIRED_TARGETS]
    groups: list[dict[str, Any]] = []
    for group in OPTIONAL_TARGET_GROUPS:
        try:
            active = _optional_group_active(repo_root, group)
        except AuditError as exc:
            active = True
            reason = f"Cannot determine activation safely: {exc}"
            group_status = "error"
        else:
            reason = (
                "At least one activation package is present; every target in the "
                "group is now mandatory."
                if active
                else group.inactive_reason
            )
            group_status = "active" if active else "inactive"
        groups.append(
            {
                "activationPackages": list(group.activation_packages),
                "displayName": group.display_name,
                "id": group.id,
                "reason": reason,
                "status": group_status,
                "targetIds": [target.id for target in group.targets],
            }
        )
        if active:
            if group_status == "error":
                for target in group.targets:
                    results.append(
                        _target_result(
                            target,
                            active=True,
                            status="error",
                            message=reason,
                        )
                    )
            else:
                results.extend(
                    _audit_target(repo_root, target, fetch) for target in group.targets
                )
        else:
            for target in group.targets:
                results.append(
                    _target_result(
                        target,
                        active=False,
                        status="inactive",
                        message=group.inactive_reason,
                    )
                )

    results.sort(key=lambda result: result["id"])
    groups.sort(key=lambda group: group["id"])
    errors = sorted(
        f"{result['id']}: {result['message']}"
        for result in results
        if result["status"] == "error"
    )
    outdated = sorted(
        result["id"] for result in results if result["status"] == "outdated"
    )
    if errors:
        status = "error"
    elif outdated:
        status = "outdated"
    else:
        status = "current"
    return {
        "activeTargetCount": sum(result["active"] for result in results),
        "errors": errors,
        "groups": groups,
        "inactiveTargetCount": sum(not result["active"] for result in results),
        "outdatedTargets": outdated,
        "schemaVersion": 1,
        "status": status,
        "targets": results,
    }


def render_json(document: dict[str, Any]) -> str:
    """Render one canonical, newline-terminated machine-readable report."""
    return (
        json.dumps(
            document,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def render_summary(document: dict[str, Any]) -> str:
    """Render a bounded GitHub step summary from already validated fields."""
    lines = [
        "# Upstream version audit",
        "",
        f"Overall status: **{document['status']}**",
        "",
        "| Target | State | Exact pin | Latest stable |",
        "| --- | --- | --- | --- |",
    ]
    for target in document["targets"]:
        installed = target["installed"] or "—"
        latest = target["latest"] or "—"
        lines.append(
            f"| `{target['id']}` | {target['status']} | `{installed}` | `{latest}` |"
        )
    lines.extend(
        [
            "",
            "This audit is read-only. An outdated result requires a focused, "
            "reviewed manifest/lock update.",
            "",
        ]
    )
    return "\n".join(lines)


def _write_report(path: Path, content: str, *, label: str) -> None:
    try:
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise AuditError(f"cannot write {label} {path}: {exc}") from exc


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        help="also write the canonical JSON report to this path",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        help="write a Markdown summary, normally $GITHUB_STEP_SUMMARY",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    document = audit_repository()
    rendered = render_json(document)
    sys.stdout.write(rendered)
    try:
        if args.output is not None:
            _write_report(args.output, rendered, label="JSON report")
        if args.summary is not None:
            _write_report(
                args.summary,
                render_summary(document),
                label="Markdown summary",
            )
    except AuditError as exc:
        print(f"upstream version audit output error: {exc}", file=sys.stderr)
        return 2
    if document["status"] == "current":
        return 0
    if document["status"] == "outdated":
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
