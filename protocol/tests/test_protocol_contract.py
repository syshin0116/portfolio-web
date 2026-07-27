from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from protocol_contract import (  # noqa: E402
    ContractError,
    LOCK_PATH,
    load_lock,
    normalize_aegra_event,
    validate_all,
    validate_fixture,
)


class ProtocolContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lock = load_lock()

    def _fixture(self, name: str) -> dict:
        path = REPO_ROOT / "protocol/fixtures" / name
        return json.loads(path.read_text(encoding="utf-8"))

    def _validate_mutation(self, fixture: dict) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.json"
            path.write_text(
                json.dumps(fixture, ensure_ascii=False),
                encoding="utf-8",
            )
            validate_fixture(path, protocol_commit=self.lock["protocol"]["commit"])

    def test_full_offline_suite_has_required_coverage(self) -> None:
        reports = validate_all()
        self.assertEqual(7, len(reports))
        self.assertGreater(sum(report.events for report in reports), 30)

    def test_inspection_fixture_is_live_only_retrieval_not_durable_replay(self) -> None:
        fixture = self._fixture("inspection-events-v1.json")
        self.assertNotIn("replay", fixture["expectations"])
        self.assertEqual(
            {"durable_replay": False, "mode": "live-run-only"},
            fixture["expectations"]["delivery"],
        )
        self.assertEqual(1, len(fixture["records"]))
        event = fixture["records"][0]["payload"]
        self.assertEqual("custom", event["method"])
        self.assertEqual(
            "syshin.rag.inspection.v1",
            event["params"]["data"]["name"],
        )
        self.assertEqual(
            "retrieval",
            event["params"]["data"]["payload"]["kind"],
        )

    def test_vendored_generated_bindings_match_locked_hashes(self) -> None:
        protocol = self.lock["protocol"]
        self.assertEqual(
            "0ff7cd3962e8b4b3e347b76203be7dfeba003928",
            protocol["commit"],
        )
        self.assertEqual(
            "official-generated-snake-case",
            protocol["bindingWireProfile"]["name"],
        )
        self.assertTrue(LOCK_PATH.is_file())

    def test_aegra_path_divergence_is_not_hidden(self) -> None:
        self.assertEqual(
            "POST /threads/{thread_id}/stream",
            self.lock["protocol"]["transport"]["sse"],
        )
        self.assertEqual(
            "POST /threads/{thread_id}/stream/events",
            self.lock["aegra"]["runtimeTransport"]["sse"],
        )
        matrix = self.lock["aegra"]["supportMatrix"]
        path_entry = next(
            item for item in matrix if item["capability"] == "Thread-centric SSE stream"
        )
        self.assertEqual("path-divergence", path_entry["status"])
        self.assertEqual(
            "protocol/fixtures/aegra-dialect-translation.json",
            self.lock["aegra"]["dialectTranslation"]["fixture"],
        )

    def test_generated_hitl_binding_rejects_aegra_value_alias(self) -> None:
        fixture = self._fixture("hitl-command-response.json")
        interrupt = next(
            record
            for record in fixture["records"]
            if record["kind"] == "event"
            and record["payload"]["method"] == "input.requested"
        )
        data = interrupt["payload"]["params"]["data"]
        data["value"] = data.pop("payload")
        with self.assertRaisesRegex(ContractError, "locked generated binding"):
            self._validate_mutation(fixture)

    def test_aegra_translation_fixture_keeps_raw_and_normalized_wire(self) -> None:
        fixture = self._fixture("aegra-dialect-translation.json")
        raw = next(
            record
            for record in fixture["records"]
            if record["kind"] == "aegra_raw_event"
        )["payload"]
        expected = next(
            record
            for record in fixture["records"]
            if record["kind"] == "normalized_event"
        )["payload"]
        self.assertIn("value", raw["params"]["data"])
        self.assertNotIn("payload", raw["params"]["data"])
        self.assertEqual(expected, normalize_aegra_event(raw))
        self.assertIn("value", raw["params"]["data"], "normalizer mutated raw wire")

    def test_aegra_translation_rejects_ambiguous_hitl_payload(self) -> None:
        fixture = self._fixture("aegra-dialect-translation.json")
        raw = next(
            record
            for record in fixture["records"]
            if record["kind"] == "aegra_raw_event"
        )["payload"]
        raw["params"]["data"]["payload"] = {"duplicate": True}
        with self.assertRaisesRegex(ContractError, "ambiguous"):
            normalize_aegra_event(raw)

    def test_aegra_translation_pair_cannot_drift(self) -> None:
        fixture = self._fixture("aegra-dialect-translation.json")
        normalized = next(
            record
            for record in fixture["records"]
            if record["kind"] == "normalized_event"
        )
        normalized["payload"]["params"]["data"]["payload"]["tool_name"] = "other"
        with self.assertRaisesRegex(ContractError, "differs from normalized fixture"):
            self._validate_mutation(fixture)

    def test_message_delta_without_active_block_fails(self) -> None:
        fixture = self._fixture("content-tool-run.json")
        fixture["records"] = [
            record
            for record in fixture["records"]
            if not (
                record["kind"] == "event"
                and record["payload"]["event_id"] == "evt-tool-003"
            )
        ]
        with self.assertRaisesRegex(ContractError, "content delta"):
            self._validate_mutation(fixture)

    def test_reconnect_at_old_cursor_fails(self) -> None:
        fixture = self._fixture("replay-disconnect.json")
        fixture = copy.deepcopy(fixture)
        resumed = next(
            record
            for record in fixture["records"]
            if record["kind"] == "stream_request"
            and record.get("connection") == "resumed"
        )
        resumed["payload"]["since"] = 103
        with self.assertRaisesRegex(ContractError, "replay cursor"):
            self._validate_mutation(fixture)

    def test_replay_duplicate_visible_delta_fails(self) -> None:
        fixture = self._fixture("replay-disconnect.json")
        resumed_delta = next(
            record
            for record in fixture["records"]
            if record["kind"] == "event"
            and record["payload"]["event_id"] == "evt-replay-105"
        )
        resumed_delta["payload"]["params"]["data"]["delta"]["text"] = "연결연결"
        with self.assertRaisesRegex(ContractError, "assembled text"):
            self._validate_mutation(fixture)

    def test_fixture_commit_drift_fails(self) -> None:
        fixture = self._fixture("structured-error.json")
        fixture["protocol_commit"] = "0" * 40
        with self.assertRaisesRegex(ContractError, "differs from lock"):
            self._validate_mutation(fixture)


if __name__ == "__main__":
    unittest.main()
