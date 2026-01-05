"""Pytest configuration for bootstrap tests."""

import sys
from unittest.mock import MagicMock

import pytest


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
