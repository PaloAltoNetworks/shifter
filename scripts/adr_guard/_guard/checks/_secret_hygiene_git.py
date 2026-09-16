"""Shared `git ls-files` containment helper for the secret-hygiene checks.

Split out of ``secret_hygiene.py`` so both the generated-artifact and the
secret-env scans share one source-control enumeration; the public name is
re-imported by ``secret_hygiene.py`` so the package surface is unchanged.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


def _git_ls_files_stdout(repo_root: Path, roots: tuple[str, ...]) -> bytes | None:
    """Return raw `git ls-files` stdout for ``roots``, or None when unusable.

    ``None`` means "no usable git index" — ``repo_root`` is not a git working
    tree, `git` is unavailable or hung, or the command failed. Callers fall
    back to a filesystem walk in that case (the synthetic-tmpdir test path).

    `--cached` enumerates tracked files; `--others --exclude-standard` adds
    untracked files NOT ignored by gitignore — that captures `git add -f`
    candidates that bypassed .gitignore and would otherwise be invisible to a
    tracked-only check until they hit the index.
    """
    if not (repo_root / ".git").exists():
        return None
    cmd = [
        "git",
        "-C",
        str(repo_root),
        "ls-files",
        "-z",
        "--cached",
        "--others",
        "--exclude-standard",
        "--",
        *roots,
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


__all__ = ["_git_ls_files_stdout"]
