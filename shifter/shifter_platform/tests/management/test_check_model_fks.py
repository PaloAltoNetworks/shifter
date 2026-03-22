"""Tests for check_model_fks management command."""

import contextlib
import json
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command

from management.management.commands.check_model_fks import (
    ALL_LAYERS,
    REVERSE_RELATION_TYPES,
    Command,
    get_layer_for_app,
    is_violation,
)


class TestIsViolation:
    """Tests for is_violation helper function.

    The platform enforces ZERO cross-layer FK coupling.
    Any FK between layers is a violation - no exceptions.
    """

    def test_any_cross_layer_fk_is_violation(self):
        """Any FK between different layers is a violation."""
        # All combinations of different layers should be violations
        for from_layer in ALL_LAYERS:
            for to_layer in ALL_LAYERS:
                if from_layer != to_layer:
                    assert is_violation(from_layer, to_layer) is True, (
                        f"{from_layer} -> {to_layer} should be a violation"
                    )

    def test_same_layer_is_not_violation(self):
        """Same layer to same layer is not a violation."""
        for layer in ALL_LAYERS:
            assert is_violation(layer, layer) is False

    def test_unknown_layer_is_not_violation(self):
        """Unknown layers are not flagged as violations."""
        assert is_violation("unknown", "cms") is False
        assert is_violation("cms", "unknown") is False
        assert is_violation("auth", "cms") is False
        assert is_violation("cms", "contenttypes") is False


class TestGetLayerForApp:
    """Tests for get_layer_for_app helper function."""

    def test_returns_layer_for_known_apps(self):
        """Returns layer name for known app labels."""
        for layer in ALL_LAYERS:
            assert get_layer_for_app(layer) == layer

    def test_returns_none_for_unknown_apps(self):
        """Returns None for unknown app labels."""
        assert get_layer_for_app("unknown") is None
        assert get_layer_for_app("auth") is None
        assert get_layer_for_app("contenttypes") is None


class TestLayerConstants:
    """Tests for layer constants."""

    def test_all_layers_defined(self):
        """All expected layers are defined."""
        assert "shared" in ALL_LAYERS
        assert "engine" in ALL_LAYERS
        assert "cms" in ALL_LAYERS
        assert "management" in ALL_LAYERS
        assert "mission_control" in ALL_LAYERS

    def test_reverse_relation_types(self):
        """REVERSE_RELATION_TYPES contains Django reverse relation classes."""
        assert "ManyToOneRel" in REVERSE_RELATION_TYPES
        assert "OneToOneRel" in REVERSE_RELATION_TYPES
        assert "ManyToManyRel" in REVERSE_RELATION_TYPES


# Sample mock data for command tests
MOCK_RESULTS = {layer: [] for layer in ALL_LAYERS}
MOCK_RESULTS["engine"] = [
    {
        "model": "Range",
        "field": "scenario",
        "field_type": "ForeignKey",
        "references": "cms.Scenario",
        "to_layer": "cms",
        "is_violation": True,
    }
]

MOCK_STATS_WITH_VIOLATIONS = {
    "total_cross_layer_fks": 1,
    "violations": 1,
    "clean_layers": ["shared", "cms", "management", "mission_control"],
    "layers_with_violations": ["engine"],
    "violation_details": [{"from": "engine", "to": "cms"}],
}

MOCK_STATS_CLEAN = {
    "total_cross_layer_fks": 0,
    "violations": 0,
    "clean_layers": ALL_LAYERS[:],
    "layers_with_violations": [],
    "violation_details": [],
}


class TestCheckModelFksCommand:
    """Tests for check_model_fks management command."""

    def test_command_runs(self):
        """Command runs without error."""
        out = StringIO()
        with patch.object(Command, "analyze_fks", return_value=MOCK_RESULTS):
            try:
                call_command("check_model_fks", stdout=out, stderr=StringIO())
            except SystemExit as e:
                assert e.code in (0, 1)

    def test_command_json_output(self):
        """Command outputs valid JSON with --json flag."""
        out = StringIO()
        with patch.object(Command, "analyze_fks", return_value=MOCK_RESULTS), contextlib.suppress(SystemExit):
            call_command("check_model_fks", "--json", "-q", stdout=out, stderr=StringIO())

        output = out.getvalue()
        data = json.loads(output)

        assert "relationships" in data
        assert "stats" in data
        assert isinstance(data["relationships"], dict)
        assert isinstance(data["stats"], dict)

    def test_command_json_has_all_layers(self):
        """JSON output includes all layers."""
        out = StringIO()
        with patch.object(Command, "analyze_fks", return_value=MOCK_RESULTS), contextlib.suppress(SystemExit):
            call_command("check_model_fks", "--json", "-q", stdout=out, stderr=StringIO())

        data = json.loads(out.getvalue())

        for layer in ALL_LAYERS:
            assert layer in data["relationships"]

    def test_command_stats_structure(self):
        """Stats in JSON output have expected structure."""
        out = StringIO()
        with patch.object(Command, "analyze_fks", return_value=MOCK_RESULTS), contextlib.suppress(SystemExit):
            call_command("check_model_fks", "--json", "-q", stdout=out, stderr=StringIO())

        data = json.loads(out.getvalue())
        stats = data["stats"]

        assert "total_cross_layer_fks" in stats
        assert "violations" in stats
        assert "clean_layers" in stats
        assert "layers_with_violations" in stats
        assert "violation_details" in stats

    def test_command_quiet_suppresses_summary(self):
        """--quiet flag suppresses summary output."""
        out = StringIO()
        err = StringIO()
        with patch.object(Command, "analyze_fks", return_value=MOCK_RESULTS), contextlib.suppress(SystemExit):
            call_command("check_model_fks", "--json", "-q", stdout=out, stderr=err)

        assert "MODEL FK SUMMARY" not in out.getvalue()
        assert "MODEL FK SUMMARY" not in err.getvalue()

    def test_command_shows_summary_by_default(self):
        """Summary is shown by default."""
        out = StringIO()
        with patch.object(Command, "analyze_fks", return_value=MOCK_RESULTS), contextlib.suppress(SystemExit):
            call_command("check_model_fks", stdout=out, stderr=StringIO())

        assert "MODEL FK SUMMARY" in out.getvalue()

    def test_command_output_file(self, tmp_path):
        """--output flag saves JSON to file."""
        output_file = tmp_path / "report.json"
        with patch.object(Command, "analyze_fks", return_value=MOCK_RESULTS), contextlib.suppress(SystemExit):
            call_command(
                "check_model_fks",
                "-o",
                str(output_file),
                "-q",
                stdout=StringIO(),
                stderr=StringIO(),
            )

        assert output_file.exists()
        data = json.loads(output_file.read_text())
        assert "relationships" in data
        assert "stats" in data

    def test_command_exits_with_error_on_violations(self):
        """Command exits with code 1 when violations exist."""
        with (
            patch.object(Command, "analyze_fks", return_value=MOCK_RESULTS),
            patch.object(Command, "compute_stats", return_value=MOCK_STATS_WITH_VIOLATIONS),
        ):
            with pytest.raises(SystemExit) as exc_info:
                call_command("check_model_fks", "-q", stdout=StringIO(), stderr=StringIO())
            assert exc_info.value.code == 1

    def test_reverse_relations_filtered_out(self):
        """Reverse relations (ManyToOneRel etc.) are not included in mock results."""
        out = StringIO()
        with patch.object(Command, "analyze_fks", return_value=MOCK_RESULTS), contextlib.suppress(SystemExit):
            call_command("check_model_fks", "--json", "-q", stdout=out, stderr=StringIO())

        data = json.loads(out.getvalue())

        for _layer, relationships in data["relationships"].items():
            for rel in relationships:
                assert rel["field_type"] not in REVERSE_RELATION_TYPES
