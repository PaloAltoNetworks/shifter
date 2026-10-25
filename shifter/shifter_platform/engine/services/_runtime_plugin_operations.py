"""Operation-fenced planning requests; plugin code runs only in isolated Jobs."""

from __future__ import annotations

from contextlib import suppress
from datetime import timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from engine.models import OperationInput, RuntimePluginInstallation, RuntimePluginInvocation

from django.db import transaction
from django.utils import timezone
from shifter_adapter_sdk.runtime import RuntimeInput, RuntimePlan

from shared.cloud.runtime_plugins import interrupt_plugin, launch_plugin, observe_plugin
from shared.operation_envelope import validate_operation_envelope
from shared.raes.operation_input import parse_raes_operation_input
from shared.runtime_plugin_binding import runtime_plugin_requests

from ._runtime_plugin_controller import _pull_secret


def queue_runtime_plugin_plans(envelope: dict[str, Any]) -> None:
    """Called in the launch transaction; never imports the installed distribution."""
    from engine.models import RuntimePluginInvocation

    if (envelope["resource"], envelope["operation"]) != ("raes-range", "provision"):
        return
    if "runtime_plugin" not in envelope["payload"]:
        return
    parsed = parse_raes_operation_input(envelope["payload"])
    if parsed.runtime_plugin is None:
        return
    if parsed.range_backend not in {"gce", "ec2"}:
        raise ValueError("Runtime plugins are not supported by this range backend")
    from uuid import UUID

    requests = runtime_plugin_requests(
        parsed.runtime_plugin,
        parsed.plan,
        UUID(str(envelope["operation_id"])),
        parsed.legacy_range_id,
        backend=parsed.range_backend,
    )
    RuntimePluginInvocation.objects.bulk_create(
        RuntimePluginInvocation(
            id=request.invocation_id,
            operation_id=request.operation_id,
            request_id=envelope["request_id"],
            phase=request.phase,
            input=request.model_dump(mode="json"),
            input_digest=request.digest,
            expires_at=timezone.now() + timedelta(minutes=10),
        )
        for request in requests
    )


def _verify_operation_identity(operation: OperationInput, envelope: dict[str, Any]) -> None:
    """Reject a durable envelope whose correlation fields differ from its operation."""
    if any(
        str(envelope[key]) != str(getattr(operation, key))
        for key in (
            "operation_id",
            "request_id",
            "resource",
            "operation",
            "contract_version",
        )
    ) or (operation.resource, operation.operation) != ("raes-range", "provision"):
        raise ValueError("Plugin operation identity mismatch")


def _authorized_request(row: RuntimePluginInvocation) -> tuple[RuntimeInput, RuntimePluginInstallation]:
    """Reconstruct the authorized request from durable operation and executable pins."""
    from engine.models import OperationInput, Range, RuntimePluginInstallation

    operation = OperationInput.objects.get(operation_id=row.operation_id, request_id=row.request_id)
    envelope = validate_operation_envelope(operation.envelope)
    _verify_operation_identity(operation, envelope)
    parsed = parse_raes_operation_input(envelope["payload"])
    pin = parsed.runtime_plugin
    if pin is None or parsed.range_backend not in {"gce", "ec2"}:
        raise ValueError("Missing plugin operation binding")
    target = Range.objects.get(request__request_id=row.request_id, provisioner_operation_id=row.operation_id)
    if target.id != parsed.legacy_range_id or target.status in {"destroyed", "destroying", "failed", "ready"}:
        raise ValueError("Plugin operation is no longer active")
    requests = runtime_plugin_requests(
        pin, parsed.plan, row.operation_id, parsed.legacy_range_id, backend=parsed.range_backend
    )
    request = _verify_invocation(row, requests)
    installation = RuntimePluginInstallation.objects.get(
        pk=pin.installation_id, organization_uuid=pin.organization_uuid
    )
    if installation.manifest_digest != pin.manifest.digest:
        raise ValueError("Plugin executable identity mismatch")
    return request, installation


def _verify_invocation(row: RuntimePluginInvocation, requests: tuple[RuntimeInput, ...]) -> RuntimeInput:
    """Verify the durable phase request against the reconstructed immutable operation."""
    expected = next(request for request in requests if request.invocation_id == row.id)
    request = RuntimeInput.model_validate(row.input)
    if request.digest != expected.digest or row.input_digest != expected.digest or row.phase != expected.phase:
        raise ValueError("Plugin invocation identity mismatch")
    return request


def reconcile_runtime_plugin_operations(*, limit: int = 6) -> int:
    """Reconcile a bounded batch of pending isolated planning invocations."""
    from engine.models import RuntimePluginInvocation

    if not 1 <= limit <= 30:
        raise ValueError("Invalid plugin reconciliation batch size")
    rows = list(RuntimePluginInvocation.objects.filter(state="pending").order_by("updated_at", "id")[:limit])
    for row in rows:
        _reconcile(row)
    return len(rows)


def _observe_plan(request: RuntimeInput) -> tuple[RuntimePlan | None, str]:
    """Authorize the isolated worker result before accepting its planned state."""
    state = "pending"
    result = observe_plugin(request)
    if result is not None:
        if not isinstance(result, RuntimePlan):
            raise ValueError("Invalid plugin plan")
        result = RuntimePlan.model_validate(result)
        result.authorize(request)
        state = "planned" if result.status == "planned" else "failed"
    return result, state


def _reconcile(row: RuntimePluginInvocation) -> None:
    """Record only planning evidence still authorized by the locked range generation."""
    from engine.models import Range, RuntimePluginInvocation

    result, state = None, "pending"
    request = None
    try:
        request, installation = _authorized_request(row)
        if row.expires_at <= timezone.now():
            raise ValueError("Plugin planning expired")
        secret_name = f"runtime-plugin-pull-{request.invocation_id.hex}" if installation.registry_credentials else ""
        launch_plugin(request, image_pull_secret=secret_name)
        _pull_secret(installation, request)
        result, state = _observe_plan(request)
    except Exception:
        # Private code, scripts and registry diagnostics never enter public logs.
        state = "failed"
        result = None
        if request is not None:
            # The Job deadline still bounds execution if interruption is unavailable.
            with suppress(Exception):
                interrupt_plugin(request)
    with transaction.atomic():
        Range.objects.select_for_update().filter(request__request_id=row.request_id).first()
        current = RuntimePluginInvocation.objects.select_for_update().get(pk=row.pk)
        if current.state != "pending":
            return
        try:
            _authorized_request(current)
            if current.expires_at <= timezone.now():
                raise ValueError("Plugin planning expired")
        except Exception:
            state, result = "failed", None
        current.state = state
        current.result = result.model_dump(mode="json") if result is not None else None
        current.save(update_fields=["state", "result", "updated_at"])
