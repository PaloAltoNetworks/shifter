"""Provisioner_db append helpers for the async-processing tables.

Split out of ``provisioner_db.py`` (Sonar S104), following the same convention as
``provisioner_db_ngfw.py``. Owns the transactional,
optional-cursor append helpers for the two async-processing tables the provisioner
writes to:

* ``engine_operation_result_inbox`` (ADR-043 Phase 2, #1834) via
  :func:`append_operation_result` for the remaining CyberScript compatibility
  path and :func:`append_operation_step_result` for cut-over families.

Both ride the caller's cursor when one is supplied or open a dedicated connection
and commit otherwise. The unstepped append is a best-effort shadow of the direct
SQL writes performed by
``provisioner_db.write_provisioned_state`` /
``provisioner_db.mark_range_instances_destroyed``. The stepped append is the
fail-hard authoritative write for cut-over families; Engine applies its validated
result to domain state, audit, and notifications in one transaction.

``OperationRef`` is the parameter object that carries the operation identity
(request + canonical generation) so leaf writers thread one value instead of a
pair of loose primitives.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import psycopg
from shared.enums import ResourceStatus
from shared.operation_envelope import build_operation_envelope, canonical_payload_digest
from shared.operation_results import build_result_identity, parse_result_payload, result_kind_for

from log_redact import safe_log_fingerprint

logger = logging.getLogger(__name__)

_OPERATION_RESULT_APPEND_FAILED = "operation_result_inbox_append_failed"
_OPERATION_RESULT_CONFLICT = "operation_result_inbox_conflict"


@dataclass(frozen=True)
class OperationRef:
    """Identity of one provisioner operation generation (ADR-043, #1834).

    ``operation_id`` is ``None`` on local-dev runs / commands not yet carrying a
    canonical generation; the shadow append is skipped entirely in that case.
    """

    request_id: str
    operation_id: str | None = None


_APPEND_OPERATION_RESULT_INSERT_SQL = """
    INSERT INTO engine_operation_result_inbox
        (operation_id, request_id, resource, operation, contract_version,
         result_kind, result_step, result_identity, payload_digest, envelope,
         disposition, disposition_detail, created_at)
    VALUES
        (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'PENDING', '', NOW())
    ON CONFLICT (result_identity) DO NOTHING
"""


def _insert_operation_result(
    cur: psycopg.Cursor[tuple[object, ...]],
    *,
    params: tuple[object, ...],
) -> None:
    """Issue the idempotent INSERT.

    Replay/conflict resolution deliberately does NOT read the inbox back: the
    provisioner principal is granted ``INSERT`` only (engine migration 0036), so a
    ``SELECT`` here raises under real grants. Instead the identity carries the
    payload digest, which makes the two cases separable without a read:

    * identical replay -> identical identity -> ``ON CONFLICT DO NOTHING``;
    * conflicting replay -> different identity -> a second row for the same
      ``(operation_id, result_step)``, which the applier (which may read)
      dispositions as ``REJECTED_CONFLICT``.
    """
    cur.execute(_APPEND_OPERATION_RESULT_INSERT_SQL, params)


def append_operation_result(
    *,
    operation_id: str,
    request_id: str,
    resource: str,
    operation: str,
    result_kind: str,
    result_payload: dict[str, Any],
    cur: psycopg.Cursor[tuple[object, ...]] | None = None,
) -> None:
    """Append a best-effort, versioned result to the operation result inbox.

    When ``cur`` is provided the INSERT rides the caller's transaction (wrapped in
    a SAVEPOINT so a shadow failure cannot poison it); when ``cur`` is None a
    dedicated connection is opened and committed immediately.

    ``result_identity`` is deterministic per operation generation + result kind
    (``f"{operation_id}:{result_kind}"``), so a retried provisioner run replays
    idempotently. Any failure is logged and swallowed, never raised.

    This is the **shadow** helper, for families whose authoritative writer is
    still direct provisioner SQL (cyberscript range provision/destroy). Families
    that have cut over use :func:`append_operation_step_result`, which is
    fail-hard because the append *is* the write.
    """
    try:
        envelope = build_operation_envelope(
            operation_id=operation_id,
            request_id=request_id,
            resource=resource,
            operation=operation,
            payload=result_payload,
        )
        digest = canonical_payload_digest(result_payload)
        params = (
            envelope["operation_id"],
            envelope["request_id"],
            resource,
            operation,
            envelope["contract_version"],
            result_kind,
            "",
            f"{envelope['operation_id']}:{result_kind}",
            digest,
            json.dumps(envelope),
        )
        _write_append(params, cur, savepoint=True)
    except Exception:
        logger.warning(
            "%s operation_id_fp=%s result_kind=%s",
            _OPERATION_RESULT_APPEND_FAILED,
            safe_log_fingerprint(str(operation_id)),
            result_kind,
            exc_info=True,
        )


def _write_append(
    params: tuple[object, ...],
    cur: psycopg.Cursor[tuple[object, ...]] | None,
    *,
    savepoint: bool,
) -> None:
    """Execute the append on the caller's cursor or a dedicated connection."""
    if cur is not None:
        if savepoint:
            # A shadow failure must not poison the caller's authoritative write.
            with cur.connection.transaction():
                _insert_operation_result(cur, params=params)
        else:
            # Authoritative: the append shares the caller's transaction outright,
            # so a failure fails the operation rather than being isolated away.
            _insert_operation_result(cur, params=params)
        return

    # Lazy import breaks the provisioner_db <-> provisioner_db_appends cycle:
    # provisioner_db re-exports these helpers, so it may not be imported at this
    # module's top.
    from provisioner_db import get_db_connection

    with get_db_connection() as conn:
        with conn.cursor() as _cur:
            _insert_operation_result(_cur, params=params)
        conn.commit()


def append_operation_step_result(
    ref: OperationRef | None,
    *,
    resource: str,
    operation: str,
    step: str,
    result_payload: dict[str, Any],
    cur: psycopg.Cursor[tuple[object, ...]] | None = None,
) -> None:
    """Append an **authoritative** operation result for a cut-over family.

    Unlike :func:`append_operation_result` this does not swallow failures: after
    cutover the append is the write, so a failure must fail the operation and let
    the existing task retry/re-drive recover it. It also validates the payload
    against the closed contract before insert, so a malformed result is caught at
    the producer rather than dispositioned at the applier.

    Skips entirely when no canonical generation is present (local dev / a caller
    not yet threading an operation id), matching the existing helpers.
    """
    if ref is None or ref.operation_id is None:
        return

    parsed = parse_result_payload(resource, operation, step=step, payload=result_payload)
    envelope = build_operation_envelope(
        operation_id=ref.operation_id,
        request_id=ref.request_id,
        resource=resource,
        operation=operation,
        payload=parsed,
    )
    digest = canonical_payload_digest(envelope["payload"])
    params = (
        envelope["operation_id"],
        envelope["request_id"],
        resource,
        operation,
        envelope["contract_version"],
        result_kind_for(resource, operation, step=step),
        str(step),
        build_result_identity(operation_id=envelope["operation_id"], step=step, digest=digest),
        digest,
        json.dumps(envelope),
    )
    _write_append(params, cur, savepoint=False)


def append_range_provision_result(
    cur: psycopg.Cursor[tuple[object, ...]],
    ref: OperationRef | None,
    *,
    range_id: int,
    subnet_count: int,
    instance_count: int,
    ngfw_instance_id: int | None,
) -> None:
    """Shadow-append the terminal-success result of a range provision."""
    if ref is None or ref.operation_id is None:
        return
    append_operation_result(
        operation_id=ref.operation_id,
        request_id=ref.request_id,
        resource="range",
        operation="provision",
        result_kind="TERMINAL_SUCCESS",
        result_payload={
            "status": ResourceStatus.READY.value,
            "range_id": range_id,
            "subnet_count": subnet_count,
            "instance_count": instance_count,
            "ngfw_instance_id": ngfw_instance_id,
        },
        cur=cur,
    )


def append_range_destroy_result(
    cur: psycopg.Cursor[tuple[object, ...]],
    ref: OperationRef | None,
    *,
    range_id: int,
    instance_count: int,
    subnet_count: int,
) -> None:
    """Shadow-append the terminal-success result of a range destroy."""
    if ref is None or ref.operation_id is None:
        return
    append_operation_result(
        operation_id=ref.operation_id,
        request_id=ref.request_id,
        resource="range",
        operation="destroy",
        result_kind="TERMINAL_SUCCESS",
        result_payload={
            "status": ResourceStatus.DESTROYED.value,
            "range_id": range_id,
            "instances_destroyed": instance_count,
            "subnets_destroyed": subnet_count,
        },
        cur=cur,
    )
