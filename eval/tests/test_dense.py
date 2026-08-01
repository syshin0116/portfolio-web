from __future__ import annotations

import json
import os
import tomllib
from collections.abc import Sequence
from importlib.metadata import PackageNotFoundError
from pathlib import Path

import pytest
from agent.retrieval import registry as agent_registry
from agent.retrieval.corpus import PublishedCorpus
from agent.retrieval.corpus_build import build_index
from agent.retrieval.protocol import DocId, Hit, Retrieval

import blogeval.lab.dense as dense_module
from blogeval.datasets import parse_queryset
from blogeval.jsonio import canonical_json_bytes, json_checksum
from blogeval.lab.dense import (
    DENSE_CONFIG,
    DENSE_METHOD_ID,
    DENSE_MODEL_ID,
    DENSE_MODEL_REVISION,
    DenseModelUnavailableError,
    DenseRetriever,
    SentenceTransformerE5Backend,
)
from blogeval.methods.rrf import (
    DENSE_RRF_CONFIG,
    DENSE_RRF_IMPLEMENTATION_ID,
    DENSE_RRF_METHOD_ID,
    RRF_METHOD_ID,
    ReciprocalRankFusionRetriever,
)
from blogeval.registry import registry
from blogeval.runner import run_evaluation
from conftest import MemoryCorpus


def _basis(index: int) -> tuple[float, ...]:
    return tuple(1.0 if position == index else 0.0 for position in range(384))


class ScriptedBackend:
    def __init__(
        self,
        document_vectors: Sequence[Sequence[float]],
        query_vectors: dict[str, Sequence[float]],
    ) -> None:
        self.document_vectors = tuple(document_vectors)
        self.query_vectors = query_vectors
        self.document_calls: list[tuple[str, ...]] = []
        self.query_calls: list[str] = []

    def embed_documents(
        self,
        texts: Sequence[str],
    ) -> Sequence[Sequence[float]]:
        self.document_calls.append(tuple(texts))
        return self.document_vectors

    def embed_query(self, text: str) -> Sequence[float]:
        self.query_calls.append(text)
        return self.query_vectors[text]


class FixedRetriever:
    def __init__(self, rankings: dict[str, tuple[str, ...]]) -> None:
        self._rankings = rankings

    def retrieve(self, query: str, *, limit: int = 10) -> Retrieval:
        return Retrieval(
            query=query,
            hits=tuple(
                Hit(doc_id=DocId(doc_id), rank=rank, score=None)
                for rank, doc_id in enumerate(
                    self._rankings.get(query, ())[:limit],
                    start=1,
                )
            ),
        )


def test_dense_retriever_exact_cosine_ranking_is_stable_and_ties_by_doc_id(
    memory_corpus: MemoryCorpus,
) -> None:
    backend = ScriptedBackend(
        (_basis(0), _basis(1), _basis(0)),
        {"도커 컨테이너": _basis(0)},
    )
    retriever = DenseRetriever(memory_corpus, backend=backend)

    first = retriever.retrieve("도커 컨테이너", limit=3)
    second = retriever.retrieve("도커 컨테이너", limit=3)

    assert first.doc_ids() == (
        DocId("AI/alpha.md"),
        DocId("Dev/gamma.md"),
        DocId("AI/beta.md"),
    )
    assert first.as_dict() == second.as_dict()
    assert first.hits[0].score == pytest.approx(1.0)
    assert first.hits[1].score == pytest.approx(1.0)
    assert first.hits[2].score == pytest.approx(0.0)
    assert backend.document_calls == [
        (
            "Alpha Docker container guide",
            "Beta Kubernetes cluster guide",
            "Gamma deployment notes",
        )
    ]
    assert backend.query_calls == ["도커 컨테이너", "도커 컨테이너"]


def test_dense_retriever_l2_normalizes_backend_vectors(
    memory_corpus: MemoryCorpus,
) -> None:
    backend = ScriptedBackend(
        (
            tuple(3.0 * value for value in _basis(0)),
            tuple(9.0 * value for value in _basis(1)),
            tuple(2.0 * value for value in _basis(2)),
        ),
        {"query": tuple(7.0 * value for value in _basis(1))},
    )

    result = DenseRetriever(memory_corpus, backend=backend).retrieve("query", limit=1)

    assert result.doc_ids() == (DocId("AI/beta.md"),)
    assert result.hits[0].score == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("document_vectors", "error"),
    [
        ((_basis(0),), "document embedding count"),
        ((_basis(0)[:-1], _basis(1), _basis(2)), "exactly 384 dimensions"),
        (((0.0,) * 384, _basis(1), _basis(2)), "must be non-zero"),
        (
            (
                (float("inf"),) + (0.0,) * 383,
                _basis(1),
                _basis(2),
            ),
            "only finite numbers",
        ),
    ],
)
def test_dense_retriever_rejects_malformed_document_embeddings(
    memory_corpus: MemoryCorpus,
    document_vectors: Sequence[Sequence[float]],
    error: str,
) -> None:
    backend = ScriptedBackend(document_vectors, {"query": _basis(0)})

    with pytest.raises(ValueError, match=error):
        DenseRetriever(memory_corpus, backend=backend)


def test_dense_retriever_validates_queries_before_embedding(
    memory_corpus: MemoryCorpus,
) -> None:
    backend = ScriptedBackend(
        (_basis(0), _basis(1), _basis(2)),
        {"bad": _basis(0)[:-1]},
    )
    retriever = DenseRetriever(memory_corpus, backend=backend)

    assert retriever.retrieve("   ", limit=3).hits == ()
    assert backend.query_calls == []
    with pytest.raises(ValueError, match="non-negative integer"):
        retriever.retrieve("query", limit=-1)
    with pytest.raises(TypeError, match="query must be a string"):
        retriever.retrieve(123)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="exactly 384 dimensions"):
        retriever.retrieve("bad")


class RecordingModel:
    max_seq_length = 512

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    def get_embedding_dimension(self) -> int:
        return 384

    def encode(self, sentences: Sequence[str], **kwargs: object) -> object:
        self.calls.append((tuple(sentences), kwargs))
        return [_basis(index % 2) for index, _ in enumerate(sentences)]


def test_e5_backend_locks_revision_offline_mode_prefixes_and_encode_policy() -> None:
    model = RecordingModel()
    factory_calls: list[tuple[str, dict[str, object]]] = []

    def factory(model_id: str, **kwargs: object) -> RecordingModel:
        factory_calls.append((model_id, kwargs))
        return model

    backend = SentenceTransformerE5Backend(_model_factory=factory)

    documents = backend.embed_documents(("문서", "document"))
    query = backend.embed_query("검색어")

    assert len(documents) == 2
    assert query == _basis(0)
    assert factory_calls == [
        (
            DENSE_MODEL_ID,
            {
                "device": "cpu",
                "local_files_only": True,
                "revision": DENSE_MODEL_REVISION,
                "trust_remote_code": False,
            },
        )
    ]
    assert model.calls == [
        (
            ("passage: 문서", "passage: document"),
            {
                "batch_size": 16,
                "convert_to_numpy": True,
                "normalize_embeddings": True,
                "precision": "float32",
                "show_progress_bar": False,
            },
        ),
        (
            ("query: 검색어",),
            {
                "batch_size": 16,
                "convert_to_numpy": True,
                "normalize_embeddings": True,
                "precision": "float32",
                "show_progress_bar": False,
            },
        ),
    ]


def test_e5_backend_fails_closed_when_optional_runtime_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_distribution(_: str) -> str:
        raise PackageNotFoundError

    monkeypatch.setattr(dense_module, "distribution_version", missing_distribution)

    with pytest.raises(DenseModelUnavailableError, match="--extra dense"):
        SentenceTransformerE5Backend()


def test_e5_backend_rejects_runtime_version_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installed = {
        "numpy": "2.4.4",
        "sentence-transformers": "5.6.0",
        "torch": "9.0.0",
        "transformers": "5.14.1",
    }
    monkeypatch.setattr(
        dense_module,
        "distribution_version",
        lambda package: installed[package],
    )

    with pytest.raises(
        DenseModelUnavailableError,
        match=r"requires torch in \('2.13.0', '2.13.0\+cpu'\), found 9.0.0",
    ):
        SentenceTransformerE5Backend()


def test_eval_registry_exposes_dense_and_bm25_dense_rrf_only_to_evaluation(
    memory_corpus: MemoryCorpus,
) -> None:
    dense_registration = registry.retrievable[DENSE_METHOD_ID]
    rrf_registration = registry.retrievable[DENSE_RRF_METHOD_ID]

    assert DENSE_METHOD_ID not in registry.servable
    assert DENSE_RRF_METHOD_ID not in registry.servable
    assert DENSE_METHOD_ID not in agent_registry.retrievable
    assert DENSE_RRF_METHOD_ID not in agent_registry.retrievable
    assert dense_registration.config == DENSE_CONFIG
    assert rrf_registration.config == DENSE_RRF_CONFIG
    assert dense_registration.data_dependencies == (
        "corpus:published-markdown",
        f"model:huggingface/{DENSE_MODEL_ID}@{DENSE_MODEL_REVISION}",
    )
    assert registry.retrievable.fingerprint(
        DENSE_METHOD_ID,
        memory_corpus,
    ).startswith("sha256:")


def test_dense_extra_locks_cpu_only_torch_and_exact_inference_stack() -> None:
    eval_root = Path(__file__).resolve().parents[1]
    workspace_root = eval_root.parent
    pyproject = tomllib.loads(
        (eval_root / "pyproject.toml").read_text(encoding="utf-8")
    )
    lock = tomllib.loads((workspace_root / "uv.lock").read_text(encoding="utf-8"))

    assert pyproject["project"]["optional-dependencies"]["dense"] == [
        "sentence-transformers==5.6.0",
        "torch==2.13.0",
        "transformers==5.14.1",
    ]
    assert pyproject["tool"]["uv"]["sources"]["torch"] == {"index": "pytorch-cpu"}
    assert pyproject["tool"]["uv"]["index"] == [
        {
            "explicit": True,
            "name": "pytorch-cpu",
            "url": "https://download.pytorch.org/whl/cpu",
        }
    ]
    assert DENSE_CONFIG["embedding"]["packages"] == {
        "numpy": ["2.4.4"],
        "sentence-transformers": ["5.6.0"],
        "torch": ["2.13.0", "2.13.0+cpu"],
        "transformers": ["5.14.1"],
    }
    torch_packages = [
        package for package in lock["package"] if package["name"] == "torch"
    ]
    assert torch_packages
    assert all(
        package["source"]["registry"] == "https://download.pytorch.org/whl/cpu"
        for package in torch_packages
    )
    assert not any(
        package["name"] == "triton" or package["name"].startswith(("cuda-", "nvidia-"))
        for package in lock["package"]
    )


def test_rrf_fingerprint_uses_the_selected_fusion_method_identity(
    memory_corpus: MemoryCorpus,
) -> None:
    components = (
        (
            "left",
            "sha256:" + "1" * 64,
            FixedRetriever({"query": ("AI/alpha.md",)}),
        ),
        (
            "right",
            "sha256:" + "2" * 64,
            FixedRetriever({"query": ("AI/beta.md",)}),
        ),
    )
    lexical = ReciprocalRankFusionRetriever(
        corpus=memory_corpus,
        components=components,
        config={
            "candidate_multiplier": 2,
            "components": ["left", "right"],
            "minimum_candidates": 2,
            "rrf_k": 60,
        },
    )
    dense = ReciprocalRankFusionRetriever(
        corpus=memory_corpus,
        components=components,
        config={
            "candidate_multiplier": 2,
            "components": ["left", "right"],
            "minimum_candidates": 2,
            "rrf_k": 60,
        },
        method_id=DENSE_RRF_METHOD_ID,
        implementation_id=DENSE_RRF_IMPLEMENTATION_ID,
    )

    assert lexical.fingerprint != dense.fingerprint
    assert lexical.retrieve("query").doc_ids() == dense.retrieve("query").doc_ids()
    assert RRF_METHOD_ID != DENSE_RRF_METHOD_ID


def _write_post(content: Path, doc_id: str, *, title: str, body: str) -> None:
    path = content / doc_id
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            (
                "---",
                f"title: {json.dumps(title, ensure_ascii=False)}",
                "tags: []",
                'description: ""',
                "---",
                body,
                "",
            )
        ),
        encoding="utf-8",
    )


def _build_index(tmp_path: Path) -> PublishedCorpus:
    content = tmp_path / "content"
    _write_post(content, "AI/a-title.md", title="도커", body="컨테이너 안내")
    _write_post(content, "AI/b-body.md", title="본문", body="도커 컨테이너")
    for doc_id, title, body in (
        ("AI/c.md", "파이썬", "테스트"),
        ("AI/d.md", "쿠버네티스", "클러스터"),
        ("AI/e.md", "랭그래프", "에이전트"),
        ("AI/f.md", "검색", "평가"),
    ):
        _write_post(content, doc_id, title=title, body=body)
    corpus_policy = tmp_path / "corpus-policy.toml"
    corpus_policy.write_text(
        "schema_version = 1\nno_frontmatter_allowlist = []\n",
        encoding="utf-8",
    )
    bm25_policy = tmp_path / "bm25-policy.toml"
    bm25_policy.write_text(
        "\n".join(
            (
                "schema_version = 1",
                'policy_id = "dense-harness-test"',
                'seeds = ["도커"]',
                "deny = []",
                "",
            )
        ),
        encoding="utf-8",
    )
    output = tmp_path / "index"
    build_index(
        content_root=content,
        policy_path=corpus_policy,
        bm25_policy_path=bm25_policy,
        output_root=output,
    )
    return PublishedCorpus(output)


def _dataset(corpus: PublishedCorpus):
    value = {
        "corpus": {
            "document_count": len(corpus.doc_ids()),
            "fingerprint": corpus.fingerprint,
            "git_tree_sha": corpus.content_git_tree_sha,
        },
        "dataset_id": "dense-contract-v1",
        "dataset_kind": "known-item",
        "exclusions": [],
        "labels": {
            "review": None,
            "reviewed_qrels_checksum": None,
            "status": "synthetic-only",
        },
        "provenance": {
            "generator": "dense-contract",
            "generator_version": 1,
            "included_occurrence_count": 1,
            "source_artifacts": [],
            "source_occurrence_count": 1,
        },
        "qrels": [
            {
                "evidence": [
                    {
                        "kind": "synthetic-contract",
                        "occurrences": 1,
                        "source_doc_id": "AI/b-body.md",
                        "target": "a-title",
                    }
                ],
                "query": "도커 컨테이너",
                "query_id": "known-docker",
                "relevant_doc_ids": ["AI/a-title.md"],
            }
        ],
        "schema": "blogeval-queryset-v2",
    }
    payload = canonical_json_bytes(value)
    return parse_queryset(value, checksum=json_checksum(payload))


class KeywordBackend:
    def embed_documents(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        return tuple(
            _basis(0) if "도커" in text else _basis(index + 1)
            for index, text in enumerate(texts)
        )

    def embed_query(self, text: str) -> Sequence[float]:
        assert text == "도커 컨테이너"
        return _basis(0)


def test_runner_executes_bm25_dense_and_their_registered_rrf_with_fake_embeddings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    corpus = _build_index(tmp_path)
    monkeypatch.setattr(
        dense_module,
        "SentenceTransformerE5Backend",
        lambda config: KeywordBackend(),
    )

    run = run_evaluation(
        corpus=corpus,
        dataset=_dataset(corpus),
        content_tree_sha=corpus.content_git_tree_sha,
        method_ids=("bm25", DENSE_METHOD_ID, DENSE_RRF_METHOD_ID),
        cutoffs=(1, 3),
        registry=registry,
    )

    methods = {method.method_id: method for method in run.methods}
    assert set(methods) == {"bm25", DENSE_METHOD_ID, DENSE_RRF_METHOD_ID}
    assert methods[DENSE_METHOD_ID].queries[0].retrieved_doc_ids[0] == "AI/a-title.md"
    assert (
        methods[DENSE_RRF_METHOD_ID].queries[0].retrieved_doc_ids[0] == "AI/a-title.md"
    )
    assert methods[DENSE_METHOD_ID].metrics.as_dict()["metrics"]["hit@1"] == 1.0
    assert (
        methods[DENSE_RRF_METHOD_ID].identity_config["component_fingerprints"][1][
            "method_id"
        ]
        == DENSE_METHOD_ID
    )


@pytest.mark.real_dense
def test_cached_real_multilingual_e5_smoke() -> None:
    if os.environ.get("BLOGEVAL_REAL_DENSE_SMOKE") != "1":
        pytest.skip("set BLOGEVAL_REAL_DENSE_SMOKE=1 for the offline model smoke")
    corpus = MemoryCorpus(
        {
            DocId("AI/docker.md"): "Docker 컨테이너 이미지 빌드와 배포 가이드",
            DocId("AI/kubernetes.md"): "쿠버네티스 클러스터 운영과 파드 스케줄링",
            DocId("Others/recipe.md"): "바나나와 우유를 이용한 아침 스무디 레시피",
        }
    )

    result = DenseRetriever(corpus).retrieve("도커 컨테이너를 배포하는 방법", limit=1)

    assert result.doc_ids() == (DocId("AI/docker.md"),)
