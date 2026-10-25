"""Reconcile durable installation probes through the isolated worker boundary."""

from __future__ import annotations

import base64
import json
from typing import TYPE_CHECKING

from django.db import transaction
from django.utils import timezone
from shifter_adapter_sdk.runtime import PROTOCOL, InspectionInput, InspectionResult, PluginManifest, RuntimeInput

from shared.audit import AuditAction, AuditEntityType, AuditEvent, audit_log
from shared.cloud.exceptions import CloudTaskError
from shared.cloud.kubernetes._client import load_kubernetes_api
from shared.cloud.kubernetes._helpers import create_with_admission_retry, is_admission_conflict
from shared.cloud.runtime_plugins import (
    PLUGIN_NAMESPACE,
    interrupt_plugin,
    launch_plugin,
    observe_plugin,
    plugin_task_ref,
)

if TYPE_CHECKING:
    from engine.models import RuntimePluginInstallation


def _pull_secret(row: RuntimePluginInstallation, request: InspectionInput | RuntimeInput) -> str:
    """Create a per-invocation immutable image-pull secret, never mount it in a pod."""
    if not row.registry_credentials:
        return ""
    credentials = json.loads(row.registry_credentials)
    registry = request.manifest.worker_image.split("/", 1)[0]
    config = json.dumps({"auths": {registry: credentials}}, separators=(",", ":"))
    encoded = base64.b64encode(config.encode()).decode("ascii")
    name = f"runtime-plugin-pull-{request.invocation_id.hex}"
    batch, core, _, api_exception = load_kubernetes_api()
    job_name = plugin_task_ref(request).split("/", 1)[1]
    job = batch.read_namespaced_job(name=job_name, namespace=PLUGIN_NAMESPACE, _request_timeout=30)
    owner = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "name": job_name,
        "uid": job.metadata.uid,
        "controller": True,
        "blockOwnerDeletion": False,
    }
    body = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": name, "ownerReferences": [owner]},
        "type": "kubernetes.io/dockerconfigjson",
        "immutable": True,
        "data": {".dockerconfigjson": encoded},
    }
    try:
        # Concurrent plugin launches race on the namespace ResourceQuota; an
        # admission Conflict created nothing and is retried, never read back.
        create_with_admission_retry(
            lambda: core.create_namespaced_secret(namespace=PLUGIN_NAMESPACE, body=body, _request_timeout=30)
        )
    except api_exception as exc:
        if getattr(exc, "status", None) != 409 or is_admission_conflict(exc):
            raise CloudTaskError("Plugin registry credentials could not be installed") from None
        current = core.read_namespaced_secret(name=name, namespace=PLUGIN_NAMESPACE, _request_timeout=30)
        owners = current.metadata.owner_references or []
        if (
            current.type != body["type"]
            or current.data != body["data"]
            or not current.immutable
            or len(owners) != 1
            or owners[0].uid != job.metadata.uid
        ):
            raise CloudTaskError("Plugin registry credential identity mismatch") from None
    return name


def reconcile_runtime_plugins(*, limit: int = 3) -> int:
    """Execute no plugin in this process; accept only current probe evidence."""
    from engine.models import RuntimePluginInstallation

    if not 1 <= limit <= 20:
        raise ValueError("Invalid plugin reconciliation batch size")
    rows = list(RuntimePluginInstallation.objects.filter(state="checking").order_by("updated_at")[:limit])
    for row in rows:
        _reconcile(row)
    return len(rows)


def _reconcile(row: RuntimePluginInstallation) -> None:
    """Run or expire one current isolated compatibility probe."""
    state, failure_code = "checking", ""
    request = None
    try:
        manifest = PluginManifest.model_validate(row.manifest)
        if manifest.digest != row.manifest_digest:
            raise ValueError("Stored plugin identity mismatch")
        request = InspectionInput(protocol=PROTOCOL, phase="inspect", invocation_id=row.probe_id, manifest=manifest)
        if row.probe_expires_at <= timezone.now():
            state, failure_code = "failed", "installation-timeout"
            interrupt_plugin(request)
        else:
            state, failure_code = _observe_probe(row, request)
    except Exception:
        # Kubernetes/image errors can contain registry addresses and diagnostic
        # output. Persist and audit only a closed, tenant-actionable code.
        state, failure_code = "failed", failure_code or "installation-failed"
    _record(row, state, failure_code)


def _observe_probe(row: RuntimePluginInstallation, request: InspectionInput) -> tuple[str, str]:
    """Authorize a bounded worker result against the exact installation probe."""
    state, failure_code = "checking", ""
    # A pull secret is born with its Job owner; a crash or rejected Job
    # cannot leave unowned registry credentials. Kubelet retries pulls
    # while the corresponding immutable secret is being created.
    secret_name = f"runtime-plugin-pull-{request.invocation_id.hex}" if row.registry_credentials else ""
    launch_plugin(request, image_pull_secret=secret_name)
    _pull_secret(row, request)
    result = observe_plugin(request)
    if result is not None:
        if not isinstance(result, InspectionResult):
            raise ValueError("Invalid installation result")
        result.authorize(request)
        state = "ready" if result.status == "compatible" else "failed"
        failure_code = "" if state == "ready" else "incompatible-plugin"
    return state, failure_code


def _record(row: RuntimePluginInstallation, state: str, failure_code: str) -> None:
    """Persist only current probe evidence under the installation row lock."""
    from engine.models import RuntimePluginInstallation

    with transaction.atomic():
        current = RuntimePluginInstallation.objects.select_for_update().get(pk=row.pk)
        if current.state != "checking" or current.probe_id != row.probe_id:
            return
        if state == "ready" and current.probe_expires_at <= timezone.now():
            state, failure_code = "failed", "installation-timeout"
        current.state = state
        current.failure_code = failure_code
        current.verified_at = timezone.now() if state == "ready" else None
        current.save(update_fields=["state", "failure_code", "verified_at", "updated_at"])
        if state != "checking":
            audit_log(
                AuditEvent(
                    entity_type=AuditEntityType.RUNTIME_PLUGIN,
                    entity_id=0,
                    entity_ref=str(row.pk),
                    action=AuditAction.UPDATE,
                    previous_state={"state": "checking"},
                    new_state={"state": state, "failure_code": failure_code, "manifest_digest": row.manifest_digest},
                ),
                strict=True,
            )
