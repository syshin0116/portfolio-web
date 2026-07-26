#!/usr/bin/env python3
"""Build the deterministic Nuartz-published corpus mirror."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENT_SRC = REPO_ROOT / "agent" / "src"
if str(AGENT_SRC) not in sys.path:
    sys.path.insert(0, str(AGENT_SRC))

from agent.retrieval.corpus_build import CorpusBuildError, build_index  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--content-root",
        type=Path,
        default=REPO_ROOT / "content",
        help="source content/ directory",
    )
    parser.add_argument(
        "--policy",
        type=Path,
        default=REPO_ROOT / "agent" / "corpus-policy.toml",
        help="owner-reviewed publication policy",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "agent" / ".index",
        help="generated corpus index directory",
    )
    parser.add_argument(
        "--expect-document-count",
        type=int,
        help="fail if the published mirror does not contain this exact count",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = build_index(
            content_root=args.content_root,
            policy_path=args.policy,
            output_root=args.output,
        )
    except CorpusBuildError as exc:
        print(f"corpus build failed: {exc}", file=sys.stderr)
        return 1
    if (
        args.expect_document_count is not None
        and report.document_count != args.expect_document_count
    ):
        print(
            "corpus build failed: expected "
            f"{args.expect_document_count} published documents, "
            f"built {report.document_count}",
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(
            {
                "corpus_fingerprint": report.fingerprint,
                "document_count": report.document_count,
                "output": str(report.output_root),
                "source_markdown_count": report.source_markdown_count,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
