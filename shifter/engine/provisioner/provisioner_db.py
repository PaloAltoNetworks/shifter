"""Database access helpers for the Shifter Engine provisioner.

Extracted from ``main.py`` (Sonar S104). Owns the psycopg connection
factory, the range/instance state writers, and the range lookup helpers
that the rest of the provisioner needs to translate request IDs into
Range metadata.

The NGFW-specific read/write helpers (``get_user_ngfw_data``,
``get_ngfw_data_by_request_id``, and the range-attachment record helpers)
were split out into ``provisioner_db_ngfw.py`` to keep this module under the
Sonar S104 line budget; ``main`` re-exports both modules' surfaces so the
``main.<name>`` call sites and ``patch("main.update_instance_state")`` test
seams are unchanged.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import psycopg
from psycopg import sql

from config import has_ngfw_attachment_state
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


def update_range_status(range_id: int, status: str, **kwargs: str | int | None) -> None:
    """Update range status in database."""
    import main

    logger.debug("update_range_status: range_id=%s status=%s kwargs=%s", range_id, status, list(kwargs.keys()))
    with main.get_db_connection() as conn:
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
        conn.commit()


def write_provisioned_state(
    range_id: int,
    subnets: dict[str, dict[str, Any]],
    instances: list[dict[str, Any]],
    ngfw_instance_id: int | None = None,
) -> None:
    """Write provisioned infrastructure state directly to database."""
    import main

    provider = _get_cloud_provider()
    with main.get_db_connection() as conn:
        with conn.cursor() as cur:
            for subnet_name, subnet_data in subnets.items():
                subnet_uuid = subnet_data.get("uuid")
                if not subnet_uuid:
                    logger.warning("Subnet %s missing UUID, skipping DB write", subnet_name)
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
                logger.debug("Updated engine_subnet state: uuid=%s", subnet_uuid)

            provisioned_instances = []
            for inst in instances:
                instance_uuid = inst.get("uuid")
                if not instance_uuid:
                    logger.warning(
                        "Instance (role=%s) missing UUID, skipping DB write",
                        inst.get("role", "unknown"),
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
                logger.debug("Updated engine_instance state: uuid=%s", instance_uuid)

                provisioned_instances.append(_build_provisioned_instance_payload(inst, provider=provider))

            cur.execute(
                """
                UPDATE mission_control_range
                SET provisioned_instances = %s, ngfw_instance_id = %s, updated_at = NOW()
                WHERE id = %s
                """,
                (json.dumps(provisioned_instances), ngfw_instance_id, range_id),
            )
            if cur.rowcount == 0:
                raise ValueError(f"No mission_control_range record found for id={range_id}")
            logger.debug(
                "Updated Range.provisioned_instances: range_id=%s count=%d",
                range_id,
                len(provisioned_instances),
            )

        conn.commit()
    logger.info(
        "Wrote provisioned state to DB: range_id=%s subnets=%d instances=%d",
        range_id,
        len(subnets),
        len(instances),
    )


def mark_range_instances_destroyed(range_id: int) -> tuple[int, int]:
    """Mark all engine_instance and engine_subnet records for a range as destroyed."""
    import main

    with main.get_db_connection() as conn:
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
    import main

    with main.get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE mission_control_range SET range_config = %s WHERE id = %s",
            (json.dumps(range_spec), range_id),
        )
        conn.commit()
    logger.info("Persisted updated range_config for range %d", range_id)


def get_range_data_by_request_id(request_id: str) -> dict[str, Any]:
    """Read Range request data from Engine database."""
    import main

    with main.get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                r.request_id,
                rng.id AS range_id,
                rng.user_id,
                rng.range_config,
                rng.subnet_index,
                rng.status
            FROM engine_request r
            JOIN mission_control_range rng ON rng.request_id = r.id
            WHERE r.request_id = %s
            """,
            (request_id,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError(f"Range request not found: {request_id}")

        range_config = row[3] if row[3] else {}
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
            "subnet_index": row[4],
            "status": row[5],
            "ngfw_instance_id": ngfw_instance_id,
        }
