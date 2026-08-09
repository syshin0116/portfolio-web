from __future__ import annotations

import hashlib
import json
import unittest

from scripts.resolve_agent_runtime_image import ResolutionError, resolve_runtime_image

PRODUCTION_REPOSITORY = (
    "asia-southeast1-docker.pkg.dev/festive-ally-503605-v7/agent/agent"
)
PREVIEW_REPOSITORY = (
    "asia-southeast1-docker.pkg.dev/festive-ally-503605-v7/agent-preview/agent"
)
RUNTIME_DIGEST = "sha256:" + "1" * 64
ATTESTATION_DIGEST = "sha256:" + "2" * 64


def index_document() -> dict[str, object]:
    return {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.index.v1+json",
        "manifests": [
            {
                "mediaType": "application/vnd.oci.image.manifest.v1+json",
                "digest": RUNTIME_DIGEST,
                "size": 1234,
                "platform": {"architecture": "amd64", "os": "linux"},
            },
            {
                "mediaType": "application/vnd.oci.image.manifest.v1+json",
                "digest": ATTESTATION_DIGEST,
                "size": 5678,
                "platform": {"architecture": "unknown", "os": "unknown"},
                "annotations": {
                    "vnd.docker.reference.digest": RUNTIME_DIGEST,
                    "vnd.docker.reference.type": "attestation-manifest",
                },
            },
        ],
    }


def encode(document: object) -> tuple[bytes, str]:
    raw = json.dumps(document, separators=(",", ":")).encode()
    return raw, f"sha256:{hashlib.sha256(raw).hexdigest()}"


class RuntimeImageResolutionTests(unittest.TestCase):
    def test_resolves_exact_runtime_for_each_isolated_repository(self) -> None:
        raw, index_digest = encode(index_document())
        for repository in (PRODUCTION_REPOSITORY, PREVIEW_REPOSITORY):
            with self.subTest(repository=repository):
                self.assertEqual(
                    f"{repository}@{RUNTIME_DIGEST}",
                    resolve_runtime_image(
                        raw,
                        image_repository=repository,
                        index_digest=index_digest,
                    ),
                )

    def test_rejects_body_not_bound_to_selected_index_digest(self) -> None:
        raw, _index_digest = encode(index_document())
        with self.assertRaisesRegex(ResolutionError, "does not match"):
            resolve_runtime_image(
                raw,
                image_repository=PRODUCTION_REPOSITORY,
                index_digest="sha256:" + "f" * 64,
            )

    def test_rejects_unselected_repository_or_noncanonical_digest(self) -> None:
        raw, index_digest = encode(index_document())
        cases = (
            ("us-docker.pkg.dev/other/agent/agent", index_digest),
            (PRODUCTION_REPOSITORY, "sha256:ABC"),
        )
        for repository, digest in cases:
            with self.subTest(repository=repository, digest=digest):
                with self.assertRaises(ResolutionError):
                    resolve_runtime_image(
                        raw,
                        image_repository=repository,
                        index_digest=digest,
                    )

    def test_rejects_invalid_body_shape(self) -> None:
        for raw in (b"", b"[]", b"not-json", b"x" * 1_048_577):
            digest = f"sha256:{hashlib.sha256(raw).hexdigest()}"
            with self.subTest(size=len(raw)):
                with self.assertRaises(ResolutionError):
                    resolve_runtime_image(
                        raw,
                        image_repository=PRODUCTION_REPOSITORY,
                        index_digest=digest,
                    )

    def test_rejects_nonexact_index_contract(self) -> None:
        mutations = {
            "schema": lambda value: value.update(schemaVersion=True),
            "extra_top_level": lambda value: value.update(unexpected=True),
            "media": lambda value: value.update(
                mediaType="application/vnd.docker.distribution.manifest.list.v2+json"
            ),
            "missing_attestation": lambda value: value["manifests"].pop(),
            "extra_descriptor": lambda value: value["manifests"].append(
                dict(value["manifests"][0])
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(mutation=name):
                document = index_document()
                mutate(document)
                raw, digest = encode(document)
                with self.assertRaises(ResolutionError):
                    resolve_runtime_image(
                        raw,
                        image_repository=PRODUCTION_REPOSITORY,
                        index_digest=digest,
                    )

    def test_rejects_runtime_or_attestation_descriptor_drift(self) -> None:
        mutations = {
            "runtime_platform": lambda value: value["manifests"][0]["platform"].update(
                architecture="arm64"
            ),
            "runtime_annotation": lambda value: value["manifests"][0].update(
                annotations={"unexpected": "value"}
            ),
            "runtime_platform_field": lambda value: value["manifests"][0][
                "platform"
            ].update(variant="v1"),
            "false_size": lambda value: value["manifests"][0].update(size=True),
            "attestation_platform": lambda value: value["manifests"][1][
                "platform"
            ].update(architecture="amd64", os="linux"),
            "attestation_reference": lambda value: value["manifests"][1][
                "annotations"
            ].update(**{"vnd.docker.reference.digest": "sha256:" + "3" * 64}),
            "duplicate_digest": lambda value: value["manifests"][1].update(
                digest=RUNTIME_DIGEST
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(mutation=name):
                document = index_document()
                mutate(document)
                raw, digest = encode(document)
                with self.assertRaises(ResolutionError):
                    resolve_runtime_image(
                        raw,
                        image_repository=PRODUCTION_REPOSITORY,
                        index_digest=digest,
                    )

    def test_rejects_duplicate_json_object_keys(self) -> None:
        raw = b'{"schemaVersion":2,"schemaVersion":2}'
        digest = f"sha256:{hashlib.sha256(raw).hexdigest()}"
        with self.assertRaisesRegex(ResolutionError, "duplicate"):
            resolve_runtime_image(
                raw,
                image_repository=PRODUCTION_REPOSITORY,
                index_digest=digest,
            )


if __name__ == "__main__":
    unittest.main()
