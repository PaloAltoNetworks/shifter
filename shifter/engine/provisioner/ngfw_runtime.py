"""NGFW runtime helpers: polling, subnet config, route cleanup, state writes.

Extracted from ``main.py`` (Sonar S104). Owns the PAN-OS ``show system
info`` parsers, the post-boot serial/cert/autocommit poll loops, the
DB-write helper that backs NGFW lifecycle state, the configure /
remove subnet pipelines, the stale-route cleanup paths, and
``user_has_active_ranges``.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import psycopg
from psycopg import sql
from shared.operation_results import NGFW_STATE_KEYS, ResultStep

from events import (
    STATUS_DESTROYED,
    STATUS_FAILED,
    STATUS_PAUSED,
    STATUS_PROVISIONING,
    STATUS_READY,
)
from executors.ngfw_executor import NGFWExecutor
from log_redact import safe_log_fingerprint
from ngfw_polling import poll_for_serial_number, wait_for_autocommit
from orchestrators.setup_orchestrator import SetupOrchestrator
from plans.base import DynamicPlan, SetupPlan
from plans.ngfw_configure_subnets import NGFWConfigureSubnetsPlan, NGFWRemoveSubnetsPlan
from provisioner_db import get_db_connection
from provisioner_db_appends import OperationRef, append_operation_step_result
from provisioner_db_ngfw import get_user_ngfw_data

logger = logging.getLogger(__name__)


def update_instance_state(
    request_id: str,
    status: str,
    *,
    step: str,
    operation_id: str | None = None,
    operation: str | None = None,
    ngfw_state: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> None:
    """Report an NGFW lifecycle transition to the Engine result inbox.

    ADR-043 phase 4 (#1836): this no longer writes ``engine_instance`` or
    ``engine_app``. The Engine applier is the authoritative writer; this reports a
    closed, per-step result under the operation generation that authorized the
    work.

    ``**state_updates`` is gone deliberately. The old signature let any caller
    merge arbitrary keys -- including raw Terraform output -- into the persisted
    state. Only the normalized provider-neutral fields
    (``shared.operation_results.NGFW_STATE_KEYS``) travel now.

    Args:
        request_id: UUID string of the NGFW's Request.
        status: The reported status.
        step: The closed ``ResultStep`` this observation corresponds to.
        operation_id: ADR-043 canonical generation; absent on local-dev runs, in
            which case nothing is appended.
        operation: The owning operation (provision/deprovision/start/stop).
        ngfw_state: Normalized NGFW state to carry alongside the status.
        error_message: Bounded diagnostic, carried only on a failure step.
    """
    if operation_id is None or operation is None:
        logger.debug(
            "update_instance_state: no operation generation, skipping result append request_id=%s",
            request_id,
        )
        return

    if step == ResultStep.NGFW_TERMINAL_FAILED:
        payload: dict[str, Any] = {
            "reason_code": "cloud_operation_failed",
            "diagnostic": (error_message or "")[:512],
        }
    else:
        payload = {"ngfw_instance_uuid": _resolve_ngfw_instance_uuid(request_id), "status": status}
        if ngfw_state:
            payload["ngfw_state"] = {k: v for k, v in ngfw_state.items() if k in NGFW_STATE_KEYS}

    append_operation_step_result(
        OperationRef(request_id=request_id, operation_id=operation_id),
        resource="ngfw",
        operation=operation,
        step=step,
        result_payload=payload,
    )


def _resolve_ngfw_instance_uuid(request_id: str) -> str:
    """Return the UUID of the NGFW Instance for this request."""
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT i.uuid
            FROM engine_request r
            JOIN engine_instance i ON i.request_id = r.id
            WHERE r.request_id = %s
              AND i.role = 'ngfw'
            """,
            (request_id,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError(f"NGFW instance not found for request: {request_id}")
        return str(row[0])


def update_ngfw_attachment_state(request_id: str, attached_ranges: list[dict[str, Any]]) -> None:
    """Merge the range-attachment list into the NGFW Instance state.

    Attachment bookkeeping is not a lifecycle transition: it records which ranges
    currently use a shared NGFW. It therefore stays a direct write (it carries no
    operation generation) but is now scoped to ``engine_instance.state`` only.
    The previous path routed through ``update_instance_state`` and re-wrote the
    NGFW's *current* status onto both the Instance and its App -- a no-op status
    write whose only real effect was to require an ``engine_app`` UPDATE grant.
    """
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT i.id, i.state
                FROM engine_request r
                JOIN engine_instance i ON i.request_id = r.id
                WHERE r.request_id = %s
                  AND i.role = 'ngfw'
                """,
                (request_id,),
            )
            row = cur.fetchone()
            if not row:
                raise ValueError(f"NGFW instance not found for request: {request_id}")
            instance_id = row[0]
            state = row[1] if row[1] else {}
            state["attached_ranges"] = attached_ranges
            cur.execute(
                """
                UPDATE engine_instance
                SET state = %s, updated_at = NOW()
                WHERE id = %s
                """,
                (json.dumps(state), instance_id),
            )
        conn.commit()


def find_stale_routes_by_cidr(
    ssh_executor: NGFWExecutor,
    management_ip: str,
    target_cidrs: set[str],
) -> list[str]:
    """Find existing NGFW static routes that match target CIDRs."""
    query_cmd = "set cli pager off\nconfigure\nshow network virtual-router default routing-table ip static-route\nexit"
    try:
        result = ssh_executor.run_command(
            instance_id=management_ip,
            script="",
            stdin_input=query_cmd + "\nexit\n",
            timeout_seconds=30,
        )
    except Exception as e:
        logger.warning("Failed to query NGFW routes for cleanup: %s", e)
        return []

    if not result.success or not result.stdout:
        return []

    stale_routes = []
    route_pattern = re.compile(r"(range-\d+-\w+)\s*\{[^}]*destination\s+([\d./]+);", re.DOTALL)

    for match in route_pattern.finditer(result.stdout):
        route_name = match.group(1)
        cidr = match.group(2)
        if cidr in target_cidrs:
            logger.info(
                "Found stale route %s with CIDR %s - will delete",
                route_name,
                cidr,
            )
            stale_routes.append(route_name)

    return stale_routes


def find_stale_routes_by_db(
    ssh_executor: NGFWExecutor,
    management_ip: str,
    current_range_id: int,
) -> list[str]:
    """Find NGFW routes belonging to destroyed/failed ranges via DB lookup."""
    query_cmd = "set cli pager off\nconfigure\nshow network virtual-router default routing-table ip static-route\nexit"
    try:
        result = ssh_executor.run_command(
            instance_id=management_ip,
            script="",
            stdin_input=query_cmd + "\nexit\n",
            timeout_seconds=30,
        )
    except Exception as e:
        logger.warning("Failed to query NGFW routes for DB cleanup check: %s", e)
        result = None

    if not result or not result.success or not result.stdout:
        return []

    route_pattern = re.compile(r"(range-(\d+)-\w+)\s*\{")
    routes_by_range: dict[int, list[str]] = {}

    for match in route_pattern.finditer(result.stdout):
        route_name = match.group(1)
        range_id = int(match.group(2))
        if range_id != current_range_id:
            if range_id not in routes_by_range:
                routes_by_range[range_id] = []
            routes_by_range[range_id].append(route_name)

    if not routes_by_range:
        return []

    range_ids = list(routes_by_range.keys())
    stale_routes: list[str] = []

    try:
        with get_db_connection() as conn, conn.cursor() as cur:
            query = sql.SQL("""
                SELECT id FROM mission_control_range
                WHERE id IN ({})
                AND status NOT IN (%s, %s)
                """).format(sql.SQL(", ").join(sql.Placeholder() * len(range_ids)))
            cur.execute(query, [*range_ids, STATUS_DESTROYED, STATUS_FAILED])
            active_range_ids = {row[0] for row in cur.fetchall()}

        for range_id, routes in routes_by_range.items():
            if range_id not in active_range_ids:
                logger.info(
                    "Found %d stale routes for range %d (destroyed/failed/missing)",
                    len(routes),
                    range_id,
                )
                stale_routes.extend(routes)

    except psycopg.Error as e:
        logger.warning("Failed to query DB for stale routes: %s", e)
        stale_routes = []

    return stale_routes


def configure_ngfw_subnets(
    subnets: list[dict[str, Any]],
    range_id: int,
    management_ip: str,
    ssh_key_secret_arn: str,
    route_next_hop_ip: str,
    ssm_endpoints_subnet_cidr: str = "",
) -> None:
    """Configure NGFW with routes for range subnets."""
    logger.info(
        "Configuring NGFW: %d subnets, next_hop_fp=%s",
        len(subnets),
        safe_log_fingerprint(route_next_hop_ip),
    )

    from cloud import get_secrets_store

    secrets = get_secrets_store()
    private_key = secrets.get_secret(ssh_key_secret_arn)

    ssh_executor = NGFWExecutor(private_key=private_key)

    logger.info("Waiting for SSH on NGFW at host_fp=%s...", safe_log_fingerprint(management_ip))
    ssh_executor.wait_for_agent(host=management_ip, timeout_seconds=300)

    logger.info("Verifying NGFW management plane is ready...")
    poll_for_serial_number(
        ssh_executor=ssh_executor,
        host=management_ip,
        timeout_seconds=300,
        poll_interval=15,
    )

    logger.info("Waiting for NGFW autocommit to complete...")
    wait_for_autocommit(
        ssh_executor=ssh_executor,
        host=management_ip,
        # 10 min max for autocommit
        timeout_seconds=600,
        poll_interval=15,
    )

    target_cidrs = {s["cidr"] for s in subnets if s.get("cidr")}
    stale_by_cidr = find_stale_routes_by_cidr(ssh_executor, management_ip, target_cidrs)
    stale_by_db = find_stale_routes_by_db(ssh_executor, management_ip, range_id)

    stale_routes = list(set(stale_by_cidr + stale_by_db))
    if stale_routes:
        logger.info(
            "Found %d stale routes to clean up: %s (cidr=%d, db=%d)",
            len(stale_routes),
            stale_routes,
            len(stale_by_cidr),
            len(stale_by_db),
        )

    steps = NGFWConfigureSubnetsPlan().get_steps(
        subnets,
        range_id,
        route_next_hop_ip,
        stale_routes,
        ssm_endpoints_subnet_cidr,
    )
    plan: SetupPlan = DynamicPlan(name="ngfw_configure_subnets", steps=steps)

    orchestrator = SetupOrchestrator(ssh_executor)
    logger.info("Running NGFW subnet configuration via SetupOrchestrator...")
    result = orchestrator.orchestrate(
        instance_id=management_ip,
        plan=plan,
        context={},
    )

    if not result.success:
        raise RuntimeError(f"NGFW subnet configuration failed: {result.error or 'unknown error'}")

    logger.info(
        "NGFW configuration complete for range %s (%d subnets)",
        range_id,
        len(subnets),
    )


def remove_ngfw_subnets(user_id: int, subnets: list[dict[str, Any]], range_id: int) -> None:
    """Remove subnet addresses and security rules from user's NGFW."""
    ngfw_data = get_user_ngfw_data(user_id)
    if not ngfw_data:
        logger.warning("User %s has no NGFW, skipping subnet removal", user_id)
        return

    ngfw_request_id = ngfw_data["ngfw_request_id"]
    management_ip = ngfw_data["management_ip"]
    ssh_key_secret_arn = ngfw_data["ssh_key_secret_arn"]
    status = ngfw_data["status"]

    if not management_ip or not ssh_key_secret_arn:
        logger.warning("NGFW missing management_ip or ssh_key, skipping removal")
        return

    if status == STATUS_PAUSED:
        logger.error(
            "NGFW is paused during range destroy - this should never happen! "
            "range_id=%s user_id=%s ngfw_request_id=%s. Skipping NGFW cleanup.",
            range_id,
            user_id,
            ngfw_request_id,
        )
        return

    from cloud import get_secrets_store

    secrets = get_secrets_store()
    private_key = secrets.get_secret(ssh_key_secret_arn)

    ssh_executor = NGFWExecutor(private_key=private_key)
    logger.info("Waiting for SSH on NGFW at host_fp=%s...", safe_log_fingerprint(management_ip))
    ssh_executor.wait_for_agent(host=management_ip, timeout_seconds=300)

    logger.info("Verifying NGFW management plane is ready...")
    poll_for_serial_number(
        ssh_executor=ssh_executor,
        host=management_ip,
        # 5 min - should be quick since NGFW is running
        timeout_seconds=300,
        poll_interval=15,
    )

    has_endpoints = bool(os.environ.get("SSM_ENDPOINTS_SUBNET_CIDR"))
    steps = NGFWRemoveSubnetsPlan().get_steps(subnets, range_id, has_endpoints)
    plan: SetupPlan = DynamicPlan(name="ngfw_remove_subnets", steps=steps)

    orchestrator = SetupOrchestrator(ssh_executor)
    logger.info("Running NGFW subnet removal via SetupOrchestrator...")
    result = orchestrator.orchestrate(
        instance_id=management_ip,
        plan=plan,
        context={},
    )

    if not result.success:
        raise RuntimeError(f"NGFW subnet removal failed: {result.error or 'unknown error'}")

    logger.info("NGFW subnet removal complete for range %s", range_id)


def user_has_active_ranges(user_id: int, exclude_range_id: int) -> bool:
    """Check if user has any active ranges besides the one being destroyed."""
    logger.debug("user_has_active_ranges: user_id=%s exclude_range_id=%s", user_id, exclude_range_id)
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM mission_control_range
            WHERE user_id = %s
              AND id != %s
              AND status IN (%s, %s)
            """,
            (user_id, exclude_range_id, STATUS_READY, STATUS_PROVISIONING),
        )
        row = cur.fetchone()
        count = row[0] if row else 0
        logger.debug("user_has_active_ranges: found %d active ranges", count)
        return count > 0
