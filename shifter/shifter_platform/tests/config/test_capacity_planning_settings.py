"""Capacity-planning settings binding (PLAT-201, #680).

The composition root must fail closed on a malformed catalog rather than boot
with a partial allowlist, and must keep its metric namespace separate from the
unrelated portal saturation emitter.
"""

from __future__ import annotations

import importlib
import json
import os

import pytest
from django.core.exceptions import ImproperlyConfigured

MODULE = "config._capacity_planning_settings"

CATALOG = {
    "partitions": [
        {
            "name": "aws-dev-use2",
            "provider": "aws",
            "account": "111122223333",
            "region": "us-east-2",
            "backend": "ecs",
        }
    ],
    "metrics": [
        {
            "name": "ec2_vcpu",
            "dimension": "vcpu",
            "unit": "count",
            "partition": "aws-dev-use2",
            "source": "provider_probe",
            "freshness_seconds": 900,
        }
    ],
}


def _reload(monkeypatch, **env):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return importlib.reload(importlib.import_module(MODULE))


@pytest.fixture(autouse=True)
def _restore_module():
    """Leave the module in its default state for other tests.

    Clears the environment explicitly rather than relying on ``monkeypatch``
    teardown ordering: this fixture's finalizer runs first, so a leftover
    catalog would otherwise be re-parsed here and raise during teardown.
    """
    yield
    for key in ("CAPACITY_PLANNING_CATALOG", "CAPACITY_PLANNING_ENABLED"):
        os.environ.pop(key, None)
    importlib.reload(importlib.import_module(MODULE))


class TestCatalogBinding:
    def test_absent_catalog_is_empty_not_an_error(self, monkeypatch):
        monkeypatch.delenv("CAPACITY_PLANNING_CATALOG", raising=False)
        module = _reload(monkeypatch)

        assert module.CAPACITY_PLANNING_CATALOG.partitions == {}

    def test_declared_catalog_is_parsed(self, monkeypatch):
        module = _reload(monkeypatch, CAPACITY_PLANNING_CATALOG=json.dumps(CATALOG))

        assert "aws-dev-use2" in module.CAPACITY_PLANNING_CATALOG.partitions
        assert module.CAPACITY_PLANNING_CATALOG.metrics_for("aws-dev-use2")[0].name == "ec2_vcpu"

    def test_malformed_json_fails_closed(self, monkeypatch):
        with pytest.raises(ImproperlyConfigured):
            _reload(monkeypatch, CAPACITY_PLANNING_CATALOG="{not json")

    def test_structurally_invalid_catalog_fails_closed(self, monkeypatch):
        """A metric pointing at an undeclared partition must stop the boot."""
        broken = json.dumps({"partitions": [], "metrics": CATALOG["metrics"]})

        with pytest.raises(ImproperlyConfigured):
            _reload(monkeypatch, CAPACITY_PLANNING_CATALOG=broken)


class TestOperationalDefaults:
    def test_layer_is_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("CAPACITY_PLANNING_ENABLED", raising=False)
        module = _reload(monkeypatch)

        assert module.CAPACITY_PLANNING_ENABLED is False

    def test_enable_flag_is_explicit(self, monkeypatch):
        assert _reload(monkeypatch, CAPACITY_PLANNING_ENABLED="true").CAPACITY_PLANNING_ENABLED is True

    def test_metrics_namespace_is_not_the_portal_saturation_namespace(self, monkeypatch):
        """Conflating the two series would make both unreadable (preflight guardrail)."""
        module = _reload(monkeypatch)

        assert module.CAPACITY_PLANNING_METRICS_NAMESPACE != "Shifter/PortalCapacity"
        assert module.CAPACITY_PLANNING_METRICS_NAMESPACE == "Shifter/CapacityPlanning"

    def test_read_role_defaults_to_a_dedicated_name(self, monkeypatch):
        module = _reload(monkeypatch)

        assert module.CAPACITY_INVENTORY_ROLE_NAME == "shifter-capacity-read"
