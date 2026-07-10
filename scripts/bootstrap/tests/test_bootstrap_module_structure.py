"""Structural checks for the bootstrap deployment refactor."""

import ast
from pathlib import Path

BOOTSTRAP_DIR = Path(__file__).resolve().parents[1]


def _top_level_defs(path: Path) -> list[ast.AST]:
    module = ast.parse(path.read_text())
    return [node for node in module.body if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)]


def test_deploy_entrypoint_is_a_facade_over_focused_modules():
    expected_modules = {
        "aws_bootstrap.py",
        "bootstrap_core.py",
        "cli.py",
        "gcp_control_plane.py",
        "gdc_cluster.py",
        "terraform_deploy.py",
        "walkthrough.py",
    }

    missing = [name for name in sorted(expected_modules) if not (BOOTSTRAP_DIR / name).exists()]
    assert missing == []

    deploy_path = BOOTSTRAP_DIR / "deploy.py"
    deploy_lines = deploy_path.read_text().splitlines()
    assert len(deploy_lines) < 300

    oversized_defs = [
        f"{node.name}:{node.end_lineno - node.lineno + 1}"
        for node in _top_level_defs(deploy_path)
        if node.end_lineno and node.end_lineno - node.lineno + 1 > 100
    ]
    assert oversized_defs == []


def test_bootstrap_tests_are_split_by_behavior():
    assert not (BOOTSTRAP_DIR / "tests" / "test_deploy.py").exists()
