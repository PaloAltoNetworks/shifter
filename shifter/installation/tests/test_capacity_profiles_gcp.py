"""GCP shared-service capacity profile contract tests (#1816)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from installation.capacity_profiles_gcp import (
    CAPACITY_PROFILES,
    GcpSharedServiceCapacityProfile,
    resolve_capacity_profile,
)


def test_catalog_has_all_versioned_event_sizes():
    assert set(CAPACITY_PROFILES) == {
        "gcp-shared-v1-p10",
        "gcp-shared-v1-p30",
        "gcp-shared-v1-p50",
        "gcp-shared-v1-p100",
        "gcp-shared-v1-p200",
        "gcp-shared-v1-p300",
        "gcp-shared-v1-p500",
    }


@pytest.mark.parametrize(
    (
        "profile_id",
        "participants",
        "portal_replicas",
        "guacd_replicas",
        "access_min",
        "access_max",
        "sql_tier",
        "sql_ha",
        "sql_disk",
        "sql_budget",
        "redis_gb",
    ),
    [
        ("gcp-shared-v1-p10", 10, 2, 1, 2, 4, "db-custom-2-7680", "ZONAL", 20, 100, 2),
        ("gcp-shared-v1-p30", 30, 5, 2, 3, 8, "db-custom-4-15360", "REGIONAL", 60, 200, 8),
        ("gcp-shared-v1-p50", 50, 8, 4, 4, 12, "db-custom-8-30720", "REGIONAL", 100, 350, 12),
        ("gcp-shared-v1-p100", 100, 14, 8, 6, 20, "db-custom-16-61440", "REGIONAL", 200, 650, 20),
        ("gcp-shared-v1-p200", 200, 26, 16, 12, 24, "db-custom-32-122880", "REGIONAL", 400, 800, 32),
        ("gcp-shared-v1-p300", 300, 38, 24, 18, 36, "db-custom-48-184320", "REGIONAL", 600, 800, 48),
        ("gcp-shared-v1-p500", 500, 62, 40, 28, 57, "db-custom-64-245760", "REGIONAL", 1000, 800, 80),
    ],
)
def test_every_catalog_profile_has_its_authored_capacity_shape(
    profile_id,
    participants,
    portal_replicas,
    guacd_replicas,
    access_min,
    access_max,
    sql_tier,
    sql_ha,
    sql_disk,
    sql_budget,
    redis_gb,
):
    profile = resolve_capacity_profile(profile_id)

    assert profile.participant_count == participants
    assert profile.portal.replicas == portal_replicas
    assert profile.guacd.replicas == guacd_replicas
    assert profile.guacamole_client.replicas == 1
    assert profile.guacamole_client.jdbc_pool_active_connections == 10
    assert profile.guacamole_client.absolute_tunnel_connections == participants
    assert profile.access_nodes.minimum_nodes == access_min
    assert profile.access_nodes.maximum_nodes == access_max
    assert profile.cloud_sql.tier == sql_tier
    assert profile.cloud_sql.availability_type == sql_ha
    assert profile.cloud_sql.disk_size_gb == sql_disk
    assert profile.cloud_sql.connection_budget == sql_budget
    assert profile.redis.memory_size_gb == redis_gb
    assert profile.redis.tier == "STANDARD_HA"
    assert profile.gate.concurrency == participants
    assert profile.gate.hold_seconds == 120
    assert profile.gate.telemetry_settle_seconds == 240


def test_unknown_profile_fails_closed():
    with pytest.raises(ValueError, match="unknown shared-service capacity profile"):
        resolve_capacity_profile("gcp-shared-v1-p31")


def test_profile_rejects_multiple_guacamole_clients():
    data = resolve_capacity_profile("gcp-shared-v1-p30").model_dump(mode="json")
    data["guacamole_client"]["replicas"] = 2

    with pytest.raises(ValidationError):
        GcpSharedServiceCapacityProfile.model_validate(data)


def test_profile_rejects_timeout_and_pool_inconsistencies():
    data = resolve_capacity_profile("gcp-shared-v1-p30").model_dump(mode="json")
    data["timeouts"]["portal_backend_seconds"] = 60
    with pytest.raises(ValidationError, match="WebSocket cadence"):
        GcpSharedServiceCapacityProfile.model_validate(data)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda data: data.update(participant_count=10), "profile identity, participant count"),
        (
            lambda data: data["portal"]["autoscaling"].update(min_replicas=4),
            "portal minimum replicas",
        ),
        (
            lambda data: data["guacd"]["autoscaling"].update(min_replicas=1),
            "guacd minimum replicas",
        ),
        (
            lambda data: data["timeouts"].update(pod_termination_grace_seconds=299),
            "pod termination grace must cover connection draining",
        ),
        (
            lambda data: data["timeouts"].update(pod_termination_grace_seconds=300),
            "pod termination grace must exceed the process graceful timeout",
        ),
        (
            lambda data: data["redis"].update(connection_budget=20),
            "Redis connection budget",
        ),
        (
            lambda data: data["gate"].update(required_guacd_replicas=3),
            "gate requires more guacd replicas",
        ),
    ],
)
def test_profile_rejects_each_coupled_capacity_invariant(mutate, message):
    data = resolve_capacity_profile("gcp-shared-v1-p30").model_dump(mode="json")
    mutate(data)

    with pytest.raises(ValidationError, match=message):
        GcpSharedServiceCapacityProfile.model_validate(data)


def test_profile_accepts_termination_grace_equal_to_drain_when_process_exits_first():
    data = resolve_capacity_profile("gcp-shared-v1-p30").model_dump(mode="json")
    data["timeouts"].update(
        process_graceful_timeout_seconds=299,
        connection_draining_seconds=300,
        pod_termination_grace_seconds=300,
    )

    profile = GcpSharedServiceCapacityProfile.model_validate(data)

    assert profile.timeouts.pod_termination_grace_seconds == profile.timeouts.connection_draining_seconds

    data = resolve_capacity_profile("gcp-shared-v1-p30").model_dump(mode="json")
    data["cloud_sql"]["connection_budget"] = 20
    with pytest.raises(ValidationError, match="SQL connection budget"):
        GcpSharedServiceCapacityProfile.model_validate(data)


def test_p30_projections_share_the_same_identity():
    profile = resolve_capacity_profile("gcp-shared-v1-p30")

    assert profile.terraform_projection()["shared_service_capacity_profile"] == profile.profile_id
    assert profile.helm_projection()["capacityProfile"]["id"] == profile.profile_id
    assert profile.gate_projection()["capacity_profile_id"] == profile.profile_id
    assert profile.desired_state()["profile_id"] == profile.profile_id


def test_p30_terraform_and_gate_projections_are_complete():
    profile = resolve_capacity_profile("gcp-shared-v1-p30")

    assert profile.terraform_projection() == {
        "shared_service_capacity_profile": "gcp-shared-v1-p30",
        "access_machine_type": "e2-standard-8",
        "access_node_count": 3,
        "access_node_max_count": 8,
        "vpn_pool_machine_type": "e2-standard-2",
        "vpn_pool_min_vms": 3,
        "vpn_pool_max_vms": 6,
        "vpn_pool_cpu_target_pct": 30,
        "cloud_sql_tier": "db-custom-4-15360",
        "cloud_sql_availability_type": "REGIONAL",
        "cloud_sql_disk_size_gb": 60,
        "redis_tier": "STANDARD_HA",
        "redis_memory_size_gb": 8,
    }
    assert profile.gate_projection() == {
        "capacity_profile_id": "gcp-shared-v1-p30",
        "concurrency": 30,
        "ramp_seconds": 30,
        "hold_seconds": 120,
        "bootstrap_timeout_seconds": 90,
        "bootstrap_p95_ms": 5000,
        "bootstrap_p99_ms": 8000,
        "max_error_rate": 0.0,
        "required_guacd_replicas": 2,
        "guacd_max_cpu_pct": 80,
        "load_balancer_p95_ms": 2000,
        "telemetry_settle_seconds": 240,
        "redis_max_utilization_pct": 75,
        "cloud_sql_max_utilization_pct": 75,
    }


def test_p30_helm_projection_carries_real_resources_autoscaling_and_backends():
    helm = resolve_capacity_profile("gcp-shared-v1-p30").helm_projection()

    assert helm["portal"] == {
        "replicas": 5,
        "resources": {
            "requests": {"cpu": "500m", "memory": "2Gi", "ephemeral-storage": "256Mi"},
            "limits": {"cpu": "2", "memory": "4Gi", "ephemeral-storage": "256Mi"},
        },
        "autoscaling": {
            "enabled": True,
            "minReplicas": 5,
            "maxReplicas": 10,
            "cpuUtilizationPercentage": 65,
            "scaleDownStabilizationSeconds": 900,
        },
        "terminationGracePeriodSeconds": 330,
    }
    assert helm["guacd"]["autoscaling"] == {
        "enabled": True,
        "minReplicas": 2,
        "maxReplicas": 4,
        "cpuUtilizationPercentage": 65,
        "scaleDownStabilizationSeconds": 900,
    }
    assert helm["guacd"]["resources"]["limits"] == {
        "cpu": "2",
        "memory": "2Gi",
        "ephemeral-storage": "256Mi",
    }
    assert helm["guacamoleClient"]["resources"]["requests"] == {
        "cpu": "500m",
        "memory": "1Gi",
        "ephemeral-storage": "256Mi",
    }
    assert helm["services"] == {
        "portal": {"backendConfig": {"timeoutSec": 3600, "connectionDraining": {"drainingTimeoutSec": 300}}},
        "guacamoleClient": {"backendConfig": {"timeoutSec": 3600, "connectionDraining": {"drainingTimeoutSec": 300}}},
    }


def test_p30_drift_projection_covers_capacity_bearing_kubernetes_fields():
    state = resolve_capacity_profile("gcp-shared-v1-p30").desired_state()["kubernetes"]

    assert state["deployment/portal-web.spec.template.spec.terminationGracePeriodSeconds"] == 330
    assert state["deployment/guacd.spec.template.spec.containers.guacd.resources.requests.cpu"] == "500m"
    guacamole_env_key = (
        "deployment/guacamole-client.spec.template.spec.containers.guacamole-client.env."
        "POSTGRESQL_ABSOLUTE_MAX_CONNECTIONS"
    )
    assert state[guacamole_env_key] == "30"
    assert state["hpa/portal-web.spec.minReplicas"] == 5
    assert state["hpa/guacd.spec.maxReplicas"] == 4
    assert state["backendconfig/portal-web.spec.connectionDraining.drainingTimeoutSec"] == 300
    assert state["configmap/platform-runtime.data.PORTAL_WEB_WS_PING_INTERVAL"] == "30"


@pytest.mark.parametrize(
    ("profile_id", "minimum", "maximum"),
    [
        ("gcp-shared-v1-p10", 2, 4),
        ("gcp-shared-v1-p30", 3, 6),
        ("gcp-shared-v1-p50", 3, 6),
        ("gcp-shared-v1-p100", 5, 10),
        ("gcp-shared-v1-p200", 9, 18),
        ("gcp-shared-v1-p300", 13, 26),
        ("gcp-shared-v1-p500", 21, 42),
    ],
)
def test_the_openvpn_pool_keeps_a_spare_server_above_its_participant_plan(profile_id, minimum, maximum):
    # 25 participants per single-threaded OpenVPN server, plus one spare, never fewer than two (#2480).
    pool = resolve_capacity_profile(profile_id).vpn_pool
    assert (pool.minimum_vms, pool.maximum_vms, pool.cpu_utilization_pct) == (minimum, maximum, 30)


@pytest.mark.parametrize("profile_id", ["gcp-shared-v1-p200", "gcp-shared-v1-p300", "gcp-shared-v1-p500"])
def test_large_tiers_grow_the_single_guacamole_client_not_its_replica_count(profile_id):
    profile = resolve_capacity_profile(profile_id)
    assert profile.guacamole_client.replicas == 1
    assert profile.helm_projection()["guacamoleClient"]["replicas"] == 1
    assert profile.guacamole_client.absolute_tunnel_connections == profile.participant_count
    small = resolve_capacity_profile("gcp-shared-v1-p100").guacamole_client.resources.limits
    assert int(profile.guacamole_client.resources.limits.cpu) > int(small.cpu)


def test_a_sql_budget_above_the_default_connection_limit_is_rejected():
    profile = resolve_capacity_profile("gcp-shared-v1-p300")
    data = profile.model_dump()
    data["cloud_sql"]["connection_budget"] = 1300  # 120+ GB instances default to 1,000 connections

    with pytest.raises(ValueError, match="default max_connections"):
        GcpSharedServiceCapacityProfile.model_validate(data)
