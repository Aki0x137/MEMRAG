"""E2E: verify that each independent integration test suite is idempotent.

Each suite is executed twice in isolation against the same (running) stack
to confirm there is no persistent state bleed between runs.  The test
runner itself must be executed with ENVIRONMENT=test and all application
services reachable (i.e. inside the docker-compose test stack).

Suites covered:
  - memory-api integration tests (no external deps)
  - knowledge-ingestion mock integration tests (requires mock servers)

Usage (from repo root inside test container):
    pytest tests/e2e/test_independent_suites_idempotent.py -v
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_suite(pytest_args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a pytest sub-process and return the completed process."""
    cmd = [sys.executable, "-m", "pytest", *pytest_args, "--tb=short", "-q"]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )


def _assert_suite_passes(result: subprocess.CompletedProcess[str], label: str) -> None:
    assert result.returncode == 0, (
        f"Suite '{label}' failed (exit {result.returncode}):\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )


# ---------------------------------------------------------------------------
# Suite definitions
# ---------------------------------------------------------------------------

SUITES: list[tuple[str, list[str]]] = [
    (
        "memory-api-integration",
        ["services/memory-api/tests/integration/"],
    ),
    (
        "knowledge-ingestion-mock",
        ["services/knowledge-ingestion/tests/integration/test_mocks_integration.py"],
    ),
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("label,args", SUITES, ids=[s[0] for s in SUITES])
def test_suite_is_idempotent(label: str, args: list[str]) -> None:
    """Each suite must pass on first AND second run (no cross-run state leakage)."""
    first = _run_suite(args)
    _assert_suite_passes(first, f"{label} [run 1]")

    second = _run_suite(args)
    _assert_suite_passes(second, f"{label} [run 2]")


@pytest.mark.parametrize("label,args", SUITES, ids=[s[0] for s in SUITES])
def test_suite_passes_standalone(label: str, args: list[str]) -> None:
    """Each suite must pass when run on its own (no implicit ordering dependency)."""
    result = _run_suite(args)
    _assert_suite_passes(result, label)
