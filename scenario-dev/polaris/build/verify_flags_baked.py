#!/usr/bin/env python3
"""Bake-time smoke: verify generated Polaris artifacts carry their flags.

For each (artifact, challenge id) in ``BAKED_FLAG_ARTIFACTS`` this checks
that the CTFd board's static flag for that challenge appears in the
rendered artifact, and exits non-zero on any miss — so a clean-checkout
rebake that drops a flag fails the bake instead of shipping a flagless
range (regression #619, the "Follow the Money" Ottawa bug).

The board is parsed here independently of ``build_pdfs.py`` on purpose: a
verifier that reused the generator's flag-resolution code could share its
bug. This script stays self-contained.

Usage:
    verify_flags_baked.py <ctfd-challenges.json> <artifact-root>
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

# Generated artifact (path relative to <artifact-root>) -> CTFd challenge
# id whose static flag must appear in the rendered artifact. Add a row
# when a new generated artifact is made to carry a flag.
BAKED_FLAG_ARTIFACTS = {
    "internal/boreas-annual-2025.pdf": 6,
}


def static_flag(board, challenge_id):
    """Return the single static flag content for a CTFd challenge id."""
    matches = [
        c for c in board.get("challenges", []) if c.get("id") == challenge_id
    ]
    if len(matches) != 1:
        raise ValueError(
            f"challenge id {challenge_id}: expected exactly one board entry, "
            f"found {len(matches)}"
        )
    static = [f for f in matches[0].get("flags", []) if f.get("type") == "static"]
    if len(static) != 1:
        raise ValueError(
            f"challenge id {challenge_id}: expected exactly one static flag, "
            f"found {len(static)}"
        )
    content = static[0].get("content")
    if not content:
        raise ValueError(f"challenge id {challenge_id}: static flag has no content")
    return content


def artifact_text(path):
    """Extract searchable text from a rendered artifact."""
    if path.suffix.lower() == ".pdf":
        pdftotext = shutil.which("pdftotext")
        if pdftotext:
            result = subprocess.run(
                [pdftotext, str(path), "-"],
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout
        # Poppler unavailable: fall back to a raw byte scan. PDF text is
        # not guaranteed contiguous in raw bytes, but a literal flag drawn
        # as a single string usually survives — good enough for a smoke.
        return path.read_bytes().decode("latin-1", errors="ignore")
    return path.read_text(encoding="utf-8", errors="ignore")


def verify(challenges_path, artifact_root, artifacts=None):
    """Return a list of miss descriptions; empty list means every flag is baked."""
    board = json.loads(Path(challenges_path).read_text(encoding="utf-8"))
    artifact_root = Path(artifact_root)
    artifacts = BAKED_FLAG_ARTIFACTS if artifacts is None else artifacts

    misses = []
    for rel, challenge_id in sorted(artifacts.items()):
        flag = static_flag(board, challenge_id)
        artifact = artifact_root / rel
        if not artifact.is_file():
            misses.append(f"{rel}: artifact not found")
            print(f"  MISS {rel}: file not found")
            continue
        if flag in artifact_text(artifact):
            print(f"  OK   {rel}: challenge {challenge_id} flag present")
        else:
            misses.append(f"{rel}: challenge {challenge_id} flag absent")
            print(f"  MISS {rel}: challenge {challenge_id} flag {flag} absent")
    return misses


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print(__doc__)
        return 2
    misses = verify(argv[0], argv[1])
    if misses:
        print(
            f"\nbaked-flag verification FAILED: {len(misses)} miss(es)",
            file=sys.stderr,
        )
        return 1
    print(
        f"\nbaked-flag verification PASSED: {len(BAKED_FLAG_ARTIFACTS)} artifact(s)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
