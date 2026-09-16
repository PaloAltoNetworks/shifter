"""Bind real associated descriptor bytes, then verify the raw image separately.

The public associated-artifact validator reads the actual contained descriptor,
never a synthetic reader standing in for a disk. That descriptor names the full
portable disk identity and concrete backend source. Independent scanner evidence
must subsequently match those bytes; a separate operator policy supplies trust.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field
from raes.artifact_requirements import ArtifactIdentity, ArtifactLockedInput
from raes_contracts.associated_artifacts import (
    AssociatedArtifactValidationLimits,
    load_associated_artifact_manifest_json,
    validate_associated_artifact_manifest,
)
from raes_contracts.json_ingress import parse_bounded_json_object

from shared.artifact_preparation import Digest, ImageRef, InputObservation, ProviderID
from shared.operation_envelope import canonical_payload_digest

MAX_INPUT_BYTES = 16384
DESCRIPTOR_MEDIA_TYPE = "application/vnd.shifter.gce-input+json"


class InputDescriptor(BaseModel):
    """Closed backend projection contained in a public associated manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol: Literal["shifter.gce-input/v1"]
    artifact: ArtifactIdentity
    image_ref: ImageRef
    image_id: ProviderID
    size_bytes: Annotated[int, Field(strict=True, gt=0, le=200 * 1024**3)]


class BoundInput(InputDescriptor):
    """Immutable result of public parent, set, payload and portable identity checks."""

    lock: ArtifactLockedInput
    manifest_digest: Digest

    @property
    def digest(self) -> str:
        """The operator approves the complete bound input, including trust reference."""
        return canonical_payload_digest(self.model_dump(mode="json"))


def bind_input_material(
    lock: ArtifactLockedInput, *, manifest_bytes: bytes, descriptor_bytes: bytes, parent: object
) -> BoundInput:
    """Use the public validator with the real scenario and real descriptor stream."""
    if len(manifest_bytes) > MAX_INPUT_BYTES or len(descriptor_bytes) > MAX_INPUT_BYTES:
        raise ValueError("preparation input material exceeds its bound")
    manifest = load_associated_artifact_manifest_json(manifest_bytes)
    if set(manifest.artifacts) != {lock.input_id}:
        raise ValueError("input manifest must bind exactly the declared descriptor")
    entry = manifest.artifacts[lock.input_id]
    if entry.media_type != DESCRIPTOR_MEDIA_TYPE:
        raise ValueError("input manifest has an unsupported payload type")
    diagnostics = validate_associated_artifact_manifest(
        manifest,
        parent=parent,
        artifact_readers={lock.input_id: BytesIO(descriptor_bytes)},
        limits=AssociatedArtifactValidationLimits(
            max_artifacts=1, max_artifact_bytes=MAX_INPUT_BYTES, max_total_bytes=MAX_INPUT_BYTES
        ),
    )
    if diagnostics:
        raise ValueError("preparation input manifest failed public byte binding")
    descriptor = InputDescriptor.model_validate(parse_bounded_json_object(descriptor_bytes, max_bytes=MAX_INPUT_BYTES))
    if descriptor.artifact != lock.artifact or descriptor.artifact.media_type != "application/vnd.shifter.raw-disk":
        raise ValueError("preparation descriptor does not match the complete locked disk identity")
    return BoundInput(**descriptor.model_dump(mode="json"), lock=lock, manifest_digest=manifest.set_digest)


def load_input_material(root: Path, parent: object, locks: list[ArtifactLockedInput]) -> list[BoundInput]:
    """Resolve only contained package files; refs never trigger ambient acquisition."""
    bindings = []
    for lock in locks:
        manifest_bytes = _read_contained(root, lock.associated_artifact_manifest_ref)
        manifest = load_associated_artifact_manifest_json(manifest_bytes)
        if set(manifest.artifacts) != {lock.input_id}:
            raise ValueError("input manifest must contain exactly its declared descriptor")
        uri = manifest.artifacts[lock.input_id].uri
        prefix = "raes-environment-pack:/"
        if not uri.startswith(prefix):
            raise ValueError("preparation descriptor must be contained in the package")
        descriptor_bytes = _read_contained(root, uri.removeprefix(prefix))
        bindings.append(
            bind_input_material(lock, manifest_bytes=manifest_bytes, descriptor_bytes=descriptor_bytes, parent=parent)
        )
    return bindings


def _read_contained(root: Path, relative: str) -> bytes:
    """Reject filesystem indirection and retain at most the fixed material bound."""
    path = PurePosixPath(relative)
    if not relative or path.is_absolute() or any(part in {".", ".."} for part in relative.split("/")):
        raise ValueError("preparation input path must be contained")
    current = root
    for part in path.parts:
        current /= part
        if current.is_symlink():
            raise ValueError("preparation input path contains filesystem indirection")
    if not current.is_file():
        raise ValueError("preparation input material is unavailable")
    with current.open("rb") as stream:
        payload = stream.read(MAX_INPUT_BYTES + 1)
    if len(payload) > MAX_INPUT_BYTES:
        raise ValueError("preparation input material exceeds its bound")
    return payload


def verify_input_observations(
    bindings: list[BoundInput], observations: object, trusted_bindings: dict[str, list[str]]
) -> list[str]:
    """Require exact measured bytes and separately installed operator trust policy."""
    if not isinstance(observations, list) or any(not isinstance(value, dict) for value in observations):
        raise ValueError("independent input observations must be a list of objects")
    observed = [InputObservation.model_validate(value) for value in observations]
    expected = {item.lock.input_id: item for item in bindings}
    actual = {item.input_id: item for item in observed}
    if not expected or len(expected) != len(bindings) or len(actual) != len(observed) or set(expected) != set(actual):
        raise ValueError("independent input observations do not cover the exact fixed input set")
    for identity, binding in expected.items():
        _verify_input_observation(binding, actual[identity], trusted_bindings)
    return sorted(expected)


def _verify_input_observation(
    binding: BoundInput, receipt: InputObservation, trusted_bindings: dict[str, list[str]]
) -> None:
    """Handle verify input observation."""
    if (
        receipt.image_ref != binding.image_ref
        or receipt.image_id != binding.image_id
        or receipt.raw_disk_digest != binding.lock.artifact.digest
        or receipt.size_bytes != binding.size_bytes
    ):
        raise ValueError("independent input measurement does not match the locked source")
    if binding.digest not in trusted_bindings.get(binding.lock.trust_policy_ref, []):
        raise ValueError("the operator has not admitted this complete input under its trust policy")


def require_input_trust(
    bindings: list[BoundInput], locks: list[ArtifactLockedInput], trusted_bindings: dict[str, list[str]]
) -> None:
    """Admission checks permission for measurement, without claiming it happened."""
    expected = {item.input_id: item for item in locks}
    actual = {item.lock.input_id: item for item in bindings}
    if not expected or len(actual) != len(bindings) or set(expected) != set(actual):
        raise ValueError("preparation input material does not cover the exact fixed input set")
    for identity, binding in actual.items():
        if binding.lock != expected[identity] or binding.artifact != binding.lock.artifact:
            raise ValueError("preparation input material conflicts with the complete authored lock")
        if binding.digest not in trusted_bindings.get(binding.lock.trust_policy_ref, []):
            raise ValueError("preparation input material has no installed operator trust decision")
