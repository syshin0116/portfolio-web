"""The PostgreSQL integration suite must not silently skip in CI."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

POSTGRES_TEST_MODULE = (
    Path(__file__).resolve().parents[1] / "integration_tests" / "test_aegra_postgres.py"
)


def test_ci_without_postgres_url_refuses_to_collect_integration_suite():
    env = {
        **os.environ,
        "CI": "true",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    env.pop("AEGRA_POSTGRES_TEST_URL", None)

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import runpy; runpy.run_path({str(POSTGRES_TEST_MODULE)!r})",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "PostgreSQL integration may not skip" in result.stderr
