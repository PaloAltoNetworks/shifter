"""Versioned GCP shared-service event-capacity contracts (#1816).

The catalog in this module is the only authored definition of an event size.
Consumers resolve one immutable entry and project it into Terraform, Helm, the
public-path gate, and drift inspection.  The projections intentionally contain
only non-secret deployment policy.
"""

from __future__ import annotations

from typing import Annotated, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .capacity_profile_invariants_gcp import validate_profile_invariants

CapacityProfileId = Literal[
    "gcp-shared-v1-p10",
    "gcp-shared-v1-p30",
    "gcp-shared-v1-p50",
    "gcp-shared-v1-p100",
    "gcp-shared-v1-p200",
    "gcp-shared-v1-p300",
    "gcp-shared-v1-p500",
]

_K8S_QUANTITY = r"^(?:[1-9][0-9]*(?:m|Ki|Mi|Gi|Ti)?|0\.[0-9]+)$"
KubernetesQuantity = Annotated[str, Field(pattern=_K8S_QUANTITY)]


class _ClosedModel(BaseModel):
    """Immutable base model that rejects undeclared capacity fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ResourceQuantity(_ClosedModel):
    """CPU, memory, and ephemeral-storage quantities for one resource scope."""

    cpu: KubernetesQuantity
    memory: KubernetesQuantity
    ephemeral_storage: KubernetesQuantity = "256Mi"

    def helm(self) -> dict[str, str]:
        return {
            "cpu": self.cpu,
            "memory": self.memory,
            "ephemeral-storage": self.ephemeral_storage,
        }


class WorkloadResources(_ClosedModel):
    """Kubernetes request and limit quantities for one workload container."""

    requests: ResourceQuantity
    limits: ResourceQuantity

    def helm(self) -> dict[str, dict[str, str]]:
        return {"requests": self.requests.helm(), "limits": self.limits.helm()}


class AutoscalingPolicy(_ClosedModel):
    """Horizontal pod autoscaling bounds and stabilization policy."""

    enabled: bool = True
    min_replicas: int = Field(ge=1)
    max_replicas: int = Field(ge=1)
    cpu_utilization_pct: int = Field(ge=20, le=90)
    scale_down_stabilization_seconds: int = Field(ge=300, le=3600)

    @model_validator(mode="after")
    def validate_bounds(self) -> AutoscalingPolicy:
        if self.max_replicas < self.min_replicas:
            raise ValueError("autoscaling maximum must be at least its minimum")
        return self

    def helm(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "minReplicas": self.min_replicas,
            "maxReplicas": self.max_replicas,
            "cpuUtilizationPercentage": self.cpu_utilization_pct,
            "scaleDownStabilizationSeconds": self.scale_down_stabilization_seconds,
        }


class PortalCapacity(_ClosedModel):
    """Portal replicas, process concurrency, resources, and autoscaling policy."""

    replicas: int = Field(ge=1)
    resources: WorkloadResources
    web_workers: int = Field(ge=1, le=32)
    bootstrap_workers: int = Field(ge=1, le=32)
    autoscaling: AutoscalingPolicy


class GuacdCapacity(_ClosedModel):
    """Guacd replicas, resources, and autoscaling policy."""

    replicas: int = Field(ge=1)
    resources: WorkloadResources
    autoscaling: AutoscalingPolicy


class GuacamoleClientCapacity(_ClosedModel):
    """Guacamole web client resources and database connection ceiling."""

    replicas: Literal[1] = 1
    resources: WorkloadResources
    jdbc_pool_active_connections: Literal[10] = 10
    absolute_tunnel_connections: int = Field(ge=1, le=1000)


class CloudSqlCapacity(_ClosedModel):
    """Cloud SQL sizing, availability, connection, and utilization limits."""

    tier: str = Field(pattern=r"^db-custom-[1-9][0-9]*-[1-9][0-9]*$")
    availability_type: Literal["ZONAL", "REGIONAL"]
    disk_size_gb: int = Field(ge=20, description="Minimum disk size; Cloud SQL storage is non-shrinking")
    connection_budget: int = Field(ge=20)
    reserved_connections: int = Field(ge=5)
    max_utilization_pct: int = Field(ge=25, le=90)


class RedisCapacity(_ClosedModel):
    """Memorystore sizing, availability, connection, and utilization limits."""

    tier: Literal["BASIC", "STANDARD_HA"]
    memory_size_gb: int = Field(ge=1)
    connection_budget: int = Field(ge=20)
    max_utilization_pct: int = Field(ge=25, le=90)


class AccessNodeCapacity(_ClosedModel):
    """GKE access-node machine type and autoscaling bounds."""

    machine_type: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)+$")
    minimum_nodes: int = Field(ge=1)
    maximum_nodes: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_bounds(self) -> AccessNodeCapacity:
        if self.maximum_nodes < self.minimum_nodes:
            raise ValueError("access-node maximum must be at least its minimum")
        return self


class VpnPoolCapacity(_ClosedModel):
    """Shared participant OpenVPN pool sizing (#2480).

    One OpenVPN 2.x process is single-threaded and uses one core. The plan is
    25 participants per 2-vCPU server: 25 x 3 Mbps (interactive RDP plus SSH)
    is about 75 Mbps, roughly 40% of one core at OpenVPN's published 12 MHz per
    Mbps. The minimum adds one spare server (and never drops below two) so a
    server can fail or be replaced without exceeding the plan. The CPU target
    is 30% of the VM because a saturated OpenVPN core shows as only 50%.
    """

    machine_type: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)+$")
    minimum_vms: int = Field(ge=2)
    maximum_vms: int = Field(ge=2)
    cpu_utilization_pct: int = Field(ge=10, le=45)

    @model_validator(mode="after")
    def validate_bounds(self) -> VpnPoolCapacity:
        if self.maximum_vms < self.minimum_vms:
            raise ValueError("VPN pool maximum must be at least its minimum")
        return self


class TimeoutCapacity(_ClosedModel):
    """Coordinated backend, WebSocket, process, pod, and drain timeouts."""

    portal_backend_seconds: int = Field(ge=60)
    guacamole_backend_seconds: int = Field(ge=60)
    websocket_ping_interval_seconds: int = Field(ge=5)
    websocket_ping_timeout_seconds: int = Field(ge=5)
    process_graceful_timeout_seconds: int = Field(ge=30)
    pod_termination_grace_seconds: int = Field(ge=30)
    connection_draining_seconds: int = Field(ge=30)


class GateCapacity(_ClosedModel):
    """Public-path load target and pass/fail thresholds for an event tier."""

    concurrency: int = Field(ge=1)
    ramp_seconds: int = Field(ge=0)
    hold_seconds: int = Field(ge=60)
    bootstrap_timeout_seconds: int = Field(ge=30)
    bootstrap_p95_ms: int = Field(ge=100)
    bootstrap_p99_ms: int = Field(ge=100)
    max_error_rate: float = Field(ge=0, le=1)
    required_guacd_replicas: int = Field(ge=1)
    guacd_max_cpu_pct: int = Field(ge=25, le=95)
    load_balancer_p95_ms: int = Field(ge=100)
    telemetry_settle_seconds: int = Field(ge=0, le=600)


class GcpSharedServiceCapacityProfile(_ClosedModel):
    """Immutable cross-layer capacity contract for one GCP event tier."""

    profile_id: CapacityProfileId
    participant_count: Literal[10, 30, 50, 100, 200, 300, 500]
    portal: PortalCapacity
    guacd: GuacdCapacity
    guacamole_client: GuacamoleClientCapacity
    cloud_sql: CloudSqlCapacity
    redis: RedisCapacity
    access_nodes: AccessNodeCapacity
    vpn_pool: VpnPoolCapacity
    timeouts: TimeoutCapacity
    gate: GateCapacity

    @model_validator(mode="after")
    def validate_coupled_limits(self) -> GcpSharedServiceCapacityProfile:
        """Validate invariants that couple otherwise independent profile sections."""
        validate_profile_invariants(self)
        return self

    def terraform_projection(self) -> dict[str, object]:
        return {
            "shared_service_capacity_profile": self.profile_id,
            "access_machine_type": self.access_nodes.machine_type,
            "access_node_count": self.access_nodes.minimum_nodes,
            "access_node_max_count": self.access_nodes.maximum_nodes,
            "vpn_pool_machine_type": self.vpn_pool.machine_type,
            "vpn_pool_min_vms": self.vpn_pool.minimum_vms,
            "vpn_pool_max_vms": self.vpn_pool.maximum_vms,
            "vpn_pool_cpu_target_pct": self.vpn_pool.cpu_utilization_pct,
            "cloud_sql_tier": self.cloud_sql.tier,
            "cloud_sql_availability_type": self.cloud_sql.availability_type,
            "cloud_sql_disk_size_gb": self.cloud_sql.disk_size_gb,
            "redis_tier": self.redis.tier,
            "redis_memory_size_gb": self.redis.memory_size_gb,
        }

    def helm_projection(self) -> dict[str, object]:
        return {
            "capacityProfile": {"id": self.profile_id, "participants": self.participant_count},
            "portal": {
                "replicas": self.portal.replicas,
                "resources": self.portal.resources.helm(),
                "autoscaling": self.portal.autoscaling.helm(),
                "terminationGracePeriodSeconds": self.timeouts.pod_termination_grace_seconds,
            },
            "guacd": {
                "replicas": self.guacd.replicas,
                "resources": self.guacd.resources.helm(),
                "autoscaling": self.guacd.autoscaling.helm(),
                "terminationGracePeriodSeconds": self.timeouts.pod_termination_grace_seconds,
            },
            "guacamoleClient": {
                "replicas": 1,
                "resources": self.guacamole_client.resources.helm(),
                "terminationGracePeriodSeconds": self.timeouts.pod_termination_grace_seconds,
                "postgresqlAbsoluteMaxConnections": self.guacamole_client.absolute_tunnel_connections,
            },
            "runtimeEnv": {
                "SHARED_SERVICE_CAPACITY_PROFILE": self.profile_id,
                "PORTAL_WEB_WORKERS": str(self.portal.web_workers),
                "GUACAMOLE_BOOTSTRAP_WORKERS": str(self.portal.bootstrap_workers),
                "PORTAL_WEB_WS_PING_INTERVAL": str(self.timeouts.websocket_ping_interval_seconds),
                "PORTAL_WEB_WS_PING_TIMEOUT": str(self.timeouts.websocket_ping_timeout_seconds),
                "PORTAL_WEB_GRACEFUL_TIMEOUT": str(self.timeouts.process_graceful_timeout_seconds),
            },
            "services": {
                "portal": {
                    "backendConfig": {
                        "timeoutSec": self.timeouts.portal_backend_seconds,
                        "connectionDraining": {"drainingTimeoutSec": self.timeouts.connection_draining_seconds},
                    }
                },
                "guacamoleClient": {
                    "backendConfig": {
                        "timeoutSec": self.timeouts.guacamole_backend_seconds,
                        "connectionDraining": {"drainingTimeoutSec": self.timeouts.connection_draining_seconds},
                    }
                },
            },
        }

    def gate_projection(self) -> dict[str, object]:
        return {
            "capacity_profile_id": self.profile_id,
            **self.gate.model_dump(mode="json"),
            "redis_max_utilization_pct": self.redis.max_utilization_pct,
            "cloud_sql_max_utilization_pct": self.cloud_sql.max_utilization_pct,
        }

    def desired_state(self) -> dict[str, object]:
        terraform = self.terraform_projection()
        kubernetes: dict[str, object] = {}
        for deployment, replicas, resources in (
            ("portal-web", self.portal.replicas, self.portal.resources),
            ("guacd", self.guacd.replicas, self.guacd.resources),
            ("guacamole-client", 1, self.guacamole_client.resources),
        ):
            container = "portal" if deployment == "portal-web" else deployment
            prefix = f"deployment/{deployment}"
            kubernetes[f"{prefix}.metadata.annotations.shifter.dev/capacity-profile"] = self.profile_id
            kubernetes[f"{prefix}.spec.replicas"] = replicas
            kubernetes[f"{prefix}.spec.template.spec.terminationGracePeriodSeconds"] = (
                self.timeouts.pod_termination_grace_seconds
            )
            for scope in ("requests", "limits"):
                quantity = getattr(resources, scope)
                resource_prefix = f"{prefix}.spec.template.spec.containers.{container}.resources.{scope}"
                kubernetes[f"{resource_prefix}.cpu"] = quantity.cpu
                kubernetes[f"{resource_prefix}.memory"] = quantity.memory

        kubernetes[
            "deployment/guacamole-client.spec.template.spec.containers.guacamole-client.env."
            "POSTGRESQL_ABSOLUTE_MAX_CONNECTIONS"
        ] = str(self.guacamole_client.absolute_tunnel_connections)
        for deployment, policy in (
            ("portal-web", self.portal.autoscaling),
            ("guacd", self.guacd.autoscaling),
        ):
            kubernetes[f"hpa/{deployment}.spec.minReplicas"] = policy.min_replicas
            kubernetes[f"hpa/{deployment}.spec.maxReplicas"] = policy.max_replicas
        for backend, timeout in (
            ("portal-web", self.timeouts.portal_backend_seconds),
            ("guacamole-client", self.timeouts.guacamole_backend_seconds),
        ):
            kubernetes[f"backendconfig/{backend}.spec.timeoutSec"] = timeout
            kubernetes[f"backendconfig/{backend}.spec.connectionDraining.drainingTimeoutSec"] = (
                self.timeouts.connection_draining_seconds
            )
        runtime_env = cast(dict[str, object], self.helm_projection()["runtimeEnv"])
        for key, value in runtime_env.items():
            kubernetes[f"configmap/platform-runtime.data.{key}"] = value
        return {
            "profile_id": self.profile_id,
            "terraform": {
                f"capacity.{key}": value for key, value in terraform.items() if key != "shared_service_capacity_profile"
            },
            "kubernetes": kubernetes,
        }


def _resources(request_cpu: str, request_memory: str, limit_cpu: str, limit_memory: str) -> WorkloadResources:
    """Build one workload resource request/limit pair."""
    return WorkloadResources(
        requests=ResourceQuantity(cpu=request_cpu, memory=request_memory),
        limits=ResourceQuantity(cpu=limit_cpu, memory=limit_memory),
    )


_VPN_PARTICIPANTS_PER_SERVER = 25


def _vpn_pool(count: int) -> VpnPoolCapacity:
    """Size the OpenVPN pool for one participant tier (basis on VpnPoolCapacity)."""
    minimum = max(2, -(-count // _VPN_PARTICIPANTS_PER_SERVER) + 1)
    return VpnPoolCapacity(
        machine_type="e2-standard-2",
        minimum_vms=minimum,
        maximum_vms=max(minimum + 2, minimum * 2),
        cpu_utilization_pct=30,
    )


# Tiers above 100 continue the p50 -> p100 marginal rates: about 0.12 portal and
# 0.08 guacd replicas per participant; access nodes (e2-standard-8) cover the
# minimum replicas' CPU limits with ~10% headroom and the autoscaling maximum's
# limits with ~10% headroom; Cloud SQL keeps 3.75 GiB per vCPU; Redis grows
# ~0.16 GiB per participant. Each connection budget stays near 80% of Cloud SQL's
# default max_connections for the tier's memory (1,000 at 120 GB and above), and
# the larger tiers' portal contexts (8 per replica) plus reserves fit inside it.
_TIER_SIZES: dict[int, tuple[int, int, int, int, str, Literal["ZONAL", "REGIONAL"], int, int]] = {
    10: (2, 1, 2, 4, "db-custom-2-7680", "ZONAL", 2, 100),
    30: (5, 2, 3, 8, "db-custom-4-15360", "REGIONAL", 8, 200),
    50: (8, 4, 4, 12, "db-custom-8-30720", "REGIONAL", 12, 350),
    100: (14, 8, 6, 20, "db-custom-16-61440", "REGIONAL", 20, 650),
    200: (26, 16, 12, 24, "db-custom-32-122880", "REGIONAL", 32, 800),
    300: (38, 24, 18, 36, "db-custom-48-184320", "REGIONAL", 48, 800),
    500: (62, 40, 28, 57, "db-custom-64-245760", "REGIONAL", 80, 800),
}

# guacamole-client stays at exactly one replica (#928 token affinity), and every
# participant's display stream passes through it, so the larger tiers give that
# single pod more CPU and memory instead of more replicas.
_GUACAMOLE_CLIENT_RESOURCES: dict[int, tuple[str, str, str, str]] = {
    200: ("1", "2Gi", "4", "4Gi"),
    300: ("2", "3Gi", "6", "6Gi"),
    500: ("2", "4Gi", "8", "8Gi"),
}
_GUACAMOLE_CLIENT_DEFAULT_RESOURCES = ("500m", "1Gi", "2", "2Gi")


def _build_profile(count: Literal[10, 30, 50, 100, 200, 300, 500]) -> GcpSharedServiceCapacityProfile:
    """Build one immutable catalog entry from its supported participant tier."""
    portal_replicas, guacd_replicas, access_nodes, access_max, sql_tier, sql_ha, redis_gb, sql_budget = _TIER_SIZES[
        count
    ]
    return GcpSharedServiceCapacityProfile(
        profile_id=cast(CapacityProfileId, f"gcp-shared-v1-p{count}"),
        participant_count=count,
        portal=PortalCapacity(
            replicas=portal_replicas,
            resources=_resources("500m", "2Gi", "2", "4Gi"),
            web_workers=4,
            bootstrap_workers=4,
            autoscaling=AutoscalingPolicy(
                min_replicas=portal_replicas,
                max_replicas=max(portal_replicas + 2, portal_replicas * 2),
                cpu_utilization_pct=65,
                scale_down_stabilization_seconds=900,
            ),
        ),
        guacd=GuacdCapacity(
            replicas=guacd_replicas,
            resources=_resources("500m", "1Gi", "2", "2Gi"),
            autoscaling=AutoscalingPolicy(
                min_replicas=guacd_replicas,
                max_replicas=max(guacd_replicas + 2, guacd_replicas * 2),
                cpu_utilization_pct=65,
                scale_down_stabilization_seconds=900,
            ),
        ),
        guacamole_client=GuacamoleClientCapacity(
            resources=_resources(*_GUACAMOLE_CLIENT_RESOURCES.get(count, _GUACAMOLE_CLIENT_DEFAULT_RESOURCES)),
            absolute_tunnel_connections=count,
        ),
        cloud_sql=CloudSqlCapacity(
            tier=sql_tier,
            availability_type=sql_ha,
            disk_size_gb=max(20, count * 2),
            connection_budget=sql_budget,
            reserved_connections=20,
            max_utilization_pct=75,
        ),
        redis=RedisCapacity(
            tier="STANDARD_HA",
            memory_size_gb=redis_gb,
            connection_budget=max(100, portal_replicas * 16),
            max_utilization_pct=75,
        ),
        access_nodes=AccessNodeCapacity(
            machine_type="e2-standard-8",
            minimum_nodes=access_nodes,
            maximum_nodes=access_max,
        ),
        vpn_pool=_vpn_pool(count),
        timeouts=TimeoutCapacity(
            portal_backend_seconds=3600,
            guacamole_backend_seconds=3600,
            websocket_ping_interval_seconds=30,
            websocket_ping_timeout_seconds=30,
            process_graceful_timeout_seconds=300,
            pod_termination_grace_seconds=330,
            connection_draining_seconds=300,
        ),
        gate=GateCapacity(
            concurrency=count,
            ramp_seconds=max(10, count),
            hold_seconds=120,
            bootstrap_timeout_seconds=90,
            bootstrap_p95_ms=5000,
            bootstrap_p99_ms=8000,
            max_error_rate=0,
            required_guacd_replicas=guacd_replicas,
            guacd_max_cpu_pct=80,
            load_balancer_p95_ms=2000,
            telemetry_settle_seconds=240,
        ),
    )


CAPACITY_PROFILES: dict[CapacityProfileId, GcpSharedServiceCapacityProfile] = {
    profile.profile_id: profile
    for profile in (
        _build_profile(10),
        _build_profile(30),
        _build_profile(50),
        _build_profile(100),
        _build_profile(200),
        _build_profile(300),
        _build_profile(500),
    )
}


def resolve_capacity_profile(profile_id: str) -> GcpSharedServiceCapacityProfile:
    """Resolve one known profile id or fail closed with the supported catalog."""
    try:
        return CAPACITY_PROFILES[profile_id]  # type: ignore[index]
    except KeyError as exc:
        known = ", ".join(sorted(CAPACITY_PROFILES))
        raise ValueError(f"unknown shared-service capacity profile {profile_id!r}; expected one of: {known}") from exc
