"""Runner for range infrastructure operations.

AWS ranges still use Terraform-backed infrastructure modules. GCP routes to an
explicit provider-native backend: the closed GCE VM range-cell request or the
retained GDC path. Neither uses the retired Compute Engine Terraform module.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from shared.range_cells import is_gcp_vm_range_cell_request
from shared.range_instantiation_policy import InstantiationPurpose, evaluate_gcp_backend_admission

import gcp_range_cells
import gdc_range_networks
import gdc_scenario_pods
import gdc_vmruntime_assets
import terraform_base
from cloud.exceptions import CloudError, CloudProviderNotImplementedError
from config import get_gcp_range_backend, resolve_cloud_provider

AWS_RANGE_MODULE_PATH = Path(__file__).parent / "terraform" / "modules" / "range"

_LABEL = "Range"


def _get_provider() -> str:
    return resolve_cloud_provider()


def get_range_module_path() -> Path:
    """Return the provider-specific range Terraform module path."""
    provider = _get_provider()
    if provider == "gcp":
        raise RuntimeError(
            "Active GCP range provisioning targets a provider-native runner and does not expose a "
            "Terraform module path. Call apply_range()/destroy_range() for the provider-routed path."
        )
    if provider == "aws":
        return AWS_RANGE_MODULE_PATH
    raise CloudProviderNotImplementedError(provider)


def _resolve_backend(backend: str | None) -> str:
    """Return the routing backend for a GCP operation (#1666).

    When ``backend`` is given (the per-operation ownership binding resolved at
    operation start from the persisted Range), route from it. When it is ``None``
    (the provision path and non-GCP callers) fall back to the deploy-wide
    ``GCP_RANGE_BACKEND`` env selector. Bound destroy/reconcile always pass an
    explicit backend, so they never reach the env read below (ADR-030/ADR-039).
    """
    return backend or get_gcp_range_backend()


def _uses_active_gdc_range_plane(backend: str | None = None) -> bool:
    """Return whether this operation uses the active GDC VM Runtime backend."""
    return _get_provider() == "gcp" and _resolve_backend(backend) == "gdc"


def _uses_gce_range_cells(backend: str | None = None) -> bool:
    """Return whether this operation uses the GCE range-cell backend."""
    return _get_provider() == "gcp" and _resolve_backend(backend) == "gce"


def _validate_range_cell_route(variables: dict[str, Any] | None, backend: str | None = None) -> None:
    """Prevent VM-cell requests from entering any legacy provider fallback."""
    is_cell_request = is_gcp_vm_range_cell_request(variables)
    if is_cell_request and not _uses_gce_range_cells(backend):
        raise RuntimeError("GCP VM range-cell requests require the active GCP/GCE VM range-cell backend")
    if _uses_gce_range_cells(backend) and variables is not None and not is_cell_request:
        raise RuntimeError("The GCP/GCE VM range-cell backend requires an admitted range-cell contract request")


def get_range_state_key_prefix(backend: str | None = None) -> str:
    """Return the provider-specific Terraform state key prefix."""
    if _uses_active_gdc_range_plane(backend):
        return "gcp/gdc-ranges"
    if _uses_gce_range_cells(backend):
        return "gcp/gce-range-cells"
    provider = _get_provider()
    if provider == "aws":
        return "ranges"
    raise CloudProviderNotImplementedError(provider)


def has_terraform_state(request_uuid: str, backend: str | None = None) -> bool:
    """Check if Terraform state exists for the given Range request."""
    if _uses_active_gdc_range_plane(backend) or _uses_gce_range_cells(backend):
        return False
    return terraform_base.has_terraform_state(get_range_state_key_prefix(backend), request_uuid)


def apply_range(
    request_uuid: str,
    variables: dict[str, Any],
    working_dir: Path | None = None,
    *,
    purpose: InstantiationPurpose = InstantiationPurpose.LIVE_FIRE,
    gce_apply_range_cell: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run terraform apply for Range and return outputs.

    ``purpose`` defaults to live-fire, the only purpose any current caller uses.
    A live-fire provision reaching the GDC route is denied as defense in depth
    (issue #1348 / ADR-030) before any GDC apply call; the retained GDC substrate
    is reachable only under the explicit non-user validation purpose.
    """
    _validate_range_cell_route(variables)
    if _uses_gce_range_cells():
        apply_gce = gce_apply_range_cell or gcp_range_cells.apply_range_cell
        return apply_gce(request_uuid, variables)

    if _uses_active_gdc_range_plane():
        # Defense in depth (issue #1348): evaluate the closed policy for the active
        # GDC backend and deny before any GDC apply call, carrying the stable ADR-039
        # classification code on the raised error so the incumbent error/event
        # mapping can treat a policy denial as permanent rather than transient.
        admission = evaluate_gcp_backend_admission("gdc", None, purpose)
        if not admission.admitted:
            error = CloudError(admission.reason)
            error.code = admission.code
            raise error
        network_output = gdc_range_networks.apply_range_networks(request_uuid, variables)
        vm_output = gdc_vmruntime_assets.apply_range_assets(
            request_uuid,
            variables,
            network_output.get("subnets", {}),
        )
        pod_output = gdc_scenario_pods.apply_range_assets(
            request_uuid,
            variables,
            network_output.get("subnets", {}),
        )
        return {
            "subnets": network_output.get("subnets", {}),
            "instances": [*vm_output, *pod_output],
        }

    if working_dir is None:
        working_dir = get_range_module_path()
    return terraform_base.apply(get_range_state_key_prefix(), request_uuid, variables, working_dir, _LABEL)


def destroy_range(
    request_uuid: str,
    working_dir: Path | None = None,
    variables: dict[str, Any] | None = None,
    *,
    gce_destroy_range_cell: Callable[[str, dict[str, Any] | None], None] | None = None,
    backend: str | None = None,
) -> None:
    """Run terraform destroy for Range.

    ``backend`` is the per-operation ownership binding resolved at operation start
    from the persisted Range (#1666). When supplied, teardown routes from it -- so
    a range provisioned on GDC is torn down through the GDC path even after the
    deploy-wide selector flips to GCE. ``None`` preserves the legacy env-selector
    behavior (non-GCP and provision-failure fallbacks).
    """
    _validate_range_cell_route(variables, backend)
    if _uses_gce_range_cells(backend):
        destroy_gce = gce_destroy_range_cell or gcp_range_cells.destroy_range_cell
        destroy_gce(request_uuid, variables)
        return

    if _uses_active_gdc_range_plane(backend):
        gdc_scenario_pods.destroy_range_assets(request_uuid, variables)
        gdc_vmruntime_assets.destroy_range_assets(request_uuid, variables)
        gdc_range_networks.destroy_range_networks(request_uuid, variables)
        return

    if working_dir is None:
        working_dir = get_range_module_path()
    terraform_base.destroy(get_range_state_key_prefix(backend), request_uuid, working_dir, _LABEL, variables=variables)


def cleanup_range_state(request_uuid: str, backend: str | None = None) -> None:
    """Delete range Terraform state after destroy."""
    if _uses_active_gdc_range_plane(backend) or _uses_gce_range_cells(backend):
        return
    terraform_base.cleanup_state(get_range_state_key_prefix(backend), request_uuid, _LABEL)
