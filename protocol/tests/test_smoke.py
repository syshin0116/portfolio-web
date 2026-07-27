from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import smoke
from protocol_contract import load_lock


class _FakeResponse:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class SmokeArgumentTests(unittest.TestCase):
    def test_default_run_is_offline(self) -> None:
        with (
            patch.object(smoke.asyncio, "run") as run,
            redirect_stdout(io.StringIO()),
        ):
            result = smoke.main([])
        self.assertEqual(0, result)
        run.assert_not_called()

    def test_live_url_requires_assistant(self) -> None:
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            smoke.parse_args(["--base-url", "http://127.0.0.1:8000"])

    def test_aegra_profile_uses_verified_runtime_path(self) -> None:
        profile = smoke._profiles(load_lock())["aegra-0.9.24"]
        self.assertEqual(
            "/threads/{thread_id}/stream/events",
            profile.stream_path,
        )
        self.assertEqual("sequence", profile.sse_id)


class SSEParserTests(unittest.IsolatedAsyncioTestCase):
    async def test_multiline_data_and_comment(self) -> None:
        response = _FakeResponse(
            [
                ": keepalive",
                "id: evt-1",
                "event: lifecycle",
                'data: {"type":"event",',
                'data: "method":"lifecycle"}',
                "",
            ]
        )
        frames = [frame async for frame in smoke.iter_sse_frames(response)]
        self.assertEqual(1, len(frames))
        self.assertEqual("evt-1", frames[0].event_id)
        self.assertEqual("lifecycle", frames[0].event)
        self.assertEqual("event", frames[0].data["type"])


if __name__ == "__main__":
    unittest.main()
