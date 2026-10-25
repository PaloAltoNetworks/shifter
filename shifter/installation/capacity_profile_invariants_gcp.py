"""Invariants that couple sections of a GCP shared-service capacity profile (#1816).

Each check holds for every catalog entry; the profile model runs them all after
field validation, so an incoherent profile can never be resolved.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .capacity_profiles_gcp import GcpSharedServiceCapacityProfile


def validate_profile_invariants(profile: GcpSharedServiceCapacityProfile) -> None:
    """Raise ``ValueError`` when any cross-section invariant does not hold."""
    _validate_profile_identity(profile)
    _validate_ready_replica_floors(profile)
    _validate_timeout_ordering(profile)
    _validate_connection_budgets(profile)
    _validate_sql_default_connection_limit(profile)
    _validate_gate_replica_floor(profile)


def _validate_profile_identity(profile: GcpSharedServiceCapacityProfile) -> None:
    """Require the profile suffix, participant count, and gate target to agree."""
    expected_count = int(profile.profile_id.rsplit("p", 1)[1])
    if expected_count != profile.participant_count or profile.gate.concurrency != profile.participant_count:
        raise ValueError("profile identity, participant count, and gate concurrency must agree")


def _validate_ready_replica_floors(profile: GcpSharedServiceCapacityProfile) -> None:
    """Require ready replicas to carry the gate before autoscaling reacts."""
    if profile.portal.autoscaling.min_replicas != profile.portal.replicas:
        raise ValueError("portal minimum replicas must carry the gate before autoscaling")
    if profile.guacd.autoscaling.min_replicas != profile.guacd.replicas:
        raise ValueError("guacd minimum replicas must carry the gate before autoscaling")


def _validate_timeout_ordering(profile: GcpSharedServiceCapacityProfile) -> None:
    """Require heartbeat, drain, process, and pod timeouts to remain ordered."""
    timeouts = profile.timeouts
    cadence = timeouts.websocket_ping_interval_seconds + timeouts.websocket_ping_timeout_seconds
    if cadence >= min(timeouts.portal_backend_seconds, timeouts.guacamole_backend_seconds):
        raise ValueError("WebSocket cadence must remain below both public backend timeouts")
    if timeouts.pod_termination_grace_seconds < timeouts.connection_draining_seconds:
        raise ValueError("pod termination grace must cover connection draining")
    if timeouts.pod_termination_grace_seconds <= timeouts.process_graceful_timeout_seconds:
        raise ValueError("pod termination grace must exceed the process graceful timeout")


def _validate_connection_budgets(profile: GcpSharedServiceCapacityProfile) -> None:
    """Require SQL and Redis budgets to cover all configured process contexts."""
    portal_contexts = profile.portal.replicas * (profile.portal.web_workers + profile.portal.bootstrap_workers)
    required_sql = (
        portal_contexts + profile.guacamole_client.jdbc_pool_active_connections + profile.cloud_sql.reserved_connections
    )
    if profile.cloud_sql.connection_budget < required_sql:
        raise ValueError("SQL connection budget does not cover portal, Guacamole, and reserve contexts")
    required_redis = profile.portal.replicas * profile.portal.web_workers * 2
    if profile.redis.connection_budget < required_redis:
        raise ValueError("Redis connection budget does not cover portal processes and reconnect headroom")


def _validate_gate_replica_floor(profile: GcpSharedServiceCapacityProfile) -> None:
    """Require the public-path gate to demand no more guacd pods than ready."""
    if profile.gate.required_guacd_replicas > profile.guacd.replicas:
        raise ValueError("gate requires more guacd replicas than the ready minimum")


# Cloud SQL for PostgreSQL default max_connections by instance memory (GB), from
# Google's "Configure database flags" reference: the profile does not set the
# flag, so a budget above the default would promise connections the server
# refuses.
_SQL_DEFAULT_MAX_CONNECTIONS = ((120, 1000), (60, 800), (30, 600), (15, 500), (7.5, 400), (6, 200), (3.75, 100))


def _validate_sql_default_connection_limit(profile: GcpSharedServiceCapacityProfile) -> None:
    """Require the SQL connection budget to fit Cloud SQL's default limit for the tier's memory."""
    match = re.fullmatch(r"db-custom-\d+-(\d+)", profile.cloud_sql.tier)
    if match is None:
        raise ValueError("Cloud SQL tier must be a db-custom-<vcpu>-<memory MB> machine type")
    memory_gb = int(match.group(1)) / 1024
    default_limit = next((limit for floor, limit in _SQL_DEFAULT_MAX_CONNECTIONS if memory_gb >= floor), 50)
    if profile.cloud_sql.connection_budget > default_limit:
        raise ValueError(
            f"SQL connection budget {profile.cloud_sql.connection_budget} exceeds the tier's default "
            f"max_connections of {default_limit}"
        )
