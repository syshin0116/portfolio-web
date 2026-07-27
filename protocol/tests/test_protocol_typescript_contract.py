from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import protocol_typescript_contract as typescript_contract  # noqa: E402


class TypeScriptContractGenerationTests(unittest.TestCase):
    def test_generation_covers_every_fixture_kind_with_real_generated_types(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "contract"
            report = typescript_contract.generate_contract(output)
            generated = (output / "fixture-contract.ts").read_text(encoding="utf-8")

            self.assertEqual(53, report.records)
            self.assertEqual(37, report.typed_events)
            self.assertEqual(
                {
                    "aegra_raw_event": 1,
                    "command": 5,
                    "command_response": 5,
                    "event": 36,
                    "normalized_event": 1,
                    "stream_request": 5,
                },
                report.kinds,
            )
            self.assertIn('from "./protocol.js"', generated)
            self.assertIn("satisfies EventStreamRequest", generated)
            self.assertIn("satisfies Command;", generated)
            self.assertIn(
                "satisfies CommandResponse | ErrorResponse",
                generated,
            )
            self.assertIn("satisfies Event;", generated)
            self.assertIn("satisfies AegraRawInputRequestedEvent", generated)
            self.assertEqual(
                (REPO_ROOT / "protocol/generated/typescript/protocol.ts").read_bytes(),
                (output / "protocol.ts").read_bytes(),
            )

    def test_generation_is_byte_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first"
            second = root / "second"
            typescript_contract.generate_contract(first)
            typescript_contract.generate_contract(second)
            for name in (
                "fixture-contract.ts",
                "package.json",
                "protocol.ts",
                "replay.ts",
                "tsconfig.json",
            ):
                with self.subTest(name=name):
                    self.assertEqual(
                        (first / name).read_bytes(),
                        (second / name).read_bytes(),
                    )

    def test_unknown_fixture_kind_fails_closed(self) -> None:
        with (
            tempfile.TemporaryDirectory() as fixtures_directory,
            tempfile.TemporaryDirectory() as output_directory,
        ):
            fixtures = Path(fixtures_directory)
            for source in sorted((REPO_ROOT / "protocol/fixtures").glob("*.json")):
                shutil.copyfile(source, fixtures / source.name)
            target = fixtures / "structured-error.json"
            fixture = json.loads(target.read_text(encoding="utf-8"))
            fixture["records"][0]["kind"] = "future_unreviewed_kind"
            target.write_text(json.dumps(fixture), encoding="utf-8")

            with self.assertRaisesRegex(
                typescript_contract.TypeScriptContractError,
                "unknown record kind 'future_unreviewed_kind'",
            ):
                typescript_contract.generate_contract(
                    Path(output_directory) / "contract",
                    fixtures_root=fixtures,
                )

    def test_output_inside_repository_is_rejected(self) -> None:
        output = REPO_ROOT / "protocol/tests/typescript/generated"
        with self.assertRaisesRegex(
            typescript_contract.TypeScriptContractError,
            "outside the repository",
        ):
            typescript_contract.generate_contract(output)


if __name__ == "__main__":
    unittest.main()
