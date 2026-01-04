"""Tests for check_model_fks management command."""

import json
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command

from management.management.commands.check_model_fks import (
    ALL_LAYERS,
    LAYER_INDEX,
    REVERSE_RELATION_TYPES,
    get_layer_for_app,
    is_violation,
)


class TestIsViolation:
    """Tests for is_violation helper function."""

    def test_lower_to_higher_is_violation(self):
        """Importing from lower layer to higher layer is a violation."""
        assert is_violation("shared", "engine") is True
        assert is_violation("shared", "cms") is True
        assert is_violation("engine", "cms") is True
        assert is_violation("engine", "management") is True
        assert is_violation("cms", "management") is True
        assert is_violation("cms", "mission_control") is True

    def test_higher_to_lower_is_not_violation(self):
        """Importing from higher layer to lower layer is allowed."""
        assert is_violation("engine", "shared") is False
        assert is_violation("cms", "shared") is False
        assert is_violation("cms", "engine") is False
        assert is_violation("mission_control", "shared") is False
        assert is_violation("mission_control", "cms") is False

    def test_unknown_layer_is_not_violation(self):
        """Unknown layers are not flagged as violations."""
        assert is_violation("unknown", "cms") is False
        assert is_violation("cms", "unknown") is False

    def test_same_layer_is_not_violation(self):
        """Same layer to same layer is not a violation."""
        for layer in ALL_LAYERS:
            assert is_violation(layer, layer) is False


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

    def test_layer_index_matches_all_layers(self):
        """LAYER_INDEX has entry for each layer in ALL_LAYERS."""
        for layer in ALL_LAYERS:
            assert layer in LAYER_INDEX

    def test_layer_index_order(self):
        """LAYER_INDEX reflects correct hierarchy (shared lowest)."""
        assert LAYER_INDEX["shared"] < LAYER_INDEX["engine"]
        assert LAYER_INDEX["engine"] < LAYER_INDEX["cms"]
        assert LAYER_INDEX["cms"] < LAYER_INDEX["management"]
        assert LAYER_INDEX["management"] < LAYER_INDEX["mission_control"]

    def test_reverse_relation_types(self):
        """REVERSE_RELATION_TYPES contains Django reverse relation classes."""
        assert "ManyToOneRel" in REVERSE_RELATION_TYPES
        assert "OneToOneRel" in REVERSE_RELATION_TYPES
        assert "ManyToManyRel" in REVERSE_RELATION_TYPES


@pytest.mark.django_db
class TestCheckModelFksCommand:
    """Tests for check_model_fks management command."""

    def test_command_runs(self):
        """Command runs without error."""
        out = StringIO()
        # Command may exit with 1 if violations exist, that's expected
        try:
            call_command("check_model_fks", stdout=out, stderr=StringIO())
        except SystemExit as e:
            # Exit code 1 is expected if violations exist
            assert e.code in (0, 1)

    def test_command_json_output(self):
        """Command outputs valid JSON with --json flag."""
        out = StringIO()
        try:
            call_command(
                "check_model_fks", "--json", "-q", stdout=out, stderr=StringIO()
            )
        except SystemExit:
            pass

        output = out.getvalue()
        data = json.loads(output)

        assert "relationships" in data
        assert "stats" in data
        assert isinstance(data["relationships"], dict)
        assert isinstance(data["stats"], dict)

    def test_command_json_has_all_layers(self):
        """JSON output includes all layers."""
        out = StringIO()
        try:
            call_command(
                "check_model_fks", "--json", "-q", stdout=out, stderr=StringIO()
            )
        except SystemExit:
            pass

        data = json.loads(out.getvalue())

        for layer in ALL_LAYERS:
            assert layer in data["relationships"]

    def test_command_stats_structure(self):
        """Stats in JSON output have expected structure."""
        out = StringIO()
        try:
            call_command(
                "check_model_fks", "--json", "-q", stdout=out, stderr=StringIO()
            )
        except SystemExit:
            pass

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
        try:
            call_command("check_model_fks", "--json", "-q", stdout=out, stderr=err)
        except SystemExit:
            pass

        # Summary should not appear
        assert "MODEL FK SUMMARY" not in out.getvalue()
        assert "MODEL FK SUMMARY" not in err.getvalue()

    def test_command_shows_summary_by_default(self):
        """Summary is shown by default."""
        out = StringIO()
        try:
            call_command("check_model_fks", stdout=out, stderr=StringIO())
        except SystemExit:
            pass

        assert "MODEL FK SUMMARY" in out.getvalue()

    def test_command_output_file(self, tmp_path):
        """--output flag saves JSON to file."""
        output_file = tmp_path / "report.json"
        try:
            call_command(
                "check_model_fks",
                "-o", str(output_file),
                "-q",
                stdout=StringIO(),
                stderr=StringIO(),
            )
        except SystemExit:
            pass

        assert output_file.exists()
        data = json.loads(output_file.read_text())
        assert "relationships" in data
        assert "stats" in data

    def test_command_exits_with_error_on_violations(self):
        """Command exits with code 1 when violations exist."""
        # Mock stats with violations
        mock_stats = {
            "violations": 1,
            "total_cross_layer_fks": 1,
            "clean_layers": [],
            "layers_with_violations": ["engine"],
            "violation_details": [{"from": "engine", "to": "cms"}],
        }

        with patch.object(
            __import__(
                "management.management.commands.check_model_fks",
                fromlist=["Command"],
            ).Command,
            "compute_stats",
            return_value=mock_stats,
        ):
            with pytest.raises(SystemExit) as exc_info:
                call_command(
                    "check_model_fks", "-q", stdout=StringIO(), stderr=StringIO()
                )
            assert exc_info.value.code == 1

    def test_reverse_relations_filtered_out(self):
        """Reverse relations (ManyToOneRel etc.) are not included."""
        out = StringIO()
        try:
            call_command(
                "check_model_fks", "--json", "-q", stdout=out, stderr=StringIO()
            )
        except SystemExit:
            pass

        data = json.loads(out.getvalue())

        # Check that no field_type is a reverse relation
        for layer, relationships in data["relationships"].items():
            for rel in relationships:
                assert rel["field_type"] not in REVERSE_RELATION_TYPES
