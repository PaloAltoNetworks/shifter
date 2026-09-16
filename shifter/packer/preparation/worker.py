"""Standalone preparation phases; no Django, SQL, inventory or range authority."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID

from shared.artifact_preparation import BuildEvidence, InputEvidence, PreparationWorkerResult
from shared.operation_envelope import canonical_payload_digest
from shared.preparation_grant import PreparationGrantConfiguration
from shared.raes.preparation_contract import AdapterManifest, PreparationPackage, select_preparation
from shared.raes.preparation_inputs import require_input_trust, verify_input_observations

from preparation.cleanup import cleanup_operation
from preparation.context import load_context
from preparation.gce_boot import verify_boot
from preparation.gce_build import build_image
from preparation.gce_probe import probe_from_guest
from preparation.gce_verify import scan_image

_FAILURES = {
    "verify-inputs": "input-verification-failed",
    "build": "execution-failed",
    "verify-output": "output-verification-failed",
    "cleanup": "cleanup-failed",
}
_MAX_PROFILE_CONTEXT_BYTES = 96 * 1024


def execute_attempt(
    envelope: dict[str, Any],
    root: Path,
    cloud: Callable[[PreparationGrantConfiguration], Any],
) -> dict[str, Any]:
    """Validate immutable inputs before obtaining cloud credentials; return a closed receipt."""
    payload = envelope["input"]
    phase = payload["phase"]
    result = {
        "protocol": "shifter.artifact-preparation/v1",
        "operation_id": str(UUID(payload["operation_id"])),
        "attempt_id": str(UUID(envelope["attempt_id"])),
        "input_digest": envelope["input_digest"],
        "phase": phase,
        "status": "failed",
        "failure_code": _FAILURES[phase],
        "evidence": {},
    }
    try:
        if canonical_payload_digest(payload) != envelope["input_digest"]:
            raise ValueError("preparation input digest changed")
        base = {
            key: value
            for key, value in payload.items()
            if key not in {"operation_id", "operation_input_digest", "phase", "evidence"}
        }
        if canonical_payload_digest(base) != payload["operation_input_digest"]:
            raise ValueError("preparation operation input changed")
        grant = PreparationGrantConfiguration.model_validate(payload["grant"])
        if grant.digest != payload["grant_digest"] or grant.scope_digest != payload["scope_digest"]:
            raise ValueError("preparation grant identity changed")
        if phase == "cleanup":
            evidence = payload["evidence"]
            output = cleanup_operation(
                cloud(grant),
                UUID(payload["operation_id"]),
                [UUID(value) for value in evidence["attempts"]],
                retained_image=evidence.get("retained_image"),
            )
        else:
            output = _execute_work(envelope, root, grant, cloud)
        result.update(status="succeeded", failure_code="", evidence=output)
    except TimeoutError:
        result["failure_code"] = "deadline-exceeded"
    except Exception:
        # Cloud response bodies, context paths, private constraints and identity
        # material must never become worker logs or an unbounded failure payload.
        result.update(status="failed", failure_code=_FAILURES[phase], evidence={})
    return PreparationWorkerResult.model_validate(result).model_dump(mode="json")


def _execute_work(
    envelope: dict[str, Any],
    root: Path,
    grant: PreparationGrantConfiguration,
    cloud: Callable[..., Any],
) -> dict[str, Any]:
    """Handle execute work."""
    payload = envelope["input"]
    adapter = AdapterManifest.model_validate(payload["adapter"])
    package = PreparationPackage.model_validate(payload["package"])
    if adapter.digest != payload["manifest_digest"]:
        raise ValueError("preparation adapter identity changed")
    selected = select_preparation(package.requirement, adapter, package.specification_id)
    profile = selected.specification.profile
    if (
        profile.profile != "shifter-gce-contained-build"
        or profile.version != "1"
        or profile.digest != "sha256:" + hashlib.sha256((root / "PROFILE.md").read_bytes()).hexdigest()
        or len(package.input_bindings) != 1
    ):
        raise ValueError("unsupported contained GCE profile")
    require_input_trust(package.input_bindings, package.requirement.locked_inputs, grant.trusted_input_bindings)
    context = load_context(root / "contexts", selected.specification.specification_id, selected.specification.digest)
    if sum(len(value) for value in context.values()) > _MAX_PROFILE_CONTEXT_BYTES:
        raise ValueError("installed context exceeds the contained GCE profile limit")
    binding = package.input_bindings[0]
    request = {
        "operation_id": payload["operation_id"],
        "attempt_id": envelope["attempt_id"],
        "project_id": grant.project_id,
        "zone": grant.zone,
        "subnetwork": grant.subnetwork,
        "max_disk_gb": grant.max_disk_gb,
        "max_duration_seconds": grant.max_duration_seconds,
        "image_ref": binding.image_ref,
        "image_id": binding.image_id,
    }
    scanner = {"scanner_image": grant.scanner_image, "scanner_image_id": grant.scanner_image_id}
    phase = payload["phase"]
    if phase == "verify-inputs":
        observed = scan_image(cloud(grant), {**request, **scanner}, context, verify_output=False)
        observations = [{**observed, "input_id": binding.lock.input_id}]
        verify_input_observations(package.input_bindings, observations, grant.trusted_input_bindings)
        return {"observations": observations}
    evidence = payload["evidence"]
    inputs = InputEvidence.model_validate(evidence["inputs"])
    verify_input_observations(package.input_bindings, inputs.model_dump()["observations"], grant.trusted_input_bindings)
    if phase == "build":
        return build_image(cloud(grant), request, context)
    built = BuildEvidence.model_validate(evidence["build"])
    if built.source_image_id != binding.image_id:
        raise ValueError("candidate lineage does not match the independently verified input")
    candidate = {**request, "image_ref": built.image_ref, "image_id": built.image_id}
    api = cloud(grant)
    measured = scan_image(api, {**candidate, **scanner}, context, verify_output=True)

    def probe(host: str, nonce: str) -> bool:
        """Handle probe."""
        probe_request = {**request, "image_ref": grant.scanner_image, "image_id": grant.scanner_image_id}
        return probe_from_guest(api, probe_request, context["verify_boot.py"], host, nonce)

    return {**measured, **verify_boot(api, candidate, probe)}
