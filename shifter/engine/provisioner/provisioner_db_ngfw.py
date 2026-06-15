"""NGFW-specific database access helpers for the Shifter Engine provisioner.

Extracted from ``provisioner_db.py`` (Sonar S104) to keep the NGFW
range-attachment read/write helpers in a focused module.
"""

from __future__ import annotations

from typing import Any

from config import resolve_ngfw_attachment_config
from provisioner_db import get_db_connection
from state_helpers import _get_cloud_provider


def get_user_ngfw_data(user_id: int) -> dict[str, Any] | None:
    """Get NGFW data for a user (if they have one provisioned)."""
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                r.request_id,
                i.state,
                i.status
            FROM engine_instance i
            JOIN engine_request r ON i.request_id = r.id
            WHERE r.user_id = %s
              AND i.role = 'ngfw'
              AND i.status IN ('ready', 'paused', 'pausing', 'resuming')
            ORDER BY i.created_at DESC
            LIMIT 1
            """,
            (user_id,),
        )
        row = cur.fetchone()
        if not row:
            return None

        request_id = str(row[0])
        state = row[1] if row[1] else {}
        status = row[2]
        attachment = resolve_ngfw_attachment_config(state)

        return {
            "ngfw_request_id": request_id,
            "cloud_provider": attachment.cloud_provider,
            "ec2_instance_id": state.get("ec2_instance_id"),
            "management_ip": attachment.management_ip,
            "ssh_key_secret_arn": attachment.ssh_key_secret_ref,
            "ssh_key_secret_ref": attachment.ssh_key_secret_ref,
            "dataplane_ip": attachment.dataplane_ip,
            "route_next_hop_ip": attachment.route_next_hop_ip,
            "data_eni_id": attachment.data_attachment_id,
            "data_attachment_id": attachment.data_attachment_id,
            "attachment_mode": attachment.attachment_mode,
            "provider_metadata": attachment.provider_metadata,
            "attached_ranges": state.get("attached_ranges", []),
            "status": status,
        }


def _build_ngfw_range_attachment_record(
    *,
    range_id: int,
    request_id: str,
    subnets: list[dict[str, Any]],
    ngfw_data: dict[str, Any],
) -> dict[str, Any]:
    """Build the persisted attachment record for a range bound to an NGFW."""
    return {
        "range_id": range_id,
        "request_id": request_id,
        "cloud_provider": _get_cloud_provider(),
        "attachment_mode": ngfw_data.get("attachment_mode", ""),
        "route_next_hop_ip": ngfw_data.get("route_next_hop_ip", ""),
        "data_attachment_id": ngfw_data.get("data_attachment_id", ""),
        "subnets": [
            {
                "name": subnet.get("name", ""),
                "cidr": subnet.get("cidr", ""),
                "connected_to": list(subnet.get("connected_to", [])),
                "provider_metadata": subnet.get("provider_metadata", {}),
            }
            for subnet in subnets
        ],
    }


def _record_ngfw_range_attachment(
    *,
    ngfw_request_id: str,
    ngfw_status: str,
    attachment_record: dict[str, Any],
) -> None:
    """Merge the current range attachment into the NGFW instance state."""
    from ngfw_runtime import update_instance_state

    ngfw_data = get_ngfw_data_by_request_id(ngfw_request_id)
    current_state = ngfw_data.get("state") or {}
    current_attachments = list(current_state.get("attached_ranges") or [])
    current_attachments = [
        attachment
        for attachment in current_attachments
        if attachment.get("range_id") != attachment_record.get("range_id")
    ]
    current_attachments.append(attachment_record)
    update_instance_state(
        ngfw_request_id,
        ngfw_status,
        attached_ranges=current_attachments,
    )


def _remove_ngfw_range_attachment(
    *,
    ngfw_request_id: str,
    ngfw_status: str,
    range_id: int,
) -> None:
    """Remove a range attachment from the NGFW instance state."""
    from ngfw_runtime import update_instance_state

    ngfw_data = get_ngfw_data_by_request_id(ngfw_request_id)
    current_state = ngfw_data.get("state") or {}
    current_attachments = list(current_state.get("attached_ranges") or [])
    remaining_attachments = [attachment for attachment in current_attachments if attachment.get("range_id") != range_id]
    update_instance_state(
        ngfw_request_id,
        ngfw_status,
        attached_ranges=remaining_attachments,
    )


def get_ngfw_data_by_request_id(request_id: str) -> dict[str, Any]:
    """Read NGFW request and instance data from Engine database."""
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                r.request_id,
                i.uuid AS instance_id,
                a.uuid AS app_id,
                i.spec,
                a.spec AS app_spec,
                i.state,
                i.status
            FROM engine_request r
            JOIN engine_instance i ON i.request_id = r.id
            LEFT JOIN engine_app a ON a.instance_id = i.id
            WHERE r.request_id = %s
              AND i.role = 'ngfw'
            """,
            (request_id,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError(f"NGFW request not found: {request_id}")
        return {
            "request_id": str(row[0]),
            "instance_id": str(row[1]),
            "app_id": str(row[2]) if row[2] else None,
            "spec": row[3] if row[3] else {},
            "app_spec": row[4] if row[4] else {},
            "state": row[5] if row[5] else {},
            "status": row[6],
        }
