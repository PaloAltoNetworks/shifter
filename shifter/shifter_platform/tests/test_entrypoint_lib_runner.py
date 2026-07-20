"""Wire the bash-based entrypoint-lib regression test into pytest.

The actual assertions live in `test_entrypoint_lib.sh` because the
subject under test is a sourced bash function (`fetch_runtime_secret`)
and the failure modes it guards against are bash-level (set -e
propagation, command-substitution exit codes). This pytest module is a
thin wrapper that runs the shell script via subprocess so the same
checks fire under the repo's pytest pre-commit hook and CI workflow,
not just when a developer remembers to run the .sh file manually.

See `test_entrypoint_lib.sh` for the test cases and the issue-#52
fail-closed contract they enforce.
"""

from __future__ import annotations

import shutil
import subprocess  # invokes a repo-local test script, not user input
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).parent / "test_entrypoint_lib.sh"


def test_entrypoint_lib_shell_suite_passes() -> None:
    """Run the bash regression suite for `fetch_runtime_secret`.

    The shell script returns 0 only when every fail-closed assertion
    passes. Stdout/stderr are surfaced via pytest's normal capture so a
    failure shows up with the exact test labels logged by the script.
    """
    assert SCRIPT_PATH.is_file(), f"missing shell test script: {SCRIPT_PATH}"

    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash not available on PATH")

    # Both inputs are repo-controlled: `bash` is resolved against PATH and
    # `SCRIPT_PATH` is fixed to this test directory. S603/S607 don't apply
    # but ruff can't see through that statically.
    result = subprocess.run(  # noqa: S603
        [bash, str(SCRIPT_PATH)],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        pytest.fail(
            "entrypoint-lib.sh fail-closed regression suite failed "
            f"(exit={result.returncode})\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
