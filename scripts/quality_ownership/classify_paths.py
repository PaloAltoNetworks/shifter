#!/usr/bin/env python3
"""Classify changed paths for the ``_quality.yml`` ``paths`` job (#1530).

This is the fail-closed execution boundary. It validates the quality-ownership
contract, resolves the changed paths, and **rejects any unclassified path
before emitting a single job-selection output** — an unowned path can no
longer slip through with an empty no-op matrix. On success it writes the same
``GITHUB_OUTPUT`` keys the downstream jobs consume.

Security posture (per the #1530 preflight): reads repository paths and fixed
git metadata only; no secret, environment dump, or workflow body is sourced;
git is invoked with fixed argv and NUL-delimited output so a crafted filename
cannot corrupt classification; output keys are the fixed contract category
names and values are ``true``/``false``/compact JSON.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from quality_ownership import contract as C  # noqa: E402

_CONTRACT_PATH = ".github/quality-path-filters.yaml"
_NULL_SHA = "0" * 40


def _changed_files(repo_root: Path) -> list[str] | None:
    """Return the changed paths, or ``None`` to signal a full-matrix run."""
    if os.environ.get("RUN_FULL_MATRIX", "false").lower() == "true":
        return None
    head = os.environ.get("DIFF_HEAD_SHA") or os.environ.get("GITHUB_SHA", "")
    base = os.environ.get("DIFF_BASE_SHA", "")
    if base and base != _NULL_SHA:
        cmd = ["git", "-C", str(repo_root), "diff", "-z", "--name-only", f"{base}...{head}"]
    else:
        cmd = ["git", "-C", str(repo_root), "diff", "-z", "--name-only", "HEAD~1", "HEAD"]
    out = subprocess.check_output(cmd, text=True)
    return [line for line in out.split("\0") if line]


def _write_outputs(outputs: dict[str, str]) -> None:
    github_output = os.environ.get("GITHUB_OUTPUT")
    if not github_output:
        # Local invocation without a GitHub runner: print for inspection.
        for key, value in outputs.items():
            print(f"{key}={value}")
        return
    with Path(github_output).open("a", encoding="utf-8") as handle:
        for key, value in outputs.items():
            handle.write(f"{key}={value}\n")


def main() -> int:
    repo_root = Path(os.environ.get("GITHUB_WORKSPACE", ".")).resolve()
    try:
        contract = C.load_contract(repo_root / _CONTRACT_PATH)
    except (C.ContractError, OSError) as exc:
        print(f"quality-ownership contract is invalid: {exc}", file=sys.stderr)
        return 1

    files = _changed_files(repo_root)
    try:
        outputs = C.compute_outputs(contract, files, run_full_matrix=files is None)
    except (C.UnknownPathError, C.ContractError) as exc:
        # Fail closed BEFORE emitting any job-selection output: an unclassified
        # path or a contradictory (ambiguous) match must never select jobs.
        print(str(exc), file=sys.stderr)
        return 1

    _write_outputs(outputs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
