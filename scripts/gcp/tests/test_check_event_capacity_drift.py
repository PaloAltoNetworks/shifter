"""Read-only event-capacity drift comparison tests (#1816)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "check_event_capacity_drift.py"
_SPEC = importlib.util.spec_from_file_location("check_event_capacity_drift", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)

DriftInputError = _MODULE.DriftInputError
collect_live_state = _MODULE.collect_live_state
compare_capacity_state = _MODULE.compare_capacity_state
render_drift_report = _MODULE.render_drift_report


def _desired() -> dict:
    return {
        "profile_id": "gcp-shared-v1-p30",
        "terraform": {
            "cloud_sql.tier": "db-custom-4-15360",
            "redis.memory_size_gb": 8,
        },
        "kubernetes": {
            "deployment/portal-web.spec.replicas": 5,
            "deployment/guacd.spec.replicas": 2,
        },
    }


def test_exact_live_state_has_no_drift():
    desired = _desired()
    observed = {
        "profile_id": desired["profile_id"],
        "terraform": dict(desired["terraform"]),
        "kubernetes": dict(desired["kubernetes"]),
    }

    assert compare_capacity_state(desired, observed) == []


def test_drift_report_names_field_without_dumping_provider_payload():
    desired = _desired()
    observed = {
        "profile_id": desired["profile_id"],
        "terraform": {**desired["terraform"], "redis.memory_size_gb": 1},
        "kubernetes": dict(desired["kubernetes"]),
        "raw_provider_response": {"password": "must-not-appear"},
    }

    report = render_drift_report(compare_capacity_state(desired, observed))

    assert "redis.memory_size_gb" in report
    assert "desired=8" in report
    assert "observed=1" in report
    assert "must-not-appear" not in report


def test_missing_observation_fails_closed():
    with pytest.raises(DriftInputError, match="missing observed field"):
        compare_capacity_state(_desired(), {"profile_id": "gcp-shared-v1-p30", "terraform": {}, "kubernetes": {}})


def test_cloud_sql_disk_is_a_non_shrinking_floor_during_profile_scale_down():
    desired = {
        "profile_id": "gcp-shared-v1-p10",
        "terraform": {"capacity.cloud_sql_disk_size_gb": 20},
        "kubernetes": {},
    }

    retained_larger_disk = {
        "profile_id": desired["profile_id"],
        "terraform": {"capacity.cloud_sql_disk_size_gb": 60},
        "kubernetes": {},
    }
    undersized_disk = {
        "profile_id": desired["profile_id"],
        "terraform": {"capacity.cloud_sql_disk_size_gb": 10},
        "kubernetes": {},
    }

    assert compare_capacity_state(desired, retained_larger_disk) == []
    assert [drift.field for drift in compare_capacity_state(desired, undersized_disk)] == [
        "capacity.cloud_sql_disk_size_gb"
    ]


def _live_responses(*, access_label: str | None = "gcp-shared-v1-p30") -> list[dict]:
    access_labels = {} if access_label is None else {"shifter_capacity_profile": access_label}
    return [
        {
            "settings": {
                "userLabels": {"shifter_capacity_profile": "gcp-shared-v1-p30"},
                "tier": "db-custom-4-15360",
                "availabilityType": "REGIONAL",
                "dataDiskSizeGb": "100",
            }
        },
        {
            "labels": {"shifter_capacity_profile": "gcp-shared-v1-p30"},
            "tier": "STANDARD_HA",
            "memorySizeGb": 8,
        },
        {
            "config": {"labels": access_labels, "machineType": "e2-standard-8"},
            "initialNodeCount": 99,
            "autoscaling": {"minNodeCount": 3, "maxNodeCount": 8},
        },
        {"items": []},
        {"items": []},
        {"items": []},
        {"data": {}},
    ]


def test_live_state_requires_capacity_profile_label_on_every_provider_resource(monkeypatch):
    responses = iter(_live_responses(access_label=None))
    monkeypatch.setattr(_MODULE, "_run_json", lambda _argv: next(responses))

    with pytest.raises(DriftInputError, match="missing or inconsistent"):
        collect_live_state(
            {},
            project="project",
            region="region",
            sql_instance="sql",
            redis_instance="redis",
            cluster="cluster",
            namespace="namespace",
        )


def test_live_state_uses_effective_autoscaling_minimum_for_access_capacity(monkeypatch):
    responses = iter(_live_responses())
    monkeypatch.setattr(_MODULE, "_run_json", lambda _argv: next(responses))

    observed = collect_live_state(
        {},
        project="project",
        region="region",
        sql_instance="sql",
        redis_instance="redis",
        cluster="cluster",
        namespace="namespace",
    )

    assert observed["terraform"]["capacity.access_node_count"] == 3


def _live(monkeypatch, extra: list[dict], **kwargs) -> dict:
    responses = iter(_live_responses() + extra)
    monkeypatch.setattr(_MODULE, "_run_json", lambda _argv: next(responses))
    return collect_live_state(
        {},
        project="project",
        region="region",
        sql_instance="sql",
        redis_instance="redis",
        cluster="cluster",
        namespace="namespace",
        **kwargs,
    )


def test_a_deployed_openvpn_pool_reports_its_sizing(monkeypatch):
    pool = [
        {"instanceTemplate": "https://compute.googleapis.com/compute/v1/projects/p/regions/r/instanceTemplates/t-1"},
        {"autoscalingPolicy": {"minNumReplicas": 3, "maxNumReplicas": 6, "cpuUtilization": {"utilizationTarget": 0.3}}},
        {"properties": {"machineType": "e2-standard-2"}},
    ]

    observed = _live(monkeypatch, pool, vpn_pool="shifter-x-vpn")

    assert {key: value for key, value in observed["terraform"].items() if "vpn_pool" in key} == {
        "capacity.vpn_pool_machine_type": "e2-standard-2",
        "capacity.vpn_pool_min_vms": 3,
        "capacity.vpn_pool_max_vms": 6,
        "capacity.vpn_pool_cpu_target_pct": 30,
    }
    assert "vpn_pool" not in observed


def test_an_installation_without_the_pool_skips_only_the_pool_fields(monkeypatch):
    observed = _live(monkeypatch, [])
    desired = {
        "profile_id": "gcp-shared-v1-p30",
        "terraform": {**observed["terraform"], "capacity.vpn_pool_min_vms": 3},
        "kubernetes": {},
    }

    assert observed["vpn_pool"] == "absent"
    assert compare_capacity_state(desired, observed) == []
    observed.pop("vpn_pool")
    with pytest.raises(DriftInputError, match="vpn_pool_min_vms"):
        compare_capacity_state(desired, observed)


def test_incomplete_pool_evidence_fails_closed(monkeypatch):
    pool = [{"instanceTemplate": "t"}, {"autoscalingPolicy": {}}, {"properties": {}}]
    with pytest.raises(DriftInputError, match="OpenVPN pool"):
        _live(monkeypatch, pool, vpn_pool="shifter-x-vpn")
