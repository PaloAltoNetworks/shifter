"""Tests for the check_model_fks management command.

Drives the real command against the real model graph (which is clean — the
model-FK guardrail passes), instead of patching ``Command.analyze_fks`` /
``compute_stats``. The violation-counting path is tested by calling the real
``compute_stats`` on a synthetic results dict (a value, not a mock).
"""

import contextlib
import json
from io import StringIO

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


# Synthetic results dict (a value, not a mock) with one cross-layer violation,
# used to exercise the real compute_stats counting logic.
_RESULTS_WITH_VIOLATION = {layer: [] for layer in ALL_LAYERS}
_RESULTS_WITH_VIOLATION["engine"] = [
    {
        "model": "Range",
        "field": "scenario",
        "field_type": "ForeignKey",
        "references": "cms.Scenario",
        "to_layer": "cms",
        "is_violation": True,
    }
]


def _run_json(*args):
    out = StringIO()
    with contextlib.suppress(SystemExit):
        call_command("check_model_fks", "--json", "-q", *args, stdout=out, stderr=StringIO())
    return json.loads(out.getvalue())


class TestCheckModelFksCommand:
    """Drives the real command against the real (clean) model graph."""

    def test_command_runs_clean(self):
        """The real model graph is clean, so the command completes (exit 0)."""
        with contextlib.suppress(SystemExit):
            call_command("check_model_fks", "-q", stdout=StringIO(), stderr=StringIO())

    def test_json_output_has_relationships_and_stats(self):
        data = _run_json()
        assert isinstance(data["relationships"], dict)
        assert isinstance(data["stats"], dict)

    def test_json_includes_all_layers(self):
        data = _run_json()
        for layer in ALL_LAYERS:
            assert layer in data["relationships"]

    def test_stats_structure(self):
        stats = _run_json()["stats"]
        assert {
            "total_cross_layer_fks",
            "violations",
            "clean_layers",
            "layers_with_violations",
            "violation_details",
        } <= set(stats)

    def test_real_graph_has_no_violations(self):
        assert _run_json()["stats"]["violations"] == 0

    def test_quiet_suppresses_summary(self):
        out = StringIO()
        with contextlib.suppress(SystemExit):
            call_command("check_model_fks", "--json", "-q", stdout=out, stderr=StringIO())
        assert "MODEL FK SUMMARY" not in out.getvalue()

    def test_shows_summary_by_default(self):
        out = StringIO()
        with contextlib.suppress(SystemExit):
            call_command("check_model_fks", stdout=out, stderr=StringIO())
        assert "MODEL FK SUMMARY" in out.getvalue()

    def test_output_file_written(self, tmp_path):
        output_file = tmp_path / "report.json"
        with contextlib.suppress(SystemExit):
            call_command("check_model_fks", "-o", str(output_file), "-q", stdout=StringIO(), stderr=StringIO())
        data = json.loads(output_file.read_text())
        assert "relationships" in data
        assert "stats" in data

    def test_reverse_relations_not_in_output(self):
        data = _run_json()
        for relationships in data["relationships"].values():
            for rel in relationships:
                assert rel["field_type"] not in REVERSE_RELATION_TYPES

    def test_compute_stats_counts_cross_layer_violation(self):
        """The real compute_stats flags a cross-layer FK as a violation."""
        stats = Command().compute_stats(_RESULTS_WITH_VIOLATION)
        assert stats["violations"] == 1
        assert "engine" in stats["layers_with_violations"]
