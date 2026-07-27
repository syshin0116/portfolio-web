from __future__ import annotations

import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest
from agent.retrieval.registry import RetrieverRegistry

import blogeval.publication as publication_module
import blogeval.runner as runner_module
from blogeval.datasets import DatasetError, parse_queryset, qrels_checksum
from blogeval.jsonio import canonical_json_bytes, json_checksum
from blogeval.provenance import RunProvenance, RuntimePlatform
from blogeval.publication import (
    PUBLICATION_REPOSITORY,
    PUBLICATION_SIGNER_WORKFLOW,
    PUBLICATION_WORKFLOW_IDENTITY,
    PublicationError,
    verify_publication_candidate,
)
from blogeval.runner import run_evaluation, write_run_artifacts
from conftest import MemoryCorpus, RankedRetriever

EXPECTED_COMMIT = "c" * 40


def _reviewed_dataset(known_dataset):
    value = known_dataset.as_dict()
    value["labels"] = {
        "review": {
            "review_ref": "owner-review:known-contract-v1",
            "reviewed_at": "2026-07-28",
            "reviewer": "@owner",
        },
        "reviewed_qrels_checksum": qrels_checksum(known_dataset.qrels),
        "status": "owner-reviewed",
    }
    payload = canonical_json_bytes(value)
    return parse_queryset(value, checksum=json_checksum(payload))


def _registry() -> RetrieverRegistry:
    registry = RetrieverRegistry()
    registry.register(
        "method",
        RankedRetriever,
        implementation_id="tests:publication@1",
        config={
            "rankings": {
                "alpha": ["AI/alpha.md"],
                "beta": ["AI/beta.md"],
            }
        },
        data_dependencies=("corpus:unrelated-holdout",),
        servable=False,
    )
    return registry


def _candidate_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    memory_corpus: MemoryCorpus,
    known_dataset,
    *,
    metadata_mutation: tuple[str, object] | None = None,
):
    reviewed = _reviewed_dataset(known_dataset)
    provenance = RunProvenance(
        agent_source_tree="sha256:" + "a" * 64,
        eval_source_tree="sha256:" + "b" * 64,
        workspace_lock="sha256:" + "c" * 64,
        runtime=RuntimePlatform(
            system="Linux",
            machine="x86_64",
            python_implementation="CPython",
            python_version="3.12.12",
        ),
    )
    monkeypatch.setattr(runner_module, "collect_run_provenance", lambda: provenance)
    run = run_evaluation(
        corpus=memory_corpus,
        dataset=reviewed,
        content_tree_sha="a" * 40,
        method_ids=("method",),
        cutoffs=(1,),
        registry=_registry(),
    )
    artifacts = write_run_artifacts(run, output_root=tmp_path / "results")

    staging = tmp_path / "candidate"
    staging.mkdir()
    shutil.copytree(artifacts.directory, staging / "result")
    candidate = {
        "commit_sha": EXPECTED_COMMIT,
        "content_git_tree_sha": reviewed.corpus.git_tree_sha,
        "dataset_label_status": "owner-reviewed",
        "execution_image_digest": "sha256:" + "d" * 64,
        "publication_status": "candidate-awaiting-external-verification",
        "result_digest": artifacts.result_digest,
        "run_id": run.run_id,
        "schema": "blogeval-publication-candidate-v1",
        "workflow_identity": PUBLICATION_WORKFLOW_IDENTITY,
        "workflow_run_id": "123456",
    }
    if metadata_mutation is not None:
        key, value = metadata_mutation
        candidate[key] = value
    (staging / "candidate.json").write_bytes(canonical_json_bytes(candidate))
    archive = tmp_path / "blogeval-candidate.tar.gz"
    with tarfile.open(archive, mode="w:gz") as output:
        output.add(staging / "candidate.json", arcname="candidate.json")
        output.add(staging / "result", arcname="result")
    return archive, reviewed


def _successful_attestation(command, **kwargs):
    assert kwargs == {
        "check": False,
        "capture_output": True,
        "text": True,
    }
    return subprocess.CompletedProcess(command, 0, '[{"verificationResult": {}}]', "")


def test_publication_verifier_requires_exact_github_attestation_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    memory_corpus: MemoryCorpus,
    known_dataset,
) -> None:
    archive, reviewed = _candidate_archive(
        tmp_path,
        monkeypatch,
        memory_corpus,
        known_dataset,
    )
    calls = []

    def verify(command, **kwargs):
        calls.append(command)
        return _successful_attestation(command, **kwargs)

    monkeypatch.setattr(publication_module.subprocess, "run", verify)

    candidate = verify_publication_candidate(
        archive,
        dataset=reviewed,
        expected_commit=EXPECTED_COMMIT,
    )

    assert candidate.commit_sha == EXPECTED_COMMIT
    assert calls == [
        (
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
            EXPECTED_COMMIT,
            "--signer-digest",
            EXPECTED_COMMIT,
            "--deny-self-hosted-runners",
            "--format",
            "json",
        )
    ]


@pytest.mark.parametrize(
    ("returncode", "stdout"),
    (
        (1, ""),
        (0, "[]"),
        (0, "not-json"),
    ),
)
def test_publication_verifier_rejects_missing_or_invalid_attestation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    memory_corpus: MemoryCorpus,
    known_dataset,
    returncode: int,
    stdout: str,
) -> None:
    archive, reviewed = _candidate_archive(
        tmp_path,
        monkeypatch,
        memory_corpus,
        known_dataset,
    )
    monkeypatch.setenv("BLOGEVAL_IMAGE_DIGEST", "sha256:" + "f" * 64)
    monkeypatch.setattr(
        publication_module.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command,
            returncode,
            stdout,
            "not attested",
        ),
    )

    with pytest.raises(PublicationError, match="attestation"):
        verify_publication_candidate(
            archive,
            dataset=reviewed,
            expected_commit=EXPECTED_COMMIT,
        )


def test_publication_verifier_rejects_unreviewed_dataset_before_promotion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    memory_corpus: MemoryCorpus,
    known_dataset,
) -> None:
    archive, _ = _candidate_archive(
        tmp_path,
        monkeypatch,
        memory_corpus,
        known_dataset,
    )
    called = False

    def unexpected_call(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("attestation lookup should not run for unreviewed qrels")

    monkeypatch.setattr(publication_module.subprocess, "run", unexpected_call)

    with pytest.raises(DatasetError, match="owner-reviewed"):
        verify_publication_candidate(
            archive,
            dataset=known_dataset,
            expected_commit=EXPECTED_COMMIT,
        )
    assert not called


def test_publication_verifier_rejects_attested_candidate_metadata_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    memory_corpus: MemoryCorpus,
    known_dataset,
) -> None:
    archive, reviewed = _candidate_archive(
        tmp_path,
        monkeypatch,
        memory_corpus,
        known_dataset,
        metadata_mutation=("workflow_identity", "attacker/workflow@refs/heads/main"),
    )
    monkeypatch.setattr(
        publication_module.subprocess,
        "run",
        _successful_attestation,
    )

    with pytest.raises(PublicationError, match="workflow_identity"):
        verify_publication_candidate(
            archive,
            dataset=reviewed,
            expected_commit=EXPECTED_COMMIT,
        )
