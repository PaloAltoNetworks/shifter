"""Tests for check_layer_imports module."""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from check_layer_imports import (
    ALL_LAYERS,
    IMPORT_PATTERN,
    LAYER_INDEX,
    analyze_imports,
    compute_stats,
    get_imports,
    is_violation,
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

    def test_layer_order(self):
        """Layers are ordered from lowest to highest."""
        assert LAYER_INDEX["shared"] < LAYER_INDEX["engine"]
        assert LAYER_INDEX["engine"] < LAYER_INDEX["cms"]
        assert LAYER_INDEX["cms"] < LAYER_INDEX["management"]
        assert LAYER_INDEX["management"] < LAYER_INDEX["mission_control"]


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


class TestIsViolation:
    """Tests for the is_violation function."""

    def test_shared_importing_higher_is_violation(self):
        """shared importing from higher layers is a violation."""
        assert is_violation("shared", "engine") is True
        assert is_violation("shared", "cms") is True
        assert is_violation("shared", "management") is True
        assert is_violation("shared", "mission_control") is True

    def test_engine_importing_higher_is_violation(self):
        """engine importing from higher layers is a violation."""
        assert is_violation("engine", "cms") is True
        assert is_violation("engine", "management") is True
        assert is_violation("engine", "mission_control") is True

    def test_higher_importing_lower_is_not_violation(self):
        """Higher layers importing from lower is not a violation."""
        assert is_violation("mission_control", "cms") is False
        assert is_violation("cms", "engine") is False
        assert is_violation("engine", "shared") is False

    def test_any_layer_importing_shared_is_not_violation(self):
        """Any layer importing from shared is not a violation."""
        assert is_violation("engine", "shared") is False
        assert is_violation("cms", "shared") is False
        assert is_violation("management", "shared") is False
        assert is_violation("mission_control", "shared") is False


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
        stats = compute_stats(imports)
        assert stats["total_cross_layer_imports"] == 2

    def test_counts_violations(self):
        """Counts violations correctly."""
        imports = {
            "shared": {"engine": ["engine.models"]},  # violation
            "cms": {"shared": ["shared"]},  # not a violation
        }
        stats = compute_stats(imports)
        assert stats["violations"] == 1

    def test_identifies_clean_layers(self):
        """Identifies layers without violations."""
        imports = {
            "shared": {},
            "engine": {"shared": ["shared"]},
            "cms": {"shared": ["shared"], "engine": ["engine"]},
        }
        stats = compute_stats(imports)
        assert "shared" in stats["clean_layers"]
        assert "engine" in stats["clean_layers"]
        assert "cms" in stats["clean_layers"]

    def test_identifies_layers_with_violations(self):
        """Identifies layers that have violations."""
        imports = {
            "shared": {"engine": ["engine"]},  # violation
            "engine": {"shared": ["shared"]},  # ok
        }
        stats = compute_stats(imports)
        assert "shared" in stats["layers_with_violations"]
        assert "engine" not in stats["layers_with_violations"]

    def test_records_violation_details(self):
        """Records details of each violation."""
        imports = {
            "engine": {"cms": ["cms.models"]},  # violation
        }
        stats = compute_stats(imports)
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
