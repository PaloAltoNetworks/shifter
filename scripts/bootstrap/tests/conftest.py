"""Pytest configuration for bootstrap tests."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Get the real repo root to protect it
_REAL_REPO_ROOT = Path(__file__).parent.parent.parent.parent.resolve()


@pytest.fixture(autouse=True)
def protect_real_files(monkeypatch):
    """SAFETY: Prevent tests from writing to real repository files.

    This autouse fixture intercepts Path.write_text() calls and raises
    an error if any test tries to write to the real repository.
    """
    original_write_text = Path.write_text

    def safe_write_text(self, *args, **kwargs):
        resolved = self.resolve()
        # Block writes to the real repo (but allow writes to /tmp, etc.)
        if str(resolved).startswith(str(_REAL_REPO_ROOT)):
            raise RuntimeError(
                f"TEST SAFETY: Blocked write to real repo file: {resolved}\n"
                f"Tests must mock get_repo_root() or use tmp_path fixtures."
            )
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", safe_write_text)


@pytest.fixture
def mock_deploy(monkeypatch):
    """Mock the deploy module for runner.py tests.

    This fixture creates a mock deploy module and patches it into sys.modules
    before the test runs, then cleans up after.
    """
    mock = MagicMock()
    mock.Colors = MagicMock()
    mock.Colors.BOLD = ""
    mock.Colors.END = ""
    mock.Colors.GREEN = ""
    mock.Colors.YELLOW = ""
    mock.Colors.CYAN = ""
    mock.Colors.RED = ""
    mock.code_block = MagicMock()
    mock.confirm = MagicMock(return_value=True)
    mock.confirm_or_manual = MagicMock(return_value="yes")
    mock.error = MagicMock()
    mock.header = MagicMock()
    mock.info = MagicMock()
    mock.run_cmd = MagicMock()
    mock.subheader = MagicMock()
    mock.success = MagicMock()
    mock.wait_for_user = MagicMock()
    mock.warn = MagicMock()

    # Patch
    monkeypatch.setitem(sys.modules, "deploy", mock)

    yield mock

    # Cleanup: remove runner module so it can be reimported fresh
    if "runner" in sys.modules:
        del sys.modules["runner"]
