"""Fail-closed verification of GitHub-attested evaluation candidates."""

from __future__ import annotations

import json
import re
import subprocess
import tarfile
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from agent.retrieval.protocol import Corpus
from agent.retrieval.registry import RetrieverRegistry

from blogeval.datasets import QuerySet
from blogeval.jsonio import StrictJsonError, load_canonical_json
from blogeval.provenance import (
    ProvenanceError,
    RunProvenance,
    collect_run_provenance,
    parse_run_provenance,
)
from blogeval.registry import registry as default_registry
from blogeval.runner import EvaluationError, verify_run_directory

PUBLICATION_REPOSITORY = "syshin0116/syshin0116.dev"
PUBLICATION_SIGNER_WORKFLOW = (
    "syshin0116/syshin0116.dev/.github/workflows/eval-publication.yml"
)
PUBLICATION_WORKFLOW_IDENTITY = (
    f"{PUBLICATION_REPOSITORY}/.github/workflows/eval-publication.yml@refs/heads/main"
)
PUBLICATION_CANDIDATE_SCHEMA = "blogeval-publication-candidate-v2"
PUBLICATION_CANDIDATE_STATUS = "candidate-awaiting-external-verification"
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_RUN_ID_RE = _SHA256_RE
_MAX_ARCHIVE_FILE_BYTES = 64 * 1024 * 1024
_CANDIDATE_KEYS = frozenset(
    {
        "commit_sha",
        "content_git_tree_sha",
        "dataset_checksum",
        "dataset_id",
        "dataset_label_status",
        "execution_image_digest",
        "publication_status",
        "result_digest",
        "run_id",
        "schema",
        "workflow_identity",
        "workflow_run_id",
    }
)
_RESULT_FILES = frozenset(
    {
        "result/leaderboard.md",
        "result/manifest.json",
        "result/metrics.svg",
        "result/per-query.md",
        "result/run.json",
    }
)


class PublicationError(ValueError):
    """A candidate cannot cross the external publication boundary."""


@dataclass(frozen=True, slots=True)
class VerifiedPublicationCandidate:
    commit_sha: str
    execution_image_digest: str
    result_digest: str
    run_id: str
    workflow_run_id: str


def _git_output(workspace_root: Path, *arguments: str) -> str:
    command = ("git", "-C", str(workspace_root), *arguments)
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise PublicationError(f"cannot inspect publication checkout: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip()
        suffix = f": {detail}" if detail else ""
        raise PublicationError(f"cannot inspect publication checkout{suffix}")
    return completed.stdout


def _verify_checkout_identity(
    workspace_root: Path,
    *,
    expected_commit: str,
    recorded: RunProvenance,
) -> None:
    root = workspace_root.resolve()
    if not root.is_dir():
        raise PublicationError("publication workspace root must be a directory")
    head = _git_output(root, "rev-parse", "--verify", "HEAD").strip()
    if head != expected_commit:
        raise PublicationError(
            "publication verifier checkout does not match the expected commit"
        )
    status = _git_output(
        root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--",
        "agent/src/agent",
        "eval/src/blogeval",
        "uv.lock",
    )
    if status:
        raise PublicationError(
            "publication verifier source trees and uv.lock must be clean"
        )
    try:
        local = collect_run_provenance(workspace_root=root)
    except ProvenanceError as exc:
        raise PublicationError(str(exc)) from exc
    for field in ("agent_source_tree", "eval_source_tree", "workspace_lock"):
        if getattr(local, field) != getattr(recorded, field):
            raise PublicationError(
                f"publication verifier {field} differs from the attested run"
            )


def _require_attestation(archive: Path, *, expected_commit: str) -> None:
    command = (
        "gh",
        "attestation",
        "verify",
        str(archive),
        "--repo",
        PUBLICATION_REPOSITORY,
        "--signer-workflow",
        PUBLICATION_SIGNER_WORKFLOW,
        "--source-ref",
        "refs/heads/main",
        "--source-digest",
        expected_commit,
        "--signer-digest",
        expected_commit,
        "--deny-self-hosted-runners",
        "--format",
        "json",
    )
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise PublicationError(
            f"cannot execute GitHub attestation verifier: {exc}"
        ) from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip()
        suffix = f": {detail}" if detail else ""
        raise PublicationError(
            f"GitHub artifact attestation verification failed{suffix}"
        )
    try:
        verified = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise PublicationError(
            "GitHub attestation verifier did not return JSON"
        ) from exc
    if not isinstance(verified, list) or not verified:
        raise PublicationError("GitHub attestation verifier returned no attestations")


def _extract_exact_candidate(archive: Path, destination: Path) -> None:
    expected_names = {"candidate.json", "result", *_RESULT_FILES}
    try:
        with tarfile.open(archive, mode="r:gz") as source:
            members = source.getmembers()
            names = [member.name.rstrip("/") for member in members]
            if len(names) != len(set(names)) or set(names) != expected_names:
                raise PublicationError(
                    "publication archive does not contain the exact candidate inventory"
                )
            for member, name in zip(members, names, strict=True):
                if name == "result":
                    if not member.isdir():
                        raise PublicationError(
                            "publication archive result entry must be a directory"
                        )
                    (destination / "result").mkdir()
                    continue
                if not member.isfile() or member.size > _MAX_ARCHIVE_FILE_BYTES:
                    raise PublicationError(
                        f"publication archive entry is unsafe: {member.name}"
                    )
                extracted = source.extractfile(member)
                if extracted is None:
                    raise PublicationError(
                        f"cannot read publication archive entry: {member.name}"
                    )
                payload = extracted.read(_MAX_ARCHIVE_FILE_BYTES + 1)
                if len(payload) != member.size:
                    raise PublicationError(
                        f"publication archive entry size changed: {member.name}"
                    )
                output = destination / name
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(payload)
    except PublicationError:
        raise
    except (OSError, tarfile.TarError) as exc:
        raise PublicationError(f"cannot read publication archive: {exc}") from exc


def _text(candidate: dict[str, object], key: str) -> str:
    value = candidate[key]
    if not isinstance(value, str) or not value or value != value.strip():
        raise PublicationError(f"candidate {key} must be a non-empty trimmed string")
    return value


def verify_publication_candidate(
    archive: Path,
    *,
    corpus: Corpus,
    dataset: QuerySet,
    expected_commit: str,
    registry: RetrieverRegistry = default_registry,
    workspace_root: Path,
) -> VerifiedPublicationCandidate:
    """Require cryptographic provenance, reviewed labels, and exact result bytes."""

    if _COMMIT_RE.fullmatch(expected_commit) is None:
        raise PublicationError("expected commit must be a full lowercase Git SHA")
    dataset.require_reviewed_labels()
    _require_attestation(archive, expected_commit=expected_commit)

    with tempfile.TemporaryDirectory(prefix="blogeval-publication-") as directory:
        extracted = Path(directory)
        _extract_exact_candidate(archive, extracted)
        try:
            raw_candidate, _ = load_canonical_json(extracted / "candidate.json")
        except StrictJsonError as exc:
            raise PublicationError(str(exc)) from exc
        if not isinstance(raw_candidate, dict) or set(raw_candidate) != _CANDIDATE_KEYS:
            raise PublicationError("candidate metadata has an unexpected object shape")
        candidate = cast(dict[str, object], raw_candidate)

        exact_values = {
            "commit_sha": expected_commit,
            "content_git_tree_sha": dataset.corpus.git_tree_sha,
            "dataset_checksum": dataset.checksum,
            "dataset_id": dataset.dataset_id,
            "dataset_label_status": "owner-reviewed",
            "publication_status": PUBLICATION_CANDIDATE_STATUS,
            "schema": PUBLICATION_CANDIDATE_SCHEMA,
            "workflow_identity": PUBLICATION_WORKFLOW_IDENTITY,
        }
        for key, expected in exact_values.items():
            if candidate[key] != expected:
                raise PublicationError(f"candidate {key} does not match {expected!r}")
        image_digest = _text(candidate, "execution_image_digest")
        result_digest = _text(candidate, "result_digest")
        run_id = _text(candidate, "run_id")
        workflow_run_id = _text(candidate, "workflow_run_id")
        if _SHA256_RE.fullmatch(image_digest) is None:
            raise PublicationError("candidate execution image digest is malformed")
        if _SHA256_RE.fullmatch(result_digest) is None:
            raise PublicationError("candidate result digest is malformed")
        if _RUN_ID_RE.fullmatch(run_id) is None:
            raise PublicationError("candidate run ID is malformed")
        if not workflow_run_id.isascii() or not workflow_run_id.isdecimal():
            raise PublicationError("candidate workflow run ID must be decimal")

        try:
            raw_run, _ = load_canonical_json(extracted / "result/run.json")
        except StrictJsonError as exc:
            raise PublicationError(str(exc)) from exc
        if not isinstance(raw_run, Mapping):
            raise PublicationError("candidate run must be a JSON object")
        try:
            recorded_provenance = parse_run_provenance(raw_run.get("provenance"))
        except ProvenanceError as exc:
            raise PublicationError(str(exc)) from exc
        _verify_checkout_identity(
            workspace_root,
            expected_commit=expected_commit,
            recorded=recorded_provenance,
        )

        try:
            verified = verify_run_directory(
                extracted / "result",
                corpus=corpus,
                dataset=dataset,
                registry=registry,
            )
        except EvaluationError as exc:
            raise PublicationError(str(exc)) from exc
        if verified.result_digest != result_digest:
            raise PublicationError(
                "candidate result digest differs from the verified result"
            )
        if verified.run.run_id != run_id:
            raise PublicationError("candidate run ID differs from the verified result")
        if verified.run.provenance.runtime.system != "Linux":
            raise PublicationError("publication result was not produced on Linux")
        if verified.run.provenance.runtime.machine != "x86_64":
            raise PublicationError("publication result was not produced on x86_64")

        return VerifiedPublicationCandidate(
            commit_sha=expected_commit,
            execution_image_digest=image_digest,
            result_digest=result_digest,
            run_id=run_id,
            workflow_run_id=workflow_run_id,
        )


__all__ = [
    "PUBLICATION_CANDIDATE_SCHEMA",
    "PUBLICATION_CANDIDATE_STATUS",
    "PUBLICATION_REPOSITORY",
    "PUBLICATION_SIGNER_WORKFLOW",
    "PUBLICATION_WORKFLOW_IDENTITY",
    "PublicationError",
    "VerifiedPublicationCandidate",
    "verify_publication_candidate",
]
