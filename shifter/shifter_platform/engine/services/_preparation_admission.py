"""Controller-owned phase evidence and atomic prepared inventory admission."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from shared.artifact_preparation import PreparationWorkerResult
from shared.cloud.preparation_readback import GCEPreparationReadback
from shared.operation_envelope import canonical_payload_digest
from shared.raes.preparation_contract import AdapterManifest, PreparationPackage
from shared.raes.preparation_inputs import verify_input_observations
from shared.raes.prepared_artifacts import VerifiedMaterialization, admit_materialization_facts

if TYPE_CHECKING:
    from engine.models import PreparationAttempt, PreparationOperation


def validated_result(attempt: PreparationAttempt) -> PreparationWorkerResult:
    """Stored receipts remain bound to their full immutable attempt identity."""
    if not isinstance(attempt.result, dict):
        raise ValueError("preparation receipt is unavailable")
    result = PreparationWorkerResult.model_validate(attempt.result)
    if (
        result.operation_id != attempt.operation_id
        or result.attempt_id != attempt.id
        or result.phase != attempt.phase
        or result.input_digest != attempt.input_digest
        or canonical_payload_digest(attempt.result) != attempt.result_digest
    ):
        raise ValueError("preparation receipt identity changed")
    return result


def verified_facts(
    attempt: PreparationAttempt,
    observer: GCEPreparationReadback,
) -> VerifiedMaterialization | None:
    """Observe each ancestor's provider facts outside the inventory transaction."""
    result = validated_result(attempt)
    if result.status != "succeeded":
        raise ValueError("preparation worker failed")
    payload = attempt.input
    package = PreparationPackage.model_validate(payload["package"])
    evidence = payload["evidence"]
    if attempt.phase == "verify-inputs":
        verify_input_observations(
            package.input_bindings, result.evidence["observations"], payload["grant"]["trusted_input_bindings"]
        )
        observer.verify_inputs(attempt.operation_id, attempt.id, result.evidence)
    elif attempt.phase == "build":
        _ancestor(attempt, "input_attempt_id", "verify-inputs", "inputs")
        observer.verify_inputs(attempt.operation_id, UUID(evidence["input_attempt_id"]), evidence["inputs"])
        observer.verify_build(attempt.operation_id, attempt.id, result.evidence)
        if result.evidence["source_image_id"] != package.input_bindings[0].image_id:
            raise ValueError("builder source changed")
    elif attempt.phase == "verify-output":
        _ancestor(attempt, "input_attempt_id", "verify-inputs", "inputs")
        _ancestor(attempt, "build_attempt_id", "build", "build")
        observer.verify_inputs(attempt.operation_id, UUID(evidence["input_attempt_id"]), evidence["inputs"])
        observer.verify_build(attempt.operation_id, UUID(evidence["build_attempt_id"]), evidence["build"])
        observer.verify_output(attempt.operation_id, attempt.id, result.evidence)
        return admit_materialization_facts(
            operation_id=attempt.operation_id,
            attempt_id=attempt.id,
            operation_input_digest=payload["operation_input_digest"],
            package=package,
            adapter=AdapterManifest.model_validate(payload["adapter"]),
            grant=payload["grant"],
            inputs=evidence["inputs"],
            build=evidence["build"],
            output=result.evidence,
        )
    elif attempt.phase == "cleanup":
        observer.verify_cleanup(
            attempt.operation_id,
            [UUID(value) for value in evidence["attempts"]],
            retained_image=evidence.get("retained_image"),
        )
    return None


def _ancestor(attempt: PreparationAttempt, key: str, phase: str, evidence_key: str) -> None:
    """Handle ancestor."""
    from engine.models import PreparationAttempt

    ancestor = PreparationAttempt.objects.get(pk=attempt.input["evidence"][key], operation_id=attempt.operation_id)
    result = validated_result(ancestor)
    if (
        ancestor.phase != phase
        or ancestor.disposition != "applied"
        or result.status != "succeeded"
        or ancestor.input["operation_input_digest"] != attempt.input["operation_input_digest"]
        or canonical_payload_digest(ancestor.input) != ancestor.input_digest
        or result.evidence != attempt.input["evidence"][evidence_key]
    ):
        raise ValueError("preparation evidence ancestry changed")


def save_admission(operation: PreparationOperation, facts: VerifiedMaterialization) -> None:
    """Caller holds scope/grant/adapter/operation/attempt fences in one transaction."""
    from engine.models import PreparedArtifactAdmission, RaesImageMapping

    mapping = RaesImageMapping.objects.create(
        provider="gce",
        source_name="prepared-" + operation.id.hex,
        source_version="1",
        image_ref=facts.image_ref,
        artifact_id=facts.artifact.artifact_id,
        artifact_version=facts.artifact.version,
        artifact_digest=facts.artifact.digest,
        media_type=facts.artifact.media_type,
        integrity_ref=facts.integrity_ref,
        provenance_ref=facts.provenance_ref,
    )
    PreparedArtifactAdmission.objects.create(
        operation=operation,
        image_mapping=mapping,
        scope_digest=facts.scope_digest,
        facts=facts.model_dump(mode="json"),
        facts_digest=facts.digest,
    )
