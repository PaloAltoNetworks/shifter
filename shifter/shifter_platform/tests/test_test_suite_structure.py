"""Structural checks for platform test-suite maintainability."""

from __future__ import annotations

import ast
from pathlib import Path

MAX_TEST_CLASS_LINES = 300
MAX_TEST_MODULE_LINES = 800
TEST_ROOT = Path(__file__).resolve().parent


def _python_test_files() -> list[Path]:
    return sorted(
        path for path in TEST_ROOT.rglob("*.py") if "__pycache__" not in path.parts and path.name.startswith("test_")
    )


def test_platform_test_modules_stay_behavior_scoped():
    oversized_modules = [
        f"{path.relative_to(TEST_ROOT)} ({len(path.read_text().splitlines())} lines)"
        for path in _python_test_files()
        if len(path.read_text().splitlines()) > MAX_TEST_MODULE_LINES
    ]

    assert not oversized_modules, "Split oversized test modules by behavior/API boundary: " + ", ".join(
        oversized_modules
    )


def test_platform_test_classes_stay_scenario_scoped():
    oversized_classes: list[str] = []

    for path in _python_test_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef) or not node.name.startswith("Test"):
                continue
            line_count = (node.end_lineno or node.lineno) - node.lineno + 1
            if line_count > MAX_TEST_CLASS_LINES:
                oversized_classes.append(f"{path.relative_to(TEST_ROOT)}::{node.name} ({line_count} lines)")

    assert not oversized_classes, "Split oversized test classes by scenario: " + ", ".join(oversized_classes)
