"""Native verified facts that join prepared inventory to public RAES disclosures.

These facts are neither an upstream portable schema nor a worker admission API.
The owning controller must observe provider identity outside its transaction and
recheck its operation, grant and attempt fences before storing them in inventory.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from raes.artifact_requirements import ArtifactIdentity, ArtifactMaterializationSpecification

from shared.artifact_preparation import BuildEvidence, Digest, ImageRef, InputEvidence, OutputEvidence, ProviderID
from shared.operation_envelope import canonical_payload_digest
from shared.preparation_grant import PreparationGrantConfiguration
from shared.raes.preparation_contract import AdapterManifest, PreparationPackage, select_preparation
from shared.raes.preparation_inputs import require_input_trust, verify_input_observations


class VerifiedMaterialization(BaseModel):
    """Complete requirement identity prevents facts leaking across similar requirements."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol: Literal["shifter.verified-materialization/v1"] = "shifter.verified-materialization/v1"
    operation_id: UUID
    attempt_id: UUID
    operation_input_digest: Digest
    scope_digest: Digest
    requirement_digest: Digest
    specification: ArtifactMaterializationSpecification
    artifact: ArtifactIdentity
    satisfied_constraint_ids: list[str] = Field(max_length=32)
    locked_input_ids: list[str] = Field(max_length=64)
    integrity_ref: str = Field(min_length=1, max_length=256)
    provenance_ref: str = Field(min_length=1, max_length=256)
    image_ref: ImageRef
    image_id: ProviderID

    @property
    def digest(self) -> str:
        """Bind every persisted availability fact and its admission references."""
        return canonical_payload_digest(self.model_dump(mode="json"))


def admit_materialization_facts(
    *,
    operation_id: UUID,
    attempt_id: UUID,
    operation_input_digest: str,
    package: PreparationPackage,
    adapter: AdapterManifest,
    **documents: dict[str, Any],
) -> VerifiedMaterialization:
    """Validate measured claims for the controller's fenced inventory transaction."""
    if set(documents) != {"grant", "inputs", "build", "output"}:
        raise ValueError("materialization admission requires the complete evidence document set")
    grant, inputs, build, output = (documents[key] for key in ("grant", "inputs", "build", "output"))
    configuration = PreparationGrantConfiguration.model_validate(grant)
    selected = select_preparation(package.requirement, adapter, package.specification_id)
    require_input_trust(package.input_bindings, package.requirement.locked_inputs, configuration.trusted_input_bindings)
    input_evidence = InputEvidence.model_validate(inputs)
    input_ids = verify_input_observations(
        package.input_bindings, input_evidence.model_dump()["observations"], configuration.trusted_input_bindings
    )
    built = BuildEvidence.model_validate(build)
    observed = OutputEvidence.model_validate(output)
    if (
        len(package.input_bindings) != 1
        or built.source_image_id != package.input_bindings[0].image_id
        or built.image_ref != observed.image_ref
        or built.image_id != observed.image_id
        or not observed.image_ref.startswith(f"projects/{configuration.project_id}/global/images/")
        or observed.size_bytes > configuration.max_disk_gb * 1024**3
    ):
        raise ValueError("prepared output does not match the verified candidate lineage and scope")
    constraints = package.requirement.constraints
    if any(observed.constraint_values.get(item.kind) not in item.allowed_values for item in constraints):
        raise ValueError("prepared output does not satisfy every authored constraint")
    evidence_digest = canonical_payload_digest(observed.model_dump(mode="json"))
    return VerifiedMaterialization(
        operation_id=operation_id,
        attempt_id=attempt_id,
        operation_input_digest=operation_input_digest,
        scope_digest=configuration.scope_digest,
        requirement_digest=canonical_payload_digest(package.requirement.model_dump(mode="json")),
        specification=selected.specification,
        artifact=ArtifactIdentity(
            artifact_id="shifter-prepared-" + selected.specification.digest.removeprefix("sha256:"),
            version="1",
            digest=observed.raw_disk_digest,
            media_type="application/vnd.shifter.raw-disk",
        ),
        satisfied_constraint_ids=sorted(item.constraint_id for item in constraints),
        locked_input_ids=input_ids,
        integrity_ref=f"urn:shifter:preparation:{attempt_id}:{evidence_digest}",
        provenance_ref=f"urn:shifter:preparation:{operation_id}:{operation_input_digest}",
        image_ref=observed.image_ref,
        image_id=observed.image_id,
    )
