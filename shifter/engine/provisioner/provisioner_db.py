"""Database access helpers for the Shifter Engine provisioner.

Extracted from ``main.py`` (Sonar S104). Owns the psycopg connection
factory, the range/instance state writers, and the range lookup helpers
that the rest of the provisioner needs to translate request IDs into
Range metadata.

The NGFW-specific read/write helpers (``get_user_ngfw_data``,
``get_ngfw_data_by_request_id``, and the range-attachment record helpers)
were split out into ``provisioner_db_ngfw.py``, and the ACES-native readers
into ``provisioner_db_aces.py``, to keep this module under the Sonar S104
line budget.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import psycopg
from psycopg import sql
from shared.remote_access import parse_openvpn_binding

from config import has_ngfw_attachment_state
from log_redact import safe_log_fingerprint
from state_helpers import (
    _build_instance_state,
    _build_provisioned_instance_payload,
    _build_subnet_state,
    _get_cloud_provider,
)

logger = logging.getLogger(__name__)


def get_db_connection() -> psycopg.Connection:
    """Get database connection.

    Supports two authentication modes:
    - If DB_PASSWORD is set: Uses standard password authentication (local dev)
    - Otherwise: Uses RDS IAM authentication (ECS/production)
    """
    db_host = os.environ.get("DB_HOST")
    db_port = int(os.environ.get("DB_PORT", 5432))
    db_user = os.environ.get("DB_USER")
    db_name = os.environ.get("DB_NAME")
    db_password = os.environ.get("DB_PASSWORD")

    if db_password:
        if not all([db_host, db_user, db_name]):
            missing = [
                k
                for k, v in [
                    ("DB_HOST", db_host),
                    ("DB_USER", db_user),
                    ("DB_NAME", db_name),
                ]
                if not v
            ]
            raise RuntimeError(f"Missing env vars: {', '.join(missing)}")

        logger.debug("get_db_connection: password auth to %s:%s/%s", db_host, db_port, db_name)
        return psycopg.connect(
            host=db_host,
            port=db_port,
            dbname=db_name,
            user=db_user,
            password=db_password,
        )

    cloud_region = os.environ.get("CLOUD_REGION") or os.environ.get("AWS_REGION")
    if not all([db_host, db_user, db_name, cloud_region]):
        missing = [
            k
            for k, v in [
                ("DB_HOST", db_host),
                ("DB_USER", db_user),
                ("DB_NAME", db_name),
                ("CLOUD_REGION", cloud_region),
            ]
            if not v
        ]
        raise RuntimeError(f"Missing env vars: {', '.join(missing)}")

    logger.debug("get_db_connection: cloud IAM auth to %s:%s/%s", db_host, db_port, db_name)
    # validated above
    assert db_host is not None
    # validated above
    assert db_user is not None
    from cloud import get_db_auth

    auth = get_db_auth()
    token = auth.generate_auth_token(
        hostname=db_host,
        port=db_port,
        username=db_user,
    )
    return psycopg.connect(
        host=db_host,
        port=db_port,
        dbname=db_name,
        user=db_user,
        password=token,
        sslmode="require",
    )


def _append_kwarg_assignment(assignments: list[Any], values: list[Any], key: str, value: str | int | None) -> None:
    """Append one SET-clause fragment for an UPDATE, handling NOW() specially."""
    if value == "NOW()":
        assignments.append(sql.SQL("{} = NOW()").format(sql.Identifier(key)))
        return
    assignments.append(sql.SQL("{} = %s").format(sql.Identifier(key)))
    values.append(value)


def enqueue_event_outbox(event: dict[str, object], *, cur: psycopg.Cursor[tuple[object, ...]] | None = None) -> None:
    """Insert an event into the transactional outbox for durable delivery.

    When ``cur`` is provided the INSERT is executed on that cursor and the
    caller owns the surrounding transaction/commit (atomic with the state
    change).  When ``cur`` is None a new connection is opened, the row is
    inserted, and the connection is committed immediately.

    Uses ON CONFLICT (event_id) DO NOTHING so the call is idempotent.

    Args:
        event: Full event dict; must contain ``event_id`` and ``event_type``.
        cur:   Optional psycopg cursor sharing the caller's transaction.

    Raises:
        Exception: Any DB error is re-raised — callers must learn when durable
            recording fails.
    """
    _insert_sql = """
        INSERT INTO engine_range_event_outbox
            (event_id, event_type, payload, status, attempts, max_attempts,
             next_attempt_at, created_at)
        VALUES
            (%s, %s, %s, 'PENDING', 0, 10, NOW(), NOW())
        ON CONFLICT (event_id) DO NOTHING
    """
    params = (str(event["event_id"]), event["event_type"], json.dumps(event))

    if cur is not None:
        cur.execute(_insert_sql, params)
    else:
        with get_db_connection() as conn:
            with conn.cursor() as _cur:
                _cur.execute(_insert_sql, params)
            conn.commit()


def update_range_status(
    range_id: int,
    status: str,
    outbox_event: dict | None = None,
    **kwargs: str | int | None,
) -> None:
    """Update range status in database.

    Args:
        range_id:     Primary key of the Range.
        status:       New status string.
        outbox_event: Optional event dict to insert into the outbox atomically
                      with the status update.  When provided, the INSERT and
                      the UPDATE commit in the same transaction.
        **kwargs:     Additional column=value pairs for the UPDATE SET clause.
    """
    logger.debug("update_range_status: range_id=%s status=%s kwargs=%s", range_id, status, list(kwargs.keys()))
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            assignments = [
                sql.SQL("{} = %s").format(sql.Identifier("status")),
                sql.SQL("{} = NOW()").format(sql.Identifier("updated_at")),
            ]
            values: list[Any] = [status]

            for key, value in kwargs.items():
                if value is None:
                    continue
                _append_kwarg_assignment(assignments, values, key, value)

            values.append(range_id)
            query = sql.SQL("UPDATE mission_control_range SET {} WHERE id = %s").format(sql.SQL(", ").join(assignments))
            cur.execute(query, values)

            if outbox_event is not None:
                enqueue_event_outbox(outbox_event, cur=cur)
        conn.commit()


def _write_subnet_states(
    cur: psycopg.Cursor[tuple[object, ...]],
    range_id: int,
    subnets: dict[str, dict[str, Any]],
    provider: str,
) -> None:
    """Mark each provisioned subnet ready and persist its provider state."""
    for subnet_name, subnet_data in subnets.items():
        subnet_uuid = subnet_data.get("uuid")
        if not subnet_uuid:
            logger.warning(
                "Subnet subnet_fp=%s missing UUID, skipping DB write",
                safe_log_fingerprint(subnet_name),
            )
            continue

        state = _build_subnet_state(subnet_data, provider=provider)

        cur.execute(
            """
            UPDATE engine_subnet
            SET state = %s, status = 'ready'
            WHERE uuid = %s AND range_id = %s
            """,
            (json.dumps(state), subnet_uuid, range_id),
        )
        if cur.rowcount == 0:
            raise ValueError(f"No engine_subnet record found for uuid={subnet_uuid}, range_id={range_id}")
        logger.debug("Updated engine_subnet state: subnet_fp=%s", safe_log_fingerprint(subnet_uuid))


def _write_instance_states(
    cur: psycopg.Cursor[tuple[object, ...]],
    instances: list[dict[str, Any]],
    provider: str,
) -> list[dict[str, Any]]:
    """Mark each provisioned instance ready and return its closed payloads."""
    provisioned_instances: list[dict[str, Any]] = []
    for inst in instances:
        instance_uuid = inst.get("uuid")
        if not instance_uuid:
            logger.warning(
                "Instance (role_fp=%s) missing UUID, skipping DB write",
                safe_log_fingerprint(inst.get("role", "unknown")),
            )
            continue

        instance_state = _build_instance_state(inst, provider=provider)

        cur.execute(
            """
            UPDATE engine_instance
            SET status = 'ready', state = %s
            WHERE uuid = %s
            """,
            (json.dumps(instance_state), instance_uuid),
        )
        if cur.rowcount == 0:
            raise ValueError(f"No engine_instance record found for uuid={instance_uuid}")
        logger.debug("Updated engine_instance state: instance_fp=%s", safe_log_fingerprint(instance_uuid))

        provisioned_instances.append(_build_provisioned_instance_payload(inst, provider=provider))
    return provisioned_instances


def write_provisioned_state(
    range_id: int,
    subnets: dict[str, dict[str, Any]],
    instances: list[dict[str, Any]],
    ngfw_instance_id: int | None = None,
    vpn_access_binding: dict[str, object] | None = None,
    outbox_event: dict | None = None,
) -> None:
    """Write provisioned infrastructure state directly to database.

    Args:
        range_id:        Primary key of the Range.
        subnets:         Mapping of subnet name → subnet data dict.
        instances:       List of instance data dicts.
        ngfw_instance_id: FK to the NGFW Instance, if any.
        vpn_access_binding: Closed non-secret OpenVPN result, if supported.
        outbox_event:    Optional event dict to insert into the outbox
                         atomically with the state writes.
    """
    if vpn_access_binding is not None:
        # Reject extensions (especially accidental credential/profile fields)
        # before opening a DB transaction. Only the closed ref-only contract is
        # eligible for persistence.
        parse_openvpn_binding(vpn_access_binding)
    provider = _get_cloud_provider()
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            _write_subnet_states(cur, range_id, subnets, provider)
            provisioned_instances = _write_instance_states(cur, instances, provider)

            cur.execute(
                """
                UPDATE mission_control_range
                SET provisioned_instances = %s,
                    vpn_access_binding = %s,
                    ngfw_instance_id = %s,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (
                    json.dumps(provisioned_instances),
                    json.dumps(vpn_access_binding) if vpn_access_binding is not None else None,
                    ngfw_instance_id,
                    range_id,
                ),
            )
            if cur.rowcount == 0:
                raise ValueError(f"No mission_control_range record found for id={range_id}")
            logger.debug(
                "Updated Range.provisioned_instances: range_id=%s count=%d",
                range_id,
                len(provisioned_instances),
            )

            if outbox_event is not None:
                enqueue_event_outbox(outbox_event, cur=cur)

        conn.commit()
    logger.info(
        "Wrote provisioned state to DB: range_id=%s subnets=%d instances=%d",
        range_id,
        len(subnets),
        len(instances),
    )


def mark_range_instances_destroyed(range_id: int) -> tuple[int, int]:
    """Mark all engine_instance and engine_subnet records for a range as destroyed."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE engine_instance
                SET status = 'destroyed', destroyed_at = NOW()
                WHERE uuid IN (
                    SELECT DISTINCT i.uuid
                    FROM engine_instance i
                    JOIN engine_request r ON i.request_id = r.id
                    JOIN mission_control_range rng ON rng.request_id = r.id
                    WHERE rng.id = %s
                )
                """,
                (range_id,),
            )
            instance_count = cur.rowcount
            logger.debug(
                "Marked %d engine_instance records as destroyed for range_id=%s",
                instance_count,
                range_id,
            )

            cur.execute(
                """
                UPDATE engine_subnet
                SET status = 'destroyed', destroyed_at = NOW()
                WHERE range_id = %s
                """,
                (range_id,),
            )
            subnet_count = cur.rowcount
            logger.debug(
                "Marked %d engine_subnet records as destroyed for range_id=%s",
                subnet_count,
                range_id,
            )

            cur.execute(
                """
                UPDATE mission_control_range
                SET vpn_access_binding = NULL, updated_at = NOW()
                WHERE id = %s
                """,
                (range_id,),
            )
            if cur.rowcount == 0:
                raise ValueError(f"No mission_control_range record found for id={range_id}")

        conn.commit()
    logger.info(
        "Marked engine records as destroyed: range_id=%s instances=%d subnets=%d",
        range_id,
        instance_count,
        subnet_count,
    )
    return instance_count, subnet_count


def _update_range_config(range_id: int, range_spec: dict[str, Any]) -> None:
    """Write updated range_config back to mission_control_range."""
    from cyberscript.persisted_envelope import ensure_wrapped_persisted_spec

    wrapped = ensure_wrapped_persisted_spec("range_spec", range_spec)
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE mission_control_range SET range_config = %s WHERE id = %s",
            (json.dumps(wrapped), range_id),
        )
        conn.commit()
    logger.info("Persisted updated range_config for range %d", range_id)


def get_range_data_by_request_id(request_id: str) -> dict[str, Any]:
    """Read Range request data from Engine database."""
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                r.request_id,
                rng.id AS range_id,
                rng.user_id,
                rng.range_config,
                rng.subnet_index,
                rng.status,
                rng.range_backend,
                rng.instantiation_purpose,
                rng.remote_access_capability
            FROM engine_request r
            JOIN mission_control_range rng ON rng.request_id = r.id
            WHERE r.request_id = %s
            """,
            (request_id,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError(f"Range request not found: {request_id}")

        range_config_raw = row[3] if row[3] else {}
        from cyberscript.persisted_envelope import unwrap_persisted_spec

        range_config = unwrap_persisted_spec(range_config_raw)
        user_id = row[2]
        ngfw_instance_id = None

        if range_config.get("ngfw", False):
            cur.execute(
                """
                SELECT ei.id, ei.state
                FROM engine_instance ei
                JOIN engine_request er ON ei.request_id = er.id
                WHERE er.user_id = %s
                  AND ei.role = 'ngfw'
                  AND ei.status IN ('ready', 'paused', 'pausing', 'resuming')
                ORDER BY ei.created_at DESC
                LIMIT 1
                """,
                (user_id,),
            )
            ngfw_row = cur.fetchone()
            if ngfw_row and has_ngfw_attachment_state(ngfw_row[1]):
                ngfw_instance_id = ngfw_row[0]

        return {
            "request_id": str(row[0]),
            "range_id": row[1],
            "user_id": user_id,
            "spec": range_config,
            "spec_envelope": range_config_raw,
            "subnet_index": row[4],
            "status": row[5],
            "ngfw_instance_id": ngfw_instance_id,
            # #1666 write-once ownership binding (NULL for legacy/non-GCP rows).
            # Destroy/reconcile route from these persisted facts, never the
            # deploy-wide GCP_RANGE_BACKEND selector.
            "range_backend": row[6],
            "instantiation_purpose": row[7],
            "remote_access_capability": row[8],
        }
