#!/usr/bin/env python3
"""pre-commit commit-msg hook: reject prohibited AI/agent attribution."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from agent_attribution import find_agent_attribution_matches


def _read_commit_message(raw_path: str) -> str:
    """Read the commit-message file named by the hook argument, safely.

    git invokes the ``commit-msg`` hook with the path to the message file it
    just wrote inside the repository's git directory (e.g. ``COMMIT_EDITMSG``).
    The argument is therefore attacker-influenceable input, so it is resolved
    and confirmed to sit inside that git directory before being read. This
    keeps a crafted path from pulling in an unrelated file on disk
    (pythonsecurity:S8707) while still handling linked worktrees, whose git dir
    ``git rev-parse --git-dir`` reports authoritatively.
    """
    git_dir = Path(
        subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    ).resolve()

    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    resolved = candidate.resolve()

    if resolved != git_dir and git_dir not in resolved.parents:
        raise ValueError(
            f"refusing to read commit-message file outside the git directory: {raw_path}"
        )
    if not resolved.is_file():
        raise FileNotFoundError(f"commit-message file not found: {raw_path}")

    return resolved.read_text(encoding="utf-8")


def main() -> int:
    """Fail the commit when its message carries prohibited AI/agent attribution."""
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <commit-msg-file>", file=sys.stderr)
        return 2

    text = _read_commit_message(sys.argv[1])
    matches = find_agent_attribution_matches(text)
    if not matches:
        return 0

    print(
        "Commit message contains prohibited AI/agent attribution. Remove it and retry.",
        file=sys.stderr,
    )
    for match in matches:
        print(f"  - {match.rule}: {match.excerpt}", file=sys.stderr)
    print(
        "Disable Cursor commit/PR attribution in ~/.cursor/cli-config.json "
        "(project .cursor/cli.json cannot set attribution; see Cursor CLI docs).",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
