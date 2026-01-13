"""Tests for check_layer_imports module."""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from check_layer_imports import (
    ALL_LAYERS,
    IMPORT_PATTERN,
    analyze_imports,
    compute_stats,
    get_imports,
    is_import_allowed,
    load_allowed_imports,
)


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
