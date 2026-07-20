"""ACES-native database readers for the Shifter Engine provisioner.

Split out of ``provisioner_db`` (Sonar S104). Owns the ACES-range and
image-registry reads used by the ``aces-range`` realization path (ADR-032).
"""

from __future__ import annotations

from typing import Any

from provisioner_db import get_db_connection


def get_aces_range_data_by_request_id(request_id: str) -> dict[str, Any]:
    """Read ACES-native range data: the serialized ACES plan + ids (ADR-032).

    Unlike :func:`get_range_data_by_request_id`, this does NOT run the cyberscript
    persisted-envelope unwrap or the NGFW attachment lookup: for the ACES-native
    path ``range_config`` is the serialized ACES ProvisioningPlan itself, returned
    verbatim as ``plan`` for the provisioner ``aces-range`` command to realize.
    """
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
                rng.instantiation_purpose
            FROM engine_request r
            JOIN mission_control_range rng ON rng.request_id = r.id
            WHERE r.request_id = %s
            """,
            (request_id,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError(f"Range request not found: {request_id}")

    return {
        "request_id": str(row[0]),
        "range_id": row[1],
        "user_id": row[2],
        "plan": row[3] if row[3] else {},
        "subnet_index": row[4],
        "status": row[5],
        # #1666 write-once ownership binding (NULL for legacy/non-GCP rows).
        "range_backend": row[6],
        "instantiation_purpose": row[7],
    }


def get_aces_content_delivery_bindings_by_request_id(request_id: str) -> list[dict[str, Any]]:
    """Read the #1564 delivery bindings realized for the range bound to a request.

    Byte-free identity rows only: content_address, sha256, storage_key,
    byte_count, binding_version. Returns an empty list when the range has no
    bindings (or does not exist) rather than raising, since an ACES plan may
    legitimately carry no source-backed content.
    """
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                b.content_address,
                b.resource_type,
                b.resource_address,
                b.payload_kind,
                b.install_policy,
                b.sha256,
                b.storage_key,
                b.byte_count,
                b.binding_version
            FROM engine_request r
            JOIN mission_control_range rng ON rng.request_id = r.id
            JOIN engine_aces_content_delivery_binding b ON b.range_id = rng.id
            WHERE r.request_id = %s
            """,
            (request_id,),
        )
        rows = cur.fetchall()

    bindings: list[dict[str, Any]] = []
    for row in rows:
        common = {
            "sha256": row[5],
            "storage_key": row[6],
            "byte_count": row[7],
            "binding_version": row[8],
        }
        if row[8] == 1:
            bindings.append({"content_address": row[0], **common})
        else:
            bindings.append(
                {
                    "resource_type": row[1],
                    "resource_address": row[2],
                    "payload_kind": row[3],
                    "install_policy": row[4],
                    **common,
                }
            )
    return bindings


def get_aces_image_candidates(provider: str, source_name: str) -> list[dict[str, Any]]:
    """Return enabled ACES image mappings for (provider, source_name) (ADR-032-R2).

    The tenant-managed image registry the provisioner resolves against at
    realization. Returns the candidate rows for a source name; the pure resolver
    (``aces_image_resolver``) applies the exact-version / any-version rules.
    """
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT source_version, image_ref, machine_type, disk_size_gb, disk_type
            FROM engine_aces_image_mapping
            WHERE provider = %s AND source_name = %s AND enabled = TRUE
            """,
            (provider, source_name),
        )
        rows = cur.fetchall()

    return [
        {
            "source_version": row[0],
            "image_ref": row[1],
            "machine_type": row[2],
            "disk_size_gb": row[3],
            "disk_type": row[4],
        }
        for row in rows
    ]
