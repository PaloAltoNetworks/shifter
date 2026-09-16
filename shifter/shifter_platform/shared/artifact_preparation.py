"""Closed worker receipts for artifact preparation, independent of RAES tooling.

These are operational observations, not portable artifact intent or admission.
Only a verifier worker can report verifier evidence; the controller still checks
provider ownership, operation fences and the authored requirement before use.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

Digest = Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
ProviderID = Annotated[str, Field(pattern=r"^[1-9][0-9]{0,19}$")]
ImageRef = Annotated[
    str,
    Field(pattern=r"^projects/[a-z][a-z0-9-]{4,61}[a-z0-9]/global/images/[a-z][a-z0-9-]{0,62}$"),
]
BoundedText = Annotated[str, Field(min_length=1, max_length=256)]
Phase = Literal["verify-inputs", "build", "verify-output", "cleanup"]
FailureCode = Literal[
    "",
    "input-verification-failed",
    "execution-failed",
    "output-verification-failed",
    "cleanup-failed",
    "deadline-exceeded",
]
MAX_RESULT_BYTES = 65536


class ClosedModel(BaseModel):
    """Workers cannot add overrides or hidden claims to a known protocol."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class RawDiskObservation(ClosedModel):
    """Independent raw-disk hash, bound to actual provider image and derived disk."""

    image_ref: ImageRef
    image_id: ProviderID
    disk_id: ProviderID
    raw_disk_digest: Digest
    size_bytes: Annotated[int, Field(gt=0, le=2**50)]


class InputObservation(RawDiskObservation):
    """A named authored lock joined to independently read image bytes."""

    input_id: BoundedText


class InputEvidence(ClosedModel):
    """The verifier must observe every fixed input before build authorization."""

    observations: list[InputObservation] = Field(min_length=1, max_length=64)


class BuildEvidence(ClosedModel):
    """Candidate lineage reported by the builder, never an admission decision."""

    image_ref: ImageRef
    image_id: ProviderID
    source_disk_id: ProviderID
    source_image_id: ProviderID
    builder_instance_id: ProviderID


class OutputEvidence(RawDiskObservation):
    """Independent output measurements; profile semantics remain with the adapter."""

    boot_observed: Literal[True]
    sanitized: Literal[True]
    constraint_values: dict[BoundedText, BoundedText] = Field(default_factory=dict, max_length=32)


class CleanupEvidence(ClosedModel):
    """Cleanup receipts carry no caller-selected deletion instructions."""

    resources_remaining: list[BoundedText] = Field(max_length=0)


_EVIDENCE_TYPES: dict[Phase, type[ClosedModel]] = {
    "verify-inputs": InputEvidence,
    "build": BuildEvidence,
    "verify-output": OutputEvidence,
    "cleanup": CleanupEvidence,
}


class PreparationWorkerResult(BaseModel):
    """Bounded result inbox envelope, validated before durable recording."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol: Literal["shifter.artifact-preparation/v1"]
    operation_id: UUID
    attempt_id: UUID
    input_digest: Digest
    phase: Phase
    status: Literal["succeeded", "failed"]
    failure_code: FailureCode
    evidence: dict[str, object]

    @model_validator(mode="after")
    def validate_evidence(self) -> PreparationWorkerResult:
        """Success needs phase-specific evidence; failures expose only a code."""
        if self.status == "failed":
            if not self.failure_code or self.evidence:
                raise ValueError("failed preparation must carry only its bounded failure code")
        elif self.failure_code:
            raise ValueError("successful preparation cannot carry a failure code")
        else:
            _EVIDENCE_TYPES[self.phase].model_validate(self.evidence)
        if len(self.model_dump_json().encode("utf-8")) > MAX_RESULT_BYTES:
            raise ValueError("preparation result exceeds the size limit")
        return self
