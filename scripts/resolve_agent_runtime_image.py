#!/usr/bin/env python3
"""Resolve one reviewed BuildKit OCI index to its Linux amd64 runtime manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from typing import Any

MAX_MANIFEST_BYTES = 1_048_576
OCI_INDEX_MEDIA_TYPE = "application/vnd.oci.image.index.v1+json"
OCI_MANIFEST_MEDIA_TYPE = "application/vnd.oci.image.manifest.v1+json"
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
EXPECTED_REPOSITORIES = {
    "asia-southeast1-docker.pkg.dev/festive-ally-503605-v7/agent/agent",
    "asia-southeast1-docker.pkg.dev/festive-ally-503605-v7/agent-preview/agent",
}
ATTESTATION_REFERENCE = "vnd.docker.reference.digest"
ATTESTATION_TYPE = "vnd.docker.reference.type"


class ResolutionError(RuntimeError):
    """Raised when the registry index is outside the reviewed build contract."""


def _canonical_digest(value: object) -> str:
    if not isinstance(value, str) or DIGEST_PATTERN.fullmatch(value) is None:
        raise ResolutionError("OCI descriptor digest is not canonical")
    return value


def _positive_size(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ResolutionError("OCI descriptor size is not a positive integer")
    return value


def _object_without_duplicate_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise ResolutionError("OCI index JSON contains a duplicate object key")
        document[key] = value
    return document


def _descriptor(document: object) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise ResolutionError("OCI descriptor is not an object")
    _canonical_digest(document.get("digest"))
    _positive_size(document.get("size"))
    if document.get("mediaType") != OCI_MANIFEST_MEDIA_TYPE:
        raise ResolutionError("OCI descriptor media type is not exact")
    platform = document.get("platform")
    if not isinstance(platform, dict):
        raise ResolutionError("OCI descriptor platform is not an object")
    return document


def resolve_runtime_image(
    raw_manifest: bytes,
    *,
    image_repository: str,
    index_digest: str,
) -> str:
    if image_repository not in EXPECTED_REPOSITORIES:
        raise ResolutionError("image repository is outside the isolated registries")
    _canonical_digest(index_digest)
    if not raw_manifest or len(raw_manifest) > MAX_MANIFEST_BYTES:
        raise ResolutionError("OCI index body has an invalid size")
    observed_digest = f"sha256:{hashlib.sha256(raw_manifest).hexdigest()}"
    if observed_digest != index_digest:
        raise ResolutionError("OCI index body does not match its selected digest")
    try:
        document = json.loads(
            raw_manifest,
            object_pairs_hook=_object_without_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ResolutionError("OCI index body is not valid JSON") from error
    if not isinstance(document, dict):
        raise ResolutionError("OCI index body is not an object")
    if set(document) != {"schemaVersion", "mediaType", "manifests"}:
        raise ResolutionError("OCI index fields are not exact")
    if document.get("schemaVersion") != 2 or isinstance(
        document.get("schemaVersion"), bool
    ):
        raise ResolutionError("OCI index schema version is not exact")
    if document.get("mediaType") != OCI_INDEX_MEDIA_TYPE:
        raise ResolutionError("OCI index media type is not exact")
    manifests = document.get("manifests")
    if not isinstance(manifests, list) or len(manifests) != 2:
        raise ResolutionError("OCI index must contain one runtime and one attestation")

    descriptors = [_descriptor(item) for item in manifests]
    descriptor_digests = [str(item["digest"]) for item in descriptors]
    if len(set(descriptor_digests)) != len(descriptor_digests):
        raise ResolutionError("OCI index contains duplicate descriptor digests")

    runtime = [
        item
        for item in descriptors
        if item["platform"] == {"architecture": "amd64", "os": "linux"}
    ]
    if len(runtime) != 1:
        raise ResolutionError("OCI index must contain exactly one Linux amd64 runtime")
    runtime_descriptor = runtime[0]
    if set(runtime_descriptor) != {"mediaType", "digest", "size", "platform"}:
        raise ResolutionError("runtime descriptor fields are not exact")
    if set(runtime_descriptor["platform"]) != {"architecture", "os"}:
        raise ResolutionError("runtime platform fields are not exact")
    runtime_digest = _canonical_digest(runtime_descriptor["digest"])

    attestations = [
        item
        for item in descriptors
        if item["platform"] == {"architecture": "unknown", "os": "unknown"}
    ]
    if len(attestations) != 1:
        raise ResolutionError("OCI index must contain exactly one attestation manifest")
    attestation_descriptor = attestations[0]
    if set(attestation_descriptor) != {
        "mediaType",
        "digest",
        "size",
        "platform",
        "annotations",
    }:
        raise ResolutionError("attestation descriptor fields are not exact")
    if set(attestation_descriptor["platform"]) != {"architecture", "os"}:
        raise ResolutionError("attestation platform fields are not exact")
    annotations = attestation_descriptor.get("annotations")
    if not isinstance(annotations, dict) or annotations != {
        ATTESTATION_REFERENCE: runtime_digest,
        ATTESTATION_TYPE: "attestation-manifest",
    }:
        raise ResolutionError("attestation descriptor does not bind the runtime digest")

    return f"{image_repository}@{runtime_digest}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image-repository", required=True)
    parser.add_argument("--index-digest", required=True)
    arguments = parser.parse_args()
    raw_manifest = sys.stdin.buffer.read(MAX_MANIFEST_BYTES + 1)
    try:
        image = resolve_runtime_image(
            raw_manifest,
            image_repository=arguments.image_repository,
            index_digest=arguments.index_digest,
        )
    except ResolutionError as error:
        parser.error(str(error))
    print(image)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
