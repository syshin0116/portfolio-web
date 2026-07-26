"""Retriever registrations and explicit serving/evaluation views."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass

from agent.retrieval.fingerprint import (
    canonical_config,
    retriever_fingerprint,
    validate_implementation_id,
)
from agent.retrieval.protocol import Corpus, Retrieval, Retriever

RetrieverFactory = Callable[[Corpus, Mapping[str, object]], Retriever]
RetrieverIdentityFactory = Callable[
    [Corpus, Mapping[str, object]],
    Mapping[str, object],
]


@dataclass(frozen=True, slots=True)
class RetrieverRegistration:
    """Immutable method registration shared or extended by registries."""

    method_id: str
    implementation_id: str
    factory: RetrieverFactory
    config_json: str
    servable: bool
    identity_factory: RetrieverIdentityFactory | None

    @property
    def config(self) -> dict[str, object]:
        """Return an isolated copy of the fingerprinted configuration."""

        value = json.loads(self.config_json)
        if not isinstance(value, dict):  # canonical_config guarantees this invariant.
            raise TypeError("registered retriever config is not an object")
        return value

    def identity_config(self, corpus: Corpus | None = None) -> dict[str, object]:
        if self.identity_factory is None:
            return self.config
        if corpus is None:
            raise ValueError(
                f"retriever {self.method_id!r} requires a Corpus to resolve "
                "artifact identity"
            )
        return json.loads(canonical_config(self.identity_factory(corpus, self.config)))

    def fingerprint(self, corpus: Corpus | str) -> str:
        if isinstance(corpus, str):
            if self.identity_factory is not None:
                raise ValueError(
                    f"retriever {self.method_id!r} requires a Corpus, not only a "
                    "corpus fingerprint, to include artifact identity"
                )
            corpus_fingerprint = corpus
            config = self.config
        else:
            corpus_fingerprint = getattr(corpus, "fingerprint", None)
            if not isinstance(corpus_fingerprint, str) or not corpus_fingerprint:
                raise ValueError("corpus fingerprint must be a non-empty string")
            config = self.identity_config(corpus)
        return retriever_fingerprint(
            method_id=self.method_id,
            implementation_id=self.implementation_id,
            config=config,
            corpus_fingerprint=corpus_fingerprint,
        )


@dataclass(frozen=True, slots=True)
class ResolvedRetriever:
    """A factory result carrying the registry identity used for this corpus."""

    registration: RetrieverRegistration
    corpus_fingerprint: str
    implementation: Retriever
    identity_config_json: str

    @property
    def method_id(self) -> str:
        return self.registration.method_id

    @property
    def config(self) -> dict[str, object]:
        return self.registration.config

    @property
    def identity_config(self) -> dict[str, object]:
        value = json.loads(self.identity_config_json)
        if not isinstance(value, dict):
            raise TypeError("resolved retriever identity config is not an object")
        return value

    @property
    def fingerprint(self) -> str:
        return retriever_fingerprint(
            method_id=self.registration.method_id,
            implementation_id=self.registration.implementation_id,
            config=self.identity_config,
            corpus_fingerprint=self.corpus_fingerprint,
        )

    def retrieve(self, query: str, *, limit: int = 10) -> Retrieval:
        result = self.implementation.retrieve(query, limit=limit)
        if not isinstance(result, Retrieval):
            raise TypeError(
                f"retriever {self.method_id!r} returned {type(result).__name__}, "
                "expected Retrieval"
            )
        return result


class RegistryView(Mapping[str, RetrieverRegistration]):
    """Dynamic read-only view of either all retrievable or servable methods."""

    def __init__(
        self,
        registry: RetrieverRegistry,
        *,
        servable_only: bool,
    ) -> None:
        self._registry = registry
        self._servable_only = servable_only

    def _includes(self, registration: RetrieverRegistration) -> bool:
        return not self._servable_only or registration.servable

    def __getitem__(self, method_id: str) -> RetrieverRegistration:
        try:
            registration = self._registry._registrations[method_id]
        except KeyError:
            raise KeyError(f"retriever {method_id!r} is not registered") from None
        if not self._includes(registration):
            raise KeyError(
                f"retriever {method_id!r} is not available in the servable registry"
            )
        return registration

    def __iter__(self) -> Iterator[str]:
        return iter(
            sorted(
                method_id
                for method_id, registration in self._registry._registrations.items()
                if self._includes(registration)
            )
        )

    def __len__(self) -> int:
        return sum(
            self._includes(registration)
            for registration in self._registry._registrations.values()
        )

    def create(self, method_id: str, corpus: Corpus) -> ResolvedRetriever:
        registration = self[method_id]
        corpus_fingerprint = getattr(corpus, "fingerprint", None)
        if not isinstance(corpus_fingerprint, str) or not corpus_fingerprint:
            raise ValueError("corpus fingerprint must be a non-empty string")

        implementation = registration.factory(corpus, registration.config)
        if not isinstance(implementation, Retriever):
            raise TypeError(
                f"factory for {method_id!r} returned an object without retrieve()"
            )
        expected_identity = registration.identity_config(corpus)
        implementation_identity = getattr(implementation, "identity_config", None)
        if implementation_identity is not None:
            actual_identity_json = canonical_config(implementation_identity)
            if actual_identity_json != canonical_config(expected_identity):
                raise ValueError(
                    f"retriever {method_id!r} runtime identity differs from its "
                    "registered identity"
                )
        return ResolvedRetriever(
            registration=registration,
            corpus_fingerprint=corpus_fingerprint,
            implementation=implementation,
            identity_config_json=canonical_config(expected_identity),
        )

    def fingerprint(self, method_id: str, corpus: Corpus | str) -> str:
        return self[method_id].fingerprint(corpus)


class RetrieverRegistry:
    """Mutable registration set with explicit read-only consumption views."""

    def __init__(
        self,
        registrations: Iterable[RetrieverRegistration] | None = None,
    ) -> None:
        self._registrations: dict[str, RetrieverRegistration] = {}
        for registration in registrations or ():
            self._add(registration)

    @property
    def retrievable(self) -> RegistryView:
        """Every locally registered method, including eval-only lab methods."""

        return RegistryView(self, servable_only=False)

    @property
    def servable(self) -> RegistryView:
        """Only methods permitted in the deployed chat image."""

        return RegistryView(self, servable_only=True)

    def register(
        self,
        method_id: str,
        factory: RetrieverFactory,
        *,
        implementation_id: str,
        config: Mapping[str, object] | None = None,
        servable: bool = True,
        identity_factory: RetrieverIdentityFactory | None = None,
    ) -> RetrieverRegistration:
        if not isinstance(method_id, str) or not method_id.strip():
            raise ValueError("method_id must be a non-empty string")
        if method_id != method_id.strip():
            raise ValueError("method_id cannot contain leading or trailing whitespace")
        if not callable(factory):
            raise TypeError("factory must be callable")
        if not isinstance(servable, bool):
            raise TypeError("servable must be a boolean")
        if identity_factory is not None and not callable(identity_factory):
            raise TypeError("identity_factory must be callable or None")

        registration = RetrieverRegistration(
            method_id=method_id,
            implementation_id=validate_implementation_id(implementation_id),
            factory=factory,
            config_json=canonical_config({} if config is None else config),
            servable=servable,
            identity_factory=identity_factory,
        )
        self._add(registration)
        return registration

    def _add(self, registration: RetrieverRegistration) -> None:
        if registration.method_id in self._registrations:
            raise ValueError(
                f"retriever {registration.method_id!r} is already registered"
            )
        self._registrations[registration.method_id] = registration

    def copy(self) -> RetrieverRegistry:
        """Copy registrations so eval can extend without mutating agent serving."""

        return RetrieverRegistry(iter(self._registrations.values()))


registry = RetrieverRegistry()
retrievable = registry.retrievable
servable = registry.servable

__all__ = [
    "RegistryView",
    "ResolvedRetriever",
    "RetrieverFactory",
    "RetrieverIdentityFactory",
    "RetrieverRegistration",
    "RetrieverRegistry",
    "registry",
    "retrievable",
    "servable",
]
