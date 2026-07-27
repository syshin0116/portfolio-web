from __future__ import annotations

from pathlib import Path

import pytest
from agent.retrieval.registry import RetrieverRegistry

import blogeval.runner as runner_module
from blogeval.provenance import (
    ProvenanceError,
    RuntimePlatform,
    collect_run_provenance,
)
from blogeval.runner import run_evaluation
from conftest import MemoryCorpus, RankedRetriever

FIXED_LINUX = RuntimePlatform(
    system="Linux",
    machine="x86_64",
    python_implementation="CPython",
    python_version="3.12.12",
)
IMAGE_DIGEST = "sha256:" + "1" * 64


def _workspace(path: Path) -> Path:
    agent_source = path / "agent/src/agent"
    eval_source = path / "eval/src/blogeval"
    agent_source.mkdir(parents=True)
    eval_source.mkdir(parents=True)
    (agent_source / "retriever.py").write_text("VERSION = 1\n", encoding="utf-8")
    (eval_source / "runner.py").write_text("VERSION = 1\n", encoding="utf-8")
    (path / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    return path


def _registry() -> RetrieverRegistry:
    registry = RetrieverRegistry()
    registry.register(
        "method",
        RankedRetriever,
        implementation_id="tests:method@1",
        config={
            "rankings": {
                "alpha": ["AI/alpha.md"],
                "beta": ["AI/beta.md"],
            }
        },
        servable=False,
    )
    return registry


def _run_with_provenance(
    monkeypatch: pytest.MonkeyPatch,
    provenance,
    *,
    memory_corpus: MemoryCorpus,
    known_dataset,
):
    monkeypatch.setattr(
        runner_module,
        "collect_run_provenance",
        lambda: provenance,
    )
    return run_evaluation(
        corpus=memory_corpus,
        dataset=known_dataset,
        content_tree_sha="a" * 40,
        method_ids=("method",),
        cutoffs=(1,),
        registry=_registry(),
    )


@pytest.mark.parametrize(
    "relative_path,digest_field",
    (
        ("agent/src/agent/retriever.py", "agent_source_tree"),
        ("eval/src/blogeval/runner.py", "eval_source_tree"),
    ),
)
def test_run_id_changes_when_source_tree_mutates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    memory_corpus: MemoryCorpus,
    known_dataset,
    relative_path: str,
    digest_field: str,
) -> None:
    workspace = _workspace(tmp_path)
    first_provenance = collect_run_provenance(
        workspace_root=workspace,
        runtime=FIXED_LINUX,
        image_digest=IMAGE_DIGEST,
    )
    first = _run_with_provenance(
        monkeypatch,
        first_provenance,
        memory_corpus=memory_corpus,
        known_dataset=known_dataset,
    )

    (workspace / relative_path).write_text("VERSION = 2\n", encoding="utf-8")
    second_provenance = collect_run_provenance(
        workspace_root=workspace,
        runtime=FIXED_LINUX,
        image_digest=IMAGE_DIGEST,
    )
    second = _run_with_provenance(
        monkeypatch,
        second_provenance,
        memory_corpus=memory_corpus,
        known_dataset=known_dataset,
    )

    assert getattr(first_provenance, digest_field) != getattr(
        second_provenance,
        digest_field,
    )
    assert first.run_id != second.run_id


def test_run_id_changes_when_workspace_lock_mutates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    memory_corpus: MemoryCorpus,
    known_dataset,
) -> None:
    workspace = _workspace(tmp_path)
    first_provenance = collect_run_provenance(
        workspace_root=workspace,
        runtime=FIXED_LINUX,
        image_digest=IMAGE_DIGEST,
    )
    first = _run_with_provenance(
        monkeypatch,
        first_provenance,
        memory_corpus=memory_corpus,
        known_dataset=known_dataset,
    )

    (workspace / "uv.lock").write_text("version = 2\n", encoding="utf-8")
    second_provenance = collect_run_provenance(
        workspace_root=workspace,
        runtime=FIXED_LINUX,
        image_digest=IMAGE_DIGEST,
    )
    second = _run_with_provenance(
        monkeypatch,
        second_provenance,
        memory_corpus=memory_corpus,
        known_dataset=known_dataset,
    )

    assert first_provenance.workspace_lock != second_provenance.workspace_lock
    assert first.run_id != second.run_id


def test_publication_requires_digest_pinned_linux_x86_64(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    qualified = collect_run_provenance(
        workspace_root=workspace,
        runtime=FIXED_LINUX,
        image_digest=IMAGE_DIGEST,
    )
    no_image = collect_run_provenance(
        workspace_root=workspace,
        runtime=FIXED_LINUX,
        image_digest=None,
    )
    macos = collect_run_provenance(
        workspace_root=workspace,
        runtime=RuntimePlatform(
            system="Darwin",
            machine="arm64",
            python_implementation="CPython",
            python_version="3.12.12",
        ),
        image_digest=IMAGE_DIGEST,
    )

    assert qualified.publication_eligible is True
    assert no_image.publication_eligible is False
    assert macos.publication_eligible is False


def test_run_id_changes_with_platform_and_image_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    memory_corpus: MemoryCorpus,
    known_dataset,
) -> None:
    workspace = _workspace(tmp_path)
    provenances = (
        collect_run_provenance(
            workspace_root=workspace,
            runtime=FIXED_LINUX,
            image_digest=IMAGE_DIGEST,
        ),
        collect_run_provenance(
            workspace_root=workspace,
            runtime=FIXED_LINUX,
            image_digest="sha256:" + "2" * 64,
        ),
        collect_run_provenance(
            workspace_root=workspace,
            runtime=RuntimePlatform(
                system="Darwin",
                machine="arm64",
                python_implementation="CPython",
                python_version="3.12.12",
            ),
            image_digest=IMAGE_DIGEST,
        ),
    )

    run_ids = {
        _run_with_provenance(
            monkeypatch,
            provenance,
            memory_corpus=memory_corpus,
            known_dataset=known_dataset,
        ).run_id
        for provenance in provenances
    }

    assert len(run_ids) == len(provenances)


def test_require_publishable_run_rejects_unqualified_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    memory_corpus: MemoryCorpus,
    known_dataset,
) -> None:
    provenance = collect_run_provenance(
        workspace_root=_workspace(tmp_path),
        runtime=FIXED_LINUX,
        image_digest=None,
    )
    monkeypatch.setattr(
        runner_module,
        "collect_run_provenance",
        lambda: provenance,
    )

    with pytest.raises(ProvenanceError, match="digest-pinned Linux x86_64"):
        run_evaluation(
            corpus=memory_corpus,
            dataset=known_dataset,
            content_tree_sha="a" * 40,
            method_ids=("method",),
            cutoffs=(1,),
            registry=_registry(),
            require_publishable=True,
        )


def test_invalid_image_digest_fails_closed(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)

    with pytest.raises(ProvenanceError, match="sha256"):
        collect_run_provenance(
            workspace_root=workspace,
            runtime=FIXED_LINUX,
            image_digest="latest",
        )
