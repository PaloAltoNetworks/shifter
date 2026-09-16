"""Read-only joins between prepared evidence and the ordinary image inventory."""

from collections.abc import Iterable
from typing import Protocol

from django.conf import settings

from shared.operation_envelope import canonical_payload_digest
from shared.raes.prepared_artifacts import VerifiedMaterialization


class RaesImageMappingLike(Protocol):
    """Inventory fields compared against an immutable prepared admission."""

    @property
    def provider(self) -> str: ...
    @property
    def artifact_id(self) -> str: ...
    @property
    def artifact_version(self) -> str: ...
    @property
    def artifact_digest(self) -> str: ...
    @property
    def media_type(self) -> str: ...
    @property
    def image_ref(self) -> str: ...
    @property
    def integrity_ref(self) -> str: ...
    @property
    def provenance_ref(self) -> str: ...


def prepared_inventory_facts(mapping_ids: Iterable[int]) -> dict[int, VerifiedMaterialization | None]:
    """A present but invalid admission maps to None so its inventory row is excluded."""
    from engine.models import PreparedArtifactAdmission

    result: dict[int, VerifiedMaterialization | None] = {}
    for row in PreparedArtifactAdmission.objects.filter(image_mapping_id__in=mapping_ids).select_related("operation"):
        result[row.image_mapping_id] = None
        try:
            facts = VerifiedMaterialization.model_validate(row.facts)
        except ValueError:
            continue
        operation = row.operation
        if (
            facts.digest != row.facts_digest
            or facts.scope_digest != row.scope_digest
            or facts.operation_id != operation.id
            or operation.state != "available"
            or facts.operation_input_digest != operation.input_digest
            or canonical_payload_digest(operation.input) != operation.input_digest
            or operation.input["grant"]["project_id"] != settings.GCP_PROJECT_ID
            or not facts.image_ref.startswith(f"projects/{settings.GCP_PROJECT_ID}/global/images/")
        ):
            continue
        result[row.image_mapping_id] = facts
    return result


def mapping_matches_admission(row: RaesImageMappingLike, facts: VerifiedMaterialization | None) -> bool:
    """Administrative mapping edits cannot retarget a previously verified artifact."""
    return (
        facts is not None
        and row.provider == "gce"
        and (
            row.artifact_id,
            row.artifact_version,
            row.artifact_digest,
            row.media_type,
            row.image_ref,
            row.integrity_ref,
            row.provenance_ref,
        )
        == (
            facts.artifact.artifact_id,
            facts.artifact.version,
            facts.artifact.digest,
            facts.artifact.media_type,
            facts.image_ref,
            facts.integrity_ref,
            facts.provenance_ref,
        )
    )
