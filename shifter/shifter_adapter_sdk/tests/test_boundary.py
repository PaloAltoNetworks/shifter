"""An author installs the SDK without the application or a private repository."""

import ast
from pathlib import Path


def test_sdk_imports_no_application_modules():
    root = Path(__file__).resolve().parents[1]
    forbidden = {"shared", "cms", "engine", "config", "django", "provisioner", "installation"}
    sources = [*root.glob("*.py"), *root.joinpath("verification").glob("*.py")]
    for source in sources:
        for node in ast.walk(ast.parse(source.read_text())):
            if isinstance(node, ast.Import):
                imports = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                imports = [node.module or ""]
            else:
                continue
            assert not {name.split(".")[0] for name in imports} & forbidden, source.name
