#!/usr/bin/env python3
"""Build a temporary TypeScript consumer for every protocol fixture record."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import verify_protocol_upstream as upstream
import verify_protocol_codegen as codegen

REPO_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_ROOT = REPO_ROOT / "protocol"
LOCK_PATH = PROTOCOL_ROOT / "agent-protocol.lock.json"
FIXTURES_ROOT = PROTOCOL_ROOT / "fixtures"
TYPESCRIPT_ROOT = PROTOCOL_ROOT / "tests/typescript"
GENERATED_BINDING = PROTOCOL_ROOT / "generated/typescript/protocol.ts"
TYPESCRIPT_VERSION = "5.9.3"
NODE_VERSION = "24.19.0"
EXPECTED_REPLAY_OUTPUT = (
    "typescript protocol fixtures ok: 53 records, 37 typed events, 13 shapes"
)
RECORD_TYPES = {
    "stream_request": "EventStreamRequest",
    "command": "Command",
    "command_response": "CommandResponse | ErrorResponse",
    "event": "Event",
    "normalized_event": "Event",
    "aegra_raw_event": "AegraRawInputRequestedEvent",
}
COPIED_SOURCES = {
    "package.json": TYPESCRIPT_ROOT / "package.json",
    "protocol.ts": GENERATED_BINDING,
    "replay.ts": TYPESCRIPT_ROOT / "replay.ts",
    "tsconfig.json": TYPESCRIPT_ROOT / "tsconfig.json",
}


class TypeScriptContractError(RuntimeError):
    """Fixture literals cannot be compiled against the locked TS binding."""


@dataclass(frozen=True)
class TypeScriptContractReport:
    records: int
    typed_events: int
    kinds: dict[str, int]


def _safe_output(path: Path) -> Path:
    if not path.is_absolute():
        raise TypeScriptContractError("output directory must be an absolute path")
    if path.is_symlink():
        raise TypeScriptContractError("output directory must not be a symlink")
    resolved = path.resolve()
    if resolved == REPO_ROOT or resolved.is_relative_to(REPO_ROOT):
        raise TypeScriptContractError(
            f"output directory must be outside the repository: {resolved}"
        )
    if resolved.exists():
        if not resolved.is_dir() or any(resolved.iterdir()):
            raise TypeScriptContractError(
                f"output directory must be absent or empty: {resolved}"
            )
    else:
        try:
            resolved.mkdir(parents=True)
        except OSError as exc:
            raise TypeScriptContractError(
                f"cannot create output directory {resolved}: {exc}"
            ) from exc
    return resolved


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TypeScriptContractError(f"cannot read {label} {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise TypeScriptContractError(f"{label} must be an object: {path}")
    return payload


def _typescript_literal(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=False,
    )


def _fixture_paths(fixtures_root: Path) -> list[Path]:
    paths = sorted(fixtures_root.glob("*.json"))
    if not paths:
        raise TypeScriptContractError(f"no protocol fixtures found in {fixtures_root}")
    return paths


def generate_contract(
    output_dir: Path,
    *,
    fixtures_root: Path = FIXTURES_ROOT,
) -> TypeScriptContractReport:
    """Write a complete, temporary TypeScript compile/replay workspace."""
    output = _safe_output(output_dir)
    lock = upstream.load_lock(LOCK_PATH)
    upstream.locked_artifacts(lock)
    protocol_commit = lock["protocol"]["commit"]

    lines = [
        (
            "import type { Command, CommandResponse, ErrorResponse, Event, "
            'EventStreamRequest } from "./protocol.js";'
        ),
        "",
        "export type AegraRawInputRequestedEvent = {",
        '  type: "event";',
        "  event_id: string;",
        "  seq: number;",
        '  method: "input.requested";',
        "  params: {",
        "    namespace: string[];",
        "    timestamp: number;",
        "    data: { interrupt_id: string; value: unknown };",
        "  };",
        "};",
        "",
    ]
    kinds: Counter[str] = Counter()
    variables: dict[str, list[str]] = {kind: [] for kind in RECORD_TYPES}
    translations: dict[str, dict[str, str]] = {}
    record_number = 0

    for fixture_path in _fixture_paths(fixtures_root):
        fixture = _load_json_object(fixture_path, label="fixture")
        if fixture.get("fixture_version") != 1:
            raise TypeScriptContractError(
                f"{fixture_path}: unsupported fixture_version"
            )
        if fixture.get("protocol_commit") != protocol_commit:
            raise TypeScriptContractError(
                f"{fixture_path}: protocol_commit differs from strict lock"
            )
        if fixture.get("wire_profile") != "official-generated-snake-case":
            raise TypeScriptContractError(
                f"{fixture_path}: fixture wire profile differs from generated binding"
            )
        records = fixture.get("records")
        if not isinstance(records, list) or not records:
            raise TypeScriptContractError(
                f"{fixture_path}: records must be a non-empty array"
            )
        for fixture_index, record in enumerate(records):
            if not isinstance(record, dict):
                raise TypeScriptContractError(
                    f"{fixture_path}:record[{fixture_index}] must be an object"
                )
            kind = record.get("kind")
            if kind not in RECORD_TYPES:
                raise TypeScriptContractError(
                    f"{fixture_path}:record[{fixture_index}]: "
                    f"unknown record kind {kind!r}"
                )
            payload = record.get("payload")
            if not isinstance(payload, dict):
                raise TypeScriptContractError(
                    f"{fixture_path}:record[{fixture_index}]: payload must be an object"
                )
            variable = f"r{record_number}"
            record_number += 1
            kinds[kind] += 1
            variables[kind].append(variable)
            lines.append(
                f"const {variable} = {_typescript_literal(payload)} "
                f"as const satisfies {RECORD_TYPES[kind]};"
            )

            if kind in {"aegra_raw_event", "normalized_event"}:
                translation_id = record.get("translation_id")
                if not isinstance(translation_id, str) or not translation_id:
                    raise TypeScriptContractError(
                        f"{fixture_path}:record[{fixture_index}]: "
                        f"{kind} requires translation_id"
                    )
                pair = translations.setdefault(translation_id, {})
                if kind in pair:
                    raise TypeScriptContractError(
                        f"{fixture_path}: duplicate {kind} translation "
                        f"{translation_id!r}"
                    )
                pair[kind] = variable

    lines.append("")
    export_names = {
        "stream_request": "stream_requests",
        "command": "commands",
        "command_response": "command_responses",
        "event": "events",
        "normalized_event": "normalized_events",
        "aegra_raw_event": "aegra_raw_events",
    }
    for kind, export_name in export_names.items():
        lines.append(
            f"export const {export_name} = [{','.join(variables[kind])}] as const;"
        )

    lines.extend(["", "export const aegra_translation_pairs = ["])
    for translation_id, pair in sorted(translations.items()):
        if set(pair) != {"aegra_raw_event", "normalized_event"}:
            raise TypeScriptContractError(
                f"Aegra translation {translation_id!r} must have one raw "
                "and one normalized event"
            )
        lines.append(
            "  { "
            f"translation_id: {_typescript_literal(translation_id)}, "
            f"raw: {pair['aegra_raw_event']}, "
            f"normalized: {pair['normalized_event']} "
            "},"
        )
    lines.extend(["] as const;", ""])

    try:
        (output / "fixture-contract.ts").write_text(
            "\n".join(lines),
            encoding="utf-8",
            newline="\n",
        )
        for output_name, source in COPIED_SOURCES.items():
            if source.is_symlink() or not source.is_file():
                raise TypeScriptContractError(
                    f"contract source is missing or is a symlink: {source}"
                )
            shutil.copyfile(source, output / output_name)
    except OSError as exc:
        raise TypeScriptContractError(
            f"cannot write TypeScript contract workspace {output}: {exc}"
        ) from exc

    return TypeScriptContractReport(
        records=sum(kinds.values()),
        typed_events=kinds["event"] + kinds["normalized_event"],
        kinds=dict(sorted(kinds.items())),
    )


def compile_and_replay(source_dir: Path, *, compiler_root: Path) -> str:
    """Compile and execute one generated fixture workspace with pinned tools."""
    source = source_dir.resolve()
    if (
        not source_dir.is_absolute()
        or source_dir.is_symlink()
        or source == REPO_ROOT
        or source.is_relative_to(REPO_ROOT)
        or not source.is_dir()
    ):
        raise TypeScriptContractError(
            f"compile source must be an external real directory: {source_dir}"
        )
    for name in COPIED_SOURCES:
        path = source / name
        if path.is_symlink() or not path.is_file():
            raise TypeScriptContractError(
                f"generated contract source is missing or is a symlink: {path}"
            )
    fixture_contract = source / "fixture-contract.ts"
    if fixture_contract.is_symlink() or not fixture_contract.is_file():
        raise TypeScriptContractError(
            f"generated fixture contract is missing or is a symlink: {fixture_contract}"
        )

    compiler = compiler_root.resolve()
    if compiler != TYPESCRIPT_ROOT.resolve():
        raise TypeScriptContractError(
            f"compiler root must be the locked contract package: {compiler_root}"
        )
    manifest_path = compiler / "node_modules/typescript/package.json"
    manifest = _load_json_object(manifest_path, label="installed TypeScript manifest")
    if (
        manifest.get("name") != "typescript"
        or manifest.get("version") != TYPESCRIPT_VERSION
    ):
        raise TypeScriptContractError(
            "installed TypeScript package differs from the locked 5.9.3 compiler"
        )
    tsc = (compiler / "node_modules/.bin/tsc").resolve()
    if not tsc.is_file() or not tsc.is_relative_to(compiler):
        raise TypeScriptContractError(
            f"TypeScript compiler escapes its locked package root: {tsc}"
        )

    env = os.environ.copy()
    for key in list(env):
        if key.upper() == "NODE_OPTIONS":
            del env[key]
    env["CI"] = "true"
    node = codegen._resolve_executable("node")
    codegen.require_version(
        "node",
        actual=codegen._run(
            [str(node), "--version"],
            cwd=source,
            env=env,
            timeout=codegen.COMMAND_TIMEOUT_SECONDS,
        ).decode(),
        expected=NODE_VERSION,
        prefix="v",
    )
    codegen.require_version(
        "typescript",
        actual=codegen._run(
            [str(tsc), "--version"],
            cwd=source,
            env=env,
            timeout=codegen.COMMAND_TIMEOUT_SECONDS,
        ).decode(),
        expected=TYPESCRIPT_VERSION,
        prefix="Version ",
    )
    codegen._run(
        [str(tsc), "--project", str(source / "tsconfig.json")],
        cwd=source,
        env=env,
        timeout=codegen.COMMAND_TIMEOUT_SECONDS,
    )
    replay = source / "dist/replay.js"
    if replay.is_symlink() or not replay.is_file():
        raise TypeScriptContractError(f"compiled replay output is missing: {replay}")
    output = (
        codegen._run(
            [str(node), str(replay)],
            cwd=source,
            env=env,
            timeout=codegen.COMMAND_TIMEOUT_SECONDS,
        )
        .decode()
        .strip()
    )
    if output != EXPECTED_REPLAY_OUTPUT:
        raise TypeScriptContractError(
            f"TypeScript replay output differs: expected "
            f"{EXPECTED_REPLAY_OUTPUT!r}, got {output!r}"
        )
    return output


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--compile-with",
        type=Path,
        help="compile/replay with the installed dedicated TypeScript package",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = generate_contract(args.output_dir)
        replay_output = (
            compile_and_replay(
                args.output_dir,
                compiler_root=args.compile_with,
            )
            if args.compile_with is not None
            else None
        )
    except (
        codegen.CodegenVerificationError,
        TypeScriptContractError,
        upstream.UpstreamVerificationError,
    ) as exc:
        print(f"typescript protocol contract generation failed: {exc}", file=sys.stderr)
        return 1
    print(
        "generated TypeScript protocol contract: "
        f"{report.records} records, {report.typed_events} typed events"
    )
    for kind, count in report.kinds.items():
        print(f"- {kind}: {count}")
    if replay_output is not None:
        print(replay_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
