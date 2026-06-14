"""Structural tests for the provisioner entrypoint boundary."""

from __future__ import annotations

import ast
import re
from pathlib import Path

PROVISIONER_ROOT = Path(__file__).resolve().parents[1]


def _python_files() -> list[Path]:
    return sorted(PROVISIONER_ROOT.rglob("*.py"))


def test_production_modules_do_not_import_main_as_dependency() -> None:
    """Provisioner modules should import real owners, not the CLI entrypoint."""
    offenders: list[str] = []
    for path in _python_files():
        rel = path.relative_to(PROVISIONER_ROOT).as_posix()
        if rel == "main.py" or rel.startswith("tests/"):
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "main":
                offenders.append(f"{rel}:{node.lineno} from main import ...")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "main":
                        offenders.append(f"{rel}:{node.lineno} import main")

    assert offenders == []


def test_tests_do_not_patch_main_facade_symbols() -> None:
    """Tests should patch owner modules or external boundaries, never main.X."""
    patch_main = re.compile(r"\b(?:mocker\.)?patch\([\"']main\.")
    offenders = [
        f"{path.relative_to(PROVISIONER_ROOT).as_posix()}:{line_no}"
        for path in sorted((PROVISIONER_ROOT / "tests").glob("test_*.py"))
        for line_no, line in enumerate(path.read_text().splitlines(), start=1)
        if patch_main.search(line)
    ]

    assert offenders == []


def test_main_entrypoint_does_not_re_export_private_internals() -> None:
    """main.py remains the CLI entrypoint, not a private-symbol facade."""
    main_tree = ast.parse((PROVISIONER_ROOT / "main.py").read_text(), filename="main.py")
    offenders: list[str] = []
    for node in ast.walk(main_tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name.startswith("_"):
                    offenders.append(f"line {node.lineno}: imports private {alias.name}")
        elif isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
        ):
            offenders.append(f"line {node.lineno}: defines __all__ facade")

    assert offenders == []
