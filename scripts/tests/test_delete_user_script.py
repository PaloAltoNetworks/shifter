"""Smoke tests for scripts/delete-user.sh argument handling."""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "delete-user.sh"


class DeleteUserScriptTests(unittest.TestCase):
    def test_help_exits_zero(self) -> None:
        result = subprocess.run(  # noqa: S603
            [str(SCRIPT), "--help"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("Delete a test user from Cognito and Django", result.stdout)

    def test_missing_email_exits_nonzero(self) -> None:
        result = subprocess.run(  # noqa: S603
            [str(SCRIPT)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("email argument is required", result.stderr)


if __name__ == "__main__":
    unittest.main()
