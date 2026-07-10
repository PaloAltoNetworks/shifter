"""Tests for check_layer_imports module."""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from check_layer_imports import (
    ALL_LAYERS,
    CYBERSCRIPT_IMPORT_PATTERN,
    IMPORT_PATTERN,
    analyze_cyberscript_imports,
    analyze_imports,
    analyze_private_facade_imports,
    compute_cyberscript_violations,
    compute_private_facade_violations,
    compute_stats,
    get_cyberscript_imports,
    get_imports,
    get_private_facade_imports,
    is_import_allowed,
    load_allowed_imports,
    print_summary,
)

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "check_layer_imports.py"


class TestLayerConfiguration:
    """Tests for layer configuration constants."""

    def test_all_layers_defined(self):
        """All expected layers are defined."""
        assert "shared" in ALL_LAYERS
        assert "engine" in ALL_LAYERS
        assert "cms" in ALL_LAYERS
        assert "management" in ALL_LAYERS
        assert "mission_control" in ALL_LAYERS


class TestImportPattern:
    """Tests for the import regex pattern."""

    def test_matches_simple_import(self):
        """Matches simple import statements."""
        code = "import shared"
        matches = IMPORT_PATTERN.findall(code)
        assert "shared" in matches

    def test_matches_from_import(self):
        """Matches from...import statements."""
        code = "from engine import something"
        matches = IMPORT_PATTERN.findall(code)
        assert "engine" in matches

    def test_matches_submodule_import(self):
        """Matches submodule imports."""
        code = "from shared.exceptions import BaseError"
        matches = IMPORT_PATTERN.findall(code)
        assert "shared.exceptions" in matches

    def test_matches_deep_import(self):
        """Matches deeply nested imports."""
        code = "from cms.models.range import RangeInstance"
        matches = IMPORT_PATTERN.findall(code)
        assert "cms.models.range" in matches

    def test_matches_indented_import(self):
        """Matches indented imports (inside functions)."""
        code = "    from management import services"
        matches = IMPORT_PATTERN.findall(code)
        assert "management" in matches

    def test_ignores_non_layer_imports(self):
        """Ignores imports from non-layer modules."""
        code = "import os\nfrom django.db import models"
        matches = IMPORT_PATTERN.findall(code)
        assert len(matches) == 0


class TestIsImportAllowed:
    """Tests for the is_import_allowed function."""

    def test_allowed_import_exact_match(self):
        """Exact match in allowed list is allowed."""
        allowed = {"cms": ["shared", "engine"]}
        assert is_import_allowed("cms", "shared", allowed) is True
        assert is_import_allowed("cms", "engine", allowed) is True

    def test_allowed_import_prefix_match(self):
        """Submodule of allowed module is allowed."""
        allowed = {"cms": ["shared"]}
        assert is_import_allowed("cms", "shared.schemas", allowed) is True
        assert is_import_allowed("cms", "shared.exceptions.base", allowed) is True

    def test_disallowed_import(self):
        """Import not in allowed list is disallowed."""
        allowed = {"cms": ["shared"]}
        assert is_import_allowed("cms", "engine", allowed) is False
        assert is_import_allowed("cms", "management", allowed) is False

    def test_layer_not_in_config(self):
        """Layer not in config has no allowed imports."""
        allowed = {"cms": ["shared"]}
        assert is_import_allowed("engine", "shared", allowed) is False

    def test_specific_submodule_allowed(self):
        """Specific submodule allowed but not the whole layer."""
        allowed = {"cms": ["management.services"]}
        assert is_import_allowed("cms", "management.services", allowed) is True
        assert is_import_allowed("cms", "management.services.foo", allowed) is True
        assert is_import_allowed("cms", "management.models", allowed) is False
        assert is_import_allowed("cms", "management", allowed) is False

    def test_private_submodule_rejected(self):
        """A private split-package submodule is not a public facade member."""
        allowed = {"cms": ["engine.services"], "mission_control": ["cms.services"]}
        # Direct dotted private submodule import (e.g. import engine.services._lifecycle).
        assert is_import_allowed("cms", "engine.services._lifecycle", allowed) is False
        assert is_import_allowed("mission_control", "cms.services._range_pause", allowed) is False
        # A private component anywhere in the remainder is rejected.
        assert is_import_allowed("mission_control", "cms.services.sub._private", allowed) is False
        # The public facade and public submodules stay allowed.
        assert is_import_allowed("mission_control", "cms.services", allowed) is True
        assert is_import_allowed("mission_control", "cms.services.public", allowed) is True

    def test_private_shared_submodule_allowed(self):
        """shared is the contracts layer and remains freely importable."""
        allowed = {"cms": ["shared"]}
        assert is_import_allowed("cms", "shared.enums._internal", allowed) is True


class TestLoadAllowedImports:
    """Tests for load_allowed_imports function."""

    def test_loads_config_from_yaml(self, tmp_path):
        """Loads allowed imports from YAML config."""
        config_file = tmp_path / "test_config.yaml"
        config_file.write_text("""
allowed:
  cms:
    - shared
    - engine
  engine:
    - shared
""")
        result = load_allowed_imports(config_file)
        assert result["cms"] == ["shared", "engine"]
        assert result["engine"] == ["shared"]

    def test_returns_empty_for_empty_config(self, tmp_path):
        """Returns empty dict for config without 'allowed' key."""
        config_file = tmp_path / "empty.yaml"
        config_file.write_text("other_key: value\n")
        result = load_allowed_imports(config_file)
        assert result == {}


class TestGetImports:
    """Tests for the get_imports function."""

    def test_returns_empty_for_nonexistent_path(self, tmp_path):
        """Returns empty dict for non-existent path."""
        result = get_imports(tmp_path / "nonexistent")
        assert result == {}

    def test_finds_imports_in_python_files(self, tmp_path):
        """Finds imports in Python files."""
        layer_path = tmp_path / "test_layer"
        layer_path.mkdir()
        (layer_path / "module.py").write_text("from shared.schemas import Thing\n")

        result = get_imports(layer_path)
        assert "shared" in result
        assert "shared.schemas" in result["shared"]

    def test_finds_imports_in_nested_files(self, tmp_path):
        """Finds imports in nested Python files."""
        layer_path = tmp_path / "test_layer"
        subdir = layer_path / "submodule"
        subdir.mkdir(parents=True)
        (subdir / "nested.py").write_text("from engine import provisioner\n")

        result = get_imports(layer_path)
        assert "engine" in result


class TestComputeStats:
    """Tests for the compute_stats function."""

    def test_counts_total_imports(self):
        """Counts total cross-layer imports."""
        imports = {
            "cms": {"engine": ["engine"], "shared": ["shared.schemas"]},
            "engine": {},
        }
        allowed = {"cms": ["shared", "engine"]}
        stats = compute_stats(imports, allowed)
        assert stats["total_cross_layer_imports"] == 2

    def test_counts_violations(self):
        """Counts violations correctly."""
        imports = {
            "shared": {"engine": ["engine.models"]},  # violation - shared can't import
            "cms": {"shared": ["shared"]},  # allowed
        }
        allowed = {"cms": ["shared"]}  # shared has no allowed imports
        stats = compute_stats(imports, allowed)
        assert stats["violations"] == 1

    def test_identifies_clean_layers(self):
        """Identifies layers without violations."""
        imports = {
            "shared": {},
            "engine": {"shared": ["shared"]},
            "cms": {"shared": ["shared"], "engine": ["engine"]},
        }
        allowed = {"engine": ["shared"], "cms": ["shared", "engine"]}
        stats = compute_stats(imports, allowed)
        assert "shared" in stats["clean_layers"]
        assert "engine" in stats["clean_layers"]
        assert "cms" in stats["clean_layers"]

    def test_identifies_layers_with_violations(self):
        """Identifies layers that have violations."""
        imports = {
            "shared": {"engine": ["engine"]},  # violation
            "engine": {"shared": ["shared"]},  # ok
        }
        allowed = {"engine": ["shared"]}  # shared has no allowed imports
        stats = compute_stats(imports, allowed)
        assert "shared" in stats["layers_with_violations"]
        assert "engine" not in stats["layers_with_violations"]

    def test_records_violation_details(self):
        """Records details of each violation."""
        imports = {
            "engine": {"cms": ["cms.models"]},  # violation
        }
        allowed = {"engine": ["shared"]}  # engine can't import cms
        stats = compute_stats(imports, allowed)
        assert len(stats["violation_details"]) == 1
        assert stats["violation_details"][0]["from"] == "engine"
        assert stats["violation_details"][0]["to"] == "cms"
        assert "cms.models" in stats["violation_details"][0]["modules"]

    def test_cyberscript_violations_counted(self):
        """Cyberscript boundary violations roll up into exit-code-driving stats."""
        stats = compute_stats({}, {}, cyberscript={"cms": ["cyberscript.script_context"]})
        assert stats["violations"] == 1
        assert "cms" in stats["layers_with_violations"]
        assert stats["violation_details"] == [
            {
                "from": "cms",
                "to": "cyberscript",
                "modules": ["cyberscript.script_context"],
            }
        ]


class TestCyberscriptImportPattern:
    """Tests for direct cyberscript import detection."""

    def test_matches_from_import(self):
        code = "from cyberscript.script_context import ScriptExecutionContext"
        matches = CYBERSCRIPT_IMPORT_PATTERN.findall(code)
        assert matches == ["cyberscript.script_context"]

    def test_matches_simple_import(self):
        code = "import cyberscript.template_vars"
        matches = CYBERSCRIPT_IMPORT_PATTERN.findall(code)
        assert matches == ["cyberscript.template_vars"]


class TestCyberscriptViolations:
    """Tests for the cyberscript-only-via-shared rule."""

    def test_cms_direct_cyberscript_import_is_violation(self, tmp_path):
        cms_path = tmp_path / "cms" / "experiments"
        cms_path.mkdir(parents=True)
        (cms_path / "orchestrator.py").write_text("from cyberscript.script_context import ScriptExecutionContext\n")
        imports = get_cyberscript_imports(cms_path.parent)
        assert imports == {"cyberscript.script_context"}
        violations = compute_cyberscript_violations("cms", imports)
        assert violations == ["cyberscript.script_context"]

    def test_shared_may_import_cyberscript(self, tmp_path):
        shared_path = tmp_path / "shared"
        shared_path.mkdir()
        (shared_path / "script_context.py").write_text(
            "from cyberscript.script_context import ScriptExecutionContext\n"
        )
        imports = get_cyberscript_imports(shared_path)
        assert "cyberscript.script_context" in imports
        violations = compute_cyberscript_violations("shared", imports)
        assert violations == []


class TestPrivateFacadeImports:
    """Tests for ``from layer.services import _private`` detection (AST-based).

    The regex import scan only sees the module path, so ``from cms.services
    import _range_pause`` looks like an allowed ``cms.services`` facade import.
    This AST pass recovers the imported private name so the gate can reject it.
    """

    def test_detects_from_facade_import_of_private_name(self, tmp_path):
        layer_path = tmp_path / "mission_control"
        layer_path.mkdir()
        (layer_path / "views.py").write_text("from cms.services import _range_pause\n")
        found = get_private_facade_imports(layer_path)
        assert found == {"cms.services._range_pause"}

    def test_detects_aliased_private_name(self, tmp_path):
        layer_path = tmp_path / "mission_control"
        layer_path.mkdir()
        (layer_path / "views.py").write_text("from cms.services import _range_pause as rp\n")
        assert get_private_facade_imports(layer_path) == {"cms.services._range_pause"}

    def test_ignores_public_names_and_relative_imports(self, tmp_path):
        layer_path = tmp_path / "mission_control"
        layer_path.mkdir()
        (layer_path / "views.py").write_text(
            "from cms.services import audit_log\nfrom ._helpers import _thing\nimport os\n"
        )
        assert get_private_facade_imports(layer_path) == set()

    def test_violation_is_cross_layer_and_disallowed(self):
        allowed = {"mission_control": ["cms.services"]}
        modules = {"cms.services._range_pause"}
        assert compute_private_facade_violations("mission_control", modules, allowed) == ["cms.services._range_pause"]

    def test_same_layer_private_import_is_not_a_violation(self):
        allowed = {"cms": ["shared"]}
        modules = {"cms.services._range_pause"}
        assert compute_private_facade_violations("cms", modules, allowed) == []

    def test_analyze_rolls_up_violations_per_layer(self, tmp_path):
        mc_path = tmp_path / "mission_control"
        mc_path.mkdir()
        (mc_path / "views.py").write_text("from cms.services import _range_pause\n")
        allowed = {"mission_control": ["cms.services"]}
        result = analyze_private_facade_imports(tmp_path, allowed)
        assert result == {"mission_control": ["cms.services._range_pause"]}

    def test_private_facade_violations_counted_in_stats(self):
        stats = compute_stats(
            {},
            {"mission_control": ["cms.services"]},
            private_facade={"mission_control": ["cms.services._range_pause"]},
        )
        assert stats["violations"] == 1
        assert "mission_control" in stats["layers_with_violations"]
        assert stats["violation_details"] == [
            {
                "from": "mission_control",
                "to": "cms",
                "modules": ["cms.services._range_pause"],
            }
        ]


class TestAnalyzeImports:
    """Tests for the analyze_imports function."""

    def test_analyzes_all_layers(self, tmp_path):
        """Analyzes all defined layers."""
        # Create minimal layer structure
        for layer in ALL_LAYERS:
            (tmp_path / layer).mkdir()

        result = analyze_imports(tmp_path)
        for layer in ALL_LAYERS:
            assert layer in result

    def test_excludes_self_imports(self, tmp_path):
        """Does not include imports from a layer to itself."""
        layer_path = tmp_path / "shared"
        layer_path.mkdir()
        (layer_path / "module.py").write_text("from shared.other import X\n")

        # Create other layers
        for layer in ALL_LAYERS:
            if layer != "shared":
                (tmp_path / layer).mkdir()

        result = analyze_imports(tmp_path)
        assert "shared" not in result["shared"]

    def test_returns_empty_for_missing_layer(self, tmp_path):
        assert get_cyberscript_imports(tmp_path / "missing") == set()


class TestAnalyzeCyberscriptImports:
    def test_detects_violations_across_layers(self, tmp_path):
        for layer in ALL_LAYERS:
            (tmp_path / layer).mkdir()
        (tmp_path / "cms" / "bad.py").write_text("from cyberscript.template_vars import TemplateString\n")

        result = analyze_cyberscript_imports(tmp_path)
        assert result == {"cms": ["cyberscript.template_vars"]}


class TestPrintSummary:
    def test_prints_violation_details(self, capsys):
        stats = {
            "total_cross_layer_imports": 1,
            "violations": 1,
            "clean_layers": ["shared"],
            "layers_with_violations": ["cms"],
            "violation_details": [{"from": "cms", "to": "cyberscript", "modules": ["cyberscript.template_vars"]}],
        }
        print_summary(stats, file=sys.stdout)
        captured = capsys.readouterr().out
        assert "cms -> cyberscript" in captured
        assert "Violations detected" in captured

    def test_prints_clean_message_when_no_violations(self, capsys):
        stats = {
            "total_cross_layer_imports": 0,
            "violations": 0,
            "clean_layers": ALL_LAYERS,
            "layers_with_violations": [],
            "violation_details": [],
        }
        print_summary(stats, file=sys.stdout)
        assert "No violations detected" in capsys.readouterr().out


class TestMain:
    def test_cli_exits_zero_on_clean_repo(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "-q"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert "cyberscript_imports" in payload
        assert payload["stats"]["violations"] == 0

    def test_cli_writes_output_file(self, tmp_path):
        output_file = tmp_path / "report.json"
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "-o", str(output_file), "-q"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert output_file.exists()
        payload = json.loads(output_file.read_text())
        assert "stats" in payload

    def test_cli_prints_summary_when_not_quiet(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert "LAYER IMPORT SUMMARY" in result.stdout

    def test_cli_exits_one_when_cyberscript_violation_present(self, tmp_path):
        checker_dir = tmp_path / "scripts" / "check_layer_imports"
        checker_dir.mkdir(parents=True)
        config = checker_dir / "layer_imports.yaml"
        config.write_text("allowed:\n  cms:\n    - shared\n")
        platform = tmp_path / "shifter" / "shifter_platform"
        for layer_name in ALL_LAYERS:
            (platform / layer_name).mkdir(parents=True)
        (platform / "cms" / "bad.py").write_text("from cyberscript.template_vars import TemplateString\n")

        script = checker_dir / "check_layer_imports.py"
        script.write_text(
            SCRIPT_PATH.read_text().replace(
                'base_path = script_dir.parent.parent / "shifter" / "shifter_platform"',
                f'base_path = Path("{platform}")',
            )
        )

        result = subprocess.run(
            [sys.executable, str(script), "-q"],
            capture_output=True,
            text=True,
            check=False,
            cwd=checker_dir,
        )
        assert result.returncode == 1, result.stdout
        payload = json.loads(result.stdout)
        assert payload["cyberscript_imports"] == {"cms": ["cyberscript.template_vars"]}


class TestMainInProcess:
    def test_main_missing_config(self, tmp_path, monkeypatch):
        import check_layer_imports as cli

        script_dir = tmp_path / "scripts" / "check_layer_imports"
        script_dir.mkdir(parents=True)
        monkeypatch.setattr(cli, "__file__", str(script_dir / "check_layer_imports.py"))
        monkeypatch.setattr(sys, "argv", ["check_layer_imports", "-q"])
        assert cli.main() == 1

    def test_main_missing_platform_path(self, tmp_path, monkeypatch):
        import check_layer_imports as cli

        script_dir = tmp_path / "scripts" / "check_layer_imports"
        script_dir.mkdir(parents=True)
        (script_dir / "layer_imports.yaml").write_text("allowed: {}\n")
        monkeypatch.setattr(cli, "__file__", str(script_dir / "check_layer_imports.py"))
        monkeypatch.setattr(sys, "argv", ["check_layer_imports", "-q"])
        assert cli.main() == 1

    def test_main_success_with_output_file(self, tmp_path, monkeypatch):
        import check_layer_imports as cli

        repo_root = tmp_path
        script_dir = repo_root / "scripts" / "check_layer_imports"
        script_dir.mkdir(parents=True)
        (script_dir / "layer_imports.yaml").write_text("allowed:\n  cms:\n    - shared\n")
        platform = repo_root / "shifter" / "shifter_platform"
        for layer_name in ALL_LAYERS:
            (platform / layer_name).mkdir(parents=True)
        output_file = tmp_path / "report.json"

        monkeypatch.setattr(cli, "__file__", str(script_dir / "check_layer_imports.py"))
        monkeypatch.setattr(sys, "argv", ["check_layer_imports", "-o", str(output_file)])
        assert cli.main() == 0
        assert output_file.exists()


class TestGetImportsEdgeCases:
    def test_skips_unreadable_python_files(self, tmp_path):
        layer = tmp_path / "cms"
        layer.mkdir()
        unreadable = layer / "secret.py"
        unreadable.write_text("from shared.schemas import RangeSpec\n")
        unreadable.chmod(0o000)
        try:
            assert get_cyberscript_imports(layer) == set()
            assert get_imports(layer) == {}
        finally:
            unreadable.chmod(0o644)
