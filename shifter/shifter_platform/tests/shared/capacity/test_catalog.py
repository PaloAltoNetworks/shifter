"""Deployment-owned partition and metric catalog parsing (PLAT-201, #680).

The catalog is the allowlist: partitions and metrics exist only because a
deployment declared them. Parsing is strict on purpose -- a typo that silently
defaulted a metric to advisory, or a margin that silently clamped, would change
admission behaviour without anyone noticing.
"""

from __future__ import annotations

import json

import pytest

from shared.capacity import EnforcementMode, MeasurementSource
from shared.capacity.catalog import CapacityCatalogError, load_catalog

VALID = {
    "partitions": [
        {
            "name": "aws-dev-use2",
            "provider": "aws",
            "account": "111122223333",
            "region": "us-east-2",
            "backend": "ecs",
        },
        {
            "name": "aws-overflow-use2",
            "provider": "aws",
            "account": "123456789012",
            "region": "us-east-2",
            "backend": "ecs",
            "policy_profile": "overflow",
        },
    ],
    "metrics": [
        {
            "name": "ec2_vcpu",
            "dimension": "vcpu",
            "unit": "count",
            "partition": "aws-dev-use2",
            "source": "provider_probe",
            "freshness_seconds": 900,
            "safety_margin_ratio": 0.2,
            "provider_ref": {"limit_ref": "ec2/L-1216C47A", "usage_ref": "AWS/Usage/ResourceCount"},
        },
        {
            "name": "bedrock_tpm",
            "dimension": "tokens_per_minute",
            "unit": "tokens/min",
            "partition": "aws-dev-use2",
            "source": "provider_probe",
            "freshness_seconds": 300,
            "enforcement": "enforcing",
        },
    ],
}


class TestValidCatalog:
    def test_parses_partitions_and_metrics(self):
        catalog = load_catalog(VALID)

        assert set(catalog.partitions) == {"aws-dev-use2", "aws-overflow-use2"}
        assert {metric.name for metric in catalog.metrics_for("aws-dev-use2")} == {"ec2_vcpu", "bedrock_tpm"}

    def test_partition_identity_is_carried_through(self):
        partition = load_catalog(VALID).partitions["aws-overflow-use2"]

        assert partition.account == "123456789012"
        assert partition.region == "us-east-2"
        assert partition.policy_profile == "overflow"

    def test_policy_profile_defaults(self):
        assert load_catalog(VALID).partitions["aws-dev-use2"].policy_profile == "default"

    def test_metric_fields_are_typed(self):
        metric = next(m for m in load_catalog(VALID).metrics_for("aws-dev-use2") if m.name == "ec2_vcpu")

        assert metric.source is MeasurementSource.PROVIDER_PROBE
        assert metric.freshness_seconds == 900
        assert metric.safety_margin_ratio == pytest.approx(0.2)
        assert metric.provider_ref is not None
        assert metric.provider_ref.limit_ref == "ec2/L-1216C47A"

    def test_metrics_for_unknown_partition_is_empty(self):
        assert load_catalog(VALID).metrics_for("nope") == ()

    def test_empty_catalog_is_valid_and_inert(self):
        catalog = load_catalog({})

        assert catalog.partitions == {}
        assert catalog.metrics_for("anything") == ()


class TestEnforcementDefaults:
    """Advisory is the default; enforcing must be declared explicitly."""

    def test_omitted_enforcement_is_advisory(self):
        metric = next(m for m in load_catalog(VALID).metrics_for("aws-dev-use2") if m.name == "ec2_vcpu")

        assert metric.enforcement is EnforcementMode.ADVISORY

    def test_declared_enforcing_is_honoured(self):
        metric = next(m for m in load_catalog(VALID).metrics_for("aws-dev-use2") if m.name == "bedrock_tpm")

        assert metric.enforcement is EnforcementMode.ENFORCING

    def test_unknown_enforcement_value_is_rejected(self):
        payload = _with_metric({"enforcement": "block-everything"})

        with pytest.raises(CapacityCatalogError):
            load_catalog(payload)


class TestStrictValidation:
    """A malformed catalog fails loud at the composition root, never silently."""

    def test_unknown_metric_key_is_rejected(self):
        """A typo must not silently fall back to a default enforcement mode."""
        payload = _with_metric({"enforcment": "enforcing"})

        with pytest.raises(CapacityCatalogError):
            load_catalog(payload)

    def test_unknown_partition_key_is_rejected(self):
        payload = {"partitions": [{**VALID["partitions"][0], "acount": "typo"}], "metrics": []}

        with pytest.raises(CapacityCatalogError):
            load_catalog(payload)

    @pytest.mark.parametrize("ratio", [-0.1, 1.0, 1.5, "nope"])
    def test_out_of_range_safety_margin_is_rejected(self, ratio):
        payload = _with_metric({"safety_margin_ratio": ratio})

        with pytest.raises(CapacityCatalogError):
            load_catalog(payload)

    @pytest.mark.parametrize("freshness", [0, -1, "soon"])
    def test_non_positive_freshness_is_rejected(self, freshness):
        payload = _with_metric({"freshness_seconds": freshness})

        with pytest.raises(CapacityCatalogError):
            load_catalog(payload)

    def test_metric_referencing_undeclared_partition_is_rejected(self):
        """Metrics may only target allowlisted partitions."""
        payload = _with_metric({"partition": "not-declared"})

        with pytest.raises(CapacityCatalogError):
            load_catalog(payload)

    def test_duplicate_partition_name_is_rejected(self):
        payload = {"partitions": [VALID["partitions"][0], VALID["partitions"][0]], "metrics": []}

        with pytest.raises(CapacityCatalogError):
            load_catalog(payload)

    def test_duplicate_metric_name_in_one_partition_is_rejected(self):
        payload = {"partitions": VALID["partitions"], "metrics": [VALID["metrics"][0], VALID["metrics"][0]]}

        with pytest.raises(CapacityCatalogError):
            load_catalog(payload)

    def test_missing_required_partition_field_is_rejected(self):
        payload = {"partitions": [{"name": "x", "provider": "aws"}], "metrics": []}

        with pytest.raises(CapacityCatalogError):
            load_catalog(payload)

    def test_unknown_measurement_source_is_rejected(self):
        payload = _with_metric({"source": "vibes"})

        with pytest.raises(CapacityCatalogError):
            load_catalog(payload)

    def test_non_mapping_payload_is_rejected(self):
        with pytest.raises(CapacityCatalogError):
            load_catalog([])  # type: ignore[arg-type]


class TestCostCoefficients:
    """Deployment declares what a range and a node cost; Shifter never guesses."""

    def test_costs_default_to_zero(self):
        metric = next(m for m in load_catalog(VALID).metrics_for("aws-dev-use2") if m.name == "ec2_vcpu")

        assert metric.per_range_cost == 0.0
        assert metric.per_node_cost == 0.0

    def test_declared_costs_are_parsed(self):
        catalog = load_catalog(_with_metric({"per_range_cost": 4, "per_node_cost": 2.5}))
        metric = next(m for m in catalog.metrics_for("aws-dev-use2") if m.name == "ec2_vcpu")

        assert metric.per_range_cost == pytest.approx(4.0)
        assert metric.per_node_cost == pytest.approx(2.5)

    @pytest.mark.parametrize("cost", [-1, "free"])
    def test_invalid_cost_is_rejected(self, cost):
        payload = _with_metric({"per_range_cost": cost})

        with pytest.raises(CapacityCatalogError):
            load_catalog(payload)

    def test_cost_change_changes_the_policy_version(self):
        """Costs affect admission, so they must be pinned into the version."""
        assert load_catalog(_with_metric({"per_range_cost": 4})).policy_version != load_catalog(VALID).policy_version


class TestPolicyVersion:
    """Assessments pin the policy version that produced them."""

    def test_version_is_stable_for_identical_catalogs(self):
        """A second parse of an equal payload yields the same version."""
        duplicate = json.loads(json.dumps(VALID))

        assert load_catalog(duplicate).policy_version == load_catalog(VALID).policy_version

    def test_version_changes_when_enforcement_changes(self):
        stricter = _with_metric({"enforcement": "enforcing"}, index=0)

        assert load_catalog(stricter).policy_version != load_catalog(VALID).policy_version

    def test_version_is_insensitive_to_declaration_order(self):
        reordered = {
            "partitions": list(reversed(VALID["partitions"])),
            "metrics": list(reversed(VALID["metrics"])),
        }

        assert load_catalog(reordered).policy_version == load_catalog(VALID).policy_version


def _with_metric(overrides: dict, index: int = 0) -> dict:
    """Return the valid catalog with one metric field overridden."""
    metrics = [dict(metric) for metric in VALID["metrics"]]
    metrics[index].update(overrides)
    return {"partitions": VALID["partitions"], "metrics": metrics}
