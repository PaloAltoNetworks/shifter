"""ACES-native range lifecycle entry for the provisioner ``aces-range`` command.

Parallel to ``terraform_ops.run_range_terraform`` but for the ACES-native path
(ADR-031, default off behind the platform feature flag). It reads the serialized
ACES plan persisted in ``range_config``, realizes it into a real GCE range cell,
and publishes range lifecycle status through the neutral event seam. It performs
no cyberscript scenario setup, NGFW attachment, subnet-CIDR allocation, or Vertex
credential management -- those are cyberscript/participant concerns.

Image/sizing is resolved at realization from the authored ACES source against the
tenant-managed registry (ADR-032-R2): the resolver is wired to
``get_aces_image_candidates`` + the pure ``resolve_gce_image`` policy.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from aces_gce_image import resolve_gce_image
from aces_gcp_apply import apply_aces_range_cell, destroy_aces_range_cell
from aces_plan import AcesPlanNode, parse_plan
from aces_snapshot import snapshot_resources
from config import GCERangeImageProfile
from events import (
    publish_aces_operation,
    publish_aces_snapshot,
    publish_destroyed,
    publish_failed,
    publish_ready,
    publish_status_update,
)
from log_redact import safe_log_value
from provisioner_db_aces import (
    get_aces_content_delivery_bindings_by_request_id,
    get_aces_image_candidates,
    get_aces_range_data_by_request_id,
)

logger = logging.getLogger(__name__)

#: Registry provider key for the GCE realization backend (engine_aces_image_mapping).
_GCE_REGISTRY_PROVIDER = "gce"


def _registry_resolver() -> Callable[[AcesPlanNode], GCERangeImageProfile]:
    """Return an image resolver bound to the tenant registry + GCE policy."""

    def resolve(node: AcesPlanNode) -> GCERangeImageProfile:
        """Resolve one node's image profile from the registry (authored source, else os_family)."""
        # Authored source keys the lookup; a source-less node falls back to its
        # os_family so the backend can supply a base OS image (ADR-032 base-OS policy).
        name = (node.image.name if node.image and node.image.name else node.os_family) or ""
        candidates = get_aces_image_candidates(_GCE_REGISTRY_PROVIDER, name) if name else []
        return resolve_gce_image(node, candidates)

    return resolve


def run_aces_range_provision(request_id: str) -> None:
    """Realize the serialized ACES plan for a request into a real GCE range cell.

    Range lifecycle status is driven by the neutral ``publish_*`` events; the ACES
    sidecar operation_status + runtime_snapshot records are emitted additively
    (``publish_aces_operation``/``publish_aces_snapshot``) for the redacted MC ACES
    read seams (#1478). ``operation_id`` is ``str(request_id)`` to match #1444's receipt.
    The byte-free #1564 content-delivery bindings for this range are read once
    here and threaded through to ``apply_aces_range_cell``, which gates on and
    realizes any source-backed content delivery.
    """
    data = get_aces_range_data_by_request_id(request_id)
    range_id = data["range_id"]
    user_id = data["user_id"]
    operation_id = str(request_id)
    logger.info("Starting ACES range provision for request_id=%s", request_id)
    publish_status_update(request_id=request_id, range_id=range_id, user_id=user_id, new_status="provisioning")
    publish_aces_operation(
        request_id=request_id, range_id=range_id, user_id=user_id, operation_id=operation_id, status="running"
    )
    try:
        aces_plan = parse_plan(data["plan"])
        delivery_bindings = get_aces_content_delivery_bindings_by_request_id(request_id)
        apply_aces_range_cell(
            request_id, range_id, aces_plan, _registry_resolver(), delivery_bindings=delivery_bindings
        )
    except Exception as exc:
        error_msg = str(exc)[:1000]
        logger.exception("ACES range provision failed: %s", error_msg)
        publish_aces_operation(
            request_id=request_id,
            range_id=range_id,
            user_id=user_id,
            operation_id=operation_id,
            status="failed",
            status_reason=safe_log_value(error_msg),
        )
        publish_failed(request_id=request_id, range_id=range_id, user_id=user_id, error_message=error_msg)
        raise
    publish_aces_snapshot(
        request_id=request_id,
        range_id=range_id,
        user_id=user_id,
        operation_id=operation_id,
        resources=snapshot_resources(aces_plan),
    )
    publish_aces_operation(
        request_id=request_id, range_id=range_id, user_id=user_id, operation_id=operation_id, status="succeeded"
    )
    publish_ready(request_id=request_id, range_id=range_id, user_id=user_id)


def run_aces_range_destroy(request_id: str) -> None:
    """Tear down every GCE resource owned by an ACES range cell for a request."""
    data = get_aces_range_data_by_request_id(request_id)
    range_id = data["range_id"]
    user_id = data["user_id"]
    operation_id = str(request_id)
    logger.info("Starting ACES range destroy for request_id=%s", request_id)
    publish_aces_operation(
        request_id=request_id, range_id=range_id, user_id=user_id, operation_id=operation_id, status="running"
    )
    try:
        aces_plan = parse_plan(data["plan"])
        destroy_aces_range_cell(request_id, range_id, aces_plan)
    except Exception as exc:
        error_msg = str(exc)[:1000]
        logger.exception("ACES range destroy failed: %s", error_msg)
        publish_aces_operation(
            request_id=request_id,
            range_id=range_id,
            user_id=user_id,
            operation_id=operation_id,
            status="failed",
            status_reason=safe_log_value(error_msg),
        )
        publish_failed(request_id=request_id, range_id=range_id, user_id=user_id, error_message=error_msg)
        raise
    publish_aces_operation(
        request_id=request_id, range_id=range_id, user_id=user_id, operation_id=operation_id, status="succeeded"
    )
    publish_destroyed(request_id=request_id, range_id=range_id, user_id=user_id)
