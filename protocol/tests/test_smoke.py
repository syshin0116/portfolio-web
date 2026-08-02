from __future__ import annotations

import io
import argparse
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import smoke  # noqa: E402
from protocol_contract import load_lock  # noqa: E402


class _FakeResponse:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    async def aiter_lines(self):
        for line in self._lines:
            yield line


REFLECTED_TOKEN = "reflected-secret-token-that-must-never-be-logged"


class _ReflectingLiveSmoke:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def run_turn(self, **_kwargs: object) -> smoke.TurnResult:
        return smoke.TurnResult(
            events=[{"server": REFLECTED_TOKEN}],
            last_seq=1,
            coverage=frozenset({"tool_lifecycle"}),
            visible_text=REFLECTED_TOKEN,
            hitl_responses=0,
        )

    async def assert_thread_reload(self, _thread_id: str) -> None:
        return None

    async def assert_structured_error(self, _thread_id: str) -> None:
        return None


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
        profile = smoke._profiles(load_lock())["aegra-0.9.25"]
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

    async def test_invalid_authenticated_sse_never_echoes_server_data(self) -> None:
        response = _FakeResponse([f"data: {REFLECTED_TOKEN}", ""])

        with self.assertRaises(smoke.SmokeError) as raised:
            _ = [frame async for frame in smoke.iter_sse_frames(response)]

        self.assertNotIn(REFLECTED_TOKEN, str(raised.exception))


class AuthenticatedLogRedactionTests(unittest.IsolatedAsyncioTestCase):
    async def test_authenticated_success_never_prints_server_visible_text(self) -> None:
        args = argparse.Namespace(
            profile="aegra-0.9.25",
            token_env="TEST_LIVE_TOKEN",
            hitl_response='{"action":"approve"}',
            base_url="https://agent.example.invalid",
            assistant_id="agent",
            timeout=1.0,
            turn_one="one",
            turn_two="two",
            allow_no_tool=False,
            require_nested=False,
            require_hitl=False,
        )
        with (
            patch.dict(os.environ, {"TEST_LIVE_TOKEN": REFLECTED_TOKEN}),
            patch.object(smoke, "LiveSmoke", return_value=_ReflectingLiveSmoke()),
            redirect_stdout(output := io.StringIO()),
        ):
            await smoke.run_live(args, load_lock())

        self.assertIn("live AP v2 smoke ok", output.getvalue())
        self.assertNotIn(REFLECTED_TOKEN, output.getvalue())

    def test_authenticated_failure_never_prints_reflected_exception_text(self) -> None:
        with (
            patch.dict(os.environ, {"TEST_LIVE_TOKEN": REFLECTED_TOKEN}),
            patch.object(
                smoke,
                "run_live",
                side_effect=smoke.SmokeError(REFLECTED_TOKEN),
            ),
            redirect_stdout(io.StringIO()),
            redirect_stderr(error := io.StringIO()),
        ):
            result = smoke.main(
                [
                    "--base-url",
                    "https://agent.example.invalid",
                    "--assistant-id",
                    "agent",
                    "--token-env",
                    "TEST_LIVE_TOKEN",
                ]
            )

        self.assertEqual(1, result)
        self.assertIn("details suppressed", error.getvalue())
        self.assertNotIn(REFLECTED_TOKEN, error.getvalue())

    def test_authenticated_unexpected_exception_never_prints_reflected_text(
        self,
    ) -> None:
        with (
            patch.dict(os.environ, {"TEST_LIVE_TOKEN": REFLECTED_TOKEN}),
            patch.object(
                smoke,
                "run_live",
                side_effect=ValueError(REFLECTED_TOKEN),
            ),
            redirect_stdout(io.StringIO()),
            redirect_stderr(error := io.StringIO()),
        ):
            result = smoke.main(
                [
                    "--base-url",
                    "https://agent.example.invalid",
                    "--assistant-id",
                    "agent",
                    "--token-env",
                    "TEST_LIVE_TOKEN",
                ]
            )

        self.assertEqual(1, result)
        self.assertIn("details suppressed", error.getvalue())
        self.assertNotIn(REFLECTED_TOKEN, error.getvalue())


if __name__ == "__main__":
    unittest.main()
