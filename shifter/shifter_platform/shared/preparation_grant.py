"""Closed deployment-local authority for the supported preparation worker runtime.

An application adapter manifest requests capabilities. This separate document is
installed by the cloud operator after the corresponding IAM, network and Job
admission resources exist. Parsing is necessary, never proof of provisioning.
"""

from __future__ import annotations

from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shared.artifact_preparation import Digest, ImageRef, ProviderID
from shared.operation_envelope import canonical_payload_digest

Identifier = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]*$")]
DNSLabel = Annotated[str, Field(max_length=63, pattern=r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")]
ImageDigest = Annotated[
    str,
    Field(
        max_length=1024,
        pattern=r"^[a-z0-9][a-z0-9.-]+(?::[0-9]{1,5})?/(?:[a-z0-9]+(?:[._-][a-z0-9]+)*/)*"
        r"[a-z0-9]+(?:[._-][a-z0-9]+)*@sha256:[a-f0-9]{64}$",
    ),
]
Permission = Literal["gce-image-build", "private-artifact-storage"]
RegistryPrefix = Annotated[
    str,
    Field(max_length=512, pattern=r"^[a-z0-9][a-z0-9.-]+(?::[0-9]{1,5})?/(?:[a-z0-9]+(?:[._-][a-z0-9]+)*/)+$"),
]


class PreparationGrantConfiguration(BaseModel):
    """Immutable grant and execution budgets, supplied outside pack installation."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    protocol: Literal["shifter.preparation-grant/v1"]
    backend: Literal["gce"]
    project_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{4,61}[a-z0-9]$")]
    zone: Annotated[str, Field(pattern=r"^[a-z]+-[a-z]+[0-9]-[a-z]$")]
    namespace: Annotated[str, Field(max_length=63, pattern=r"^shifter-preparation(?:-[a-z0-9-]+)?$")]
    subnetwork: Annotated[str, Field(min_length=1, max_length=256)]
    builder_service_account: DNSLabel
    verifier_service_account: DNSLabel
    cleanup_service_account: DNSLabel
    cleanup_image: ImageDigest
    trusted_input_bindings: dict[
        Annotated[str, Field(min_length=1, max_length=1024)],
        Annotated[list[Digest], Field(min_length=1, max_length=64)],
    ] = Field(default_factory=dict, max_length=64)
    image_pull_secrets: list[DNSLabel] = Field(max_length=8)
    registry_prefixes: list[RegistryPrefix] = Field(min_length=1, max_length=8)
    approved_verifier_images: list[ImageDigest] = Field(min_length=1, max_length=16)
    approved_worker_images: list[ImageDigest] = Field(min_length=1, max_length=16)
    permissions: list[Permission] = Field(min_length=1, max_length=2)
    worker_endpoint: Annotated[str, Field(min_length=1, max_length=1024)]
    max_duration_seconds: Annotated[int, Field(ge=60, le=7200)]
    max_concurrent_operations: Annotated[int, Field(ge=1, le=4)]
    max_disk_gb: Annotated[int, Field(ge=1, le=200)]
    scanner_image: ImageRef
    scanner_image_id: ProviderID

    @model_validator(mode="after")
    def validate_authority(self) -> PreparationGrantConfiguration:
        """Reject shared identities, foreign networks and credential-bearing URLs."""
        _validate_accounts_and_network(self)
        _validate_worker_endpoint(self.worker_endpoint)
        _validate_grant_collections(self)
        return self

    def permits_image(self, image: str) -> bool:
        """Registry prefixes end at a path boundary, not a lookalike hostname."""
        return any(image.startswith(prefix) for prefix in self.registry_prefixes)

    @property
    def digest(self) -> str:
        """Bind the entire authority, endpoint and budget configuration."""
        return canonical_payload_digest(self.model_dump(mode="json"))

    @property
    def scope_digest(self) -> str:
        """Partition backend availability by deployment worker scope and location."""
        return canonical_payload_digest(
            {"backend": self.backend, "project_id": self.project_id, "zone": self.zone, "namespace": self.namespace}
        )


def _validate_accounts_and_network(grant: PreparationGrantConfiguration) -> None:
    """Handle validate accounts and network."""
    accounts = (grant.builder_service_account, grant.verifier_service_account, grant.cleanup_service_account)
    if len(set(accounts)) != 3 or any(not value.startswith("preparation-") for value in accounts):
        raise ValueError("preparation worker identities must be separate dedicated service accounts")
    region = grant.zone.rsplit("-", 1)[0]
    prefix = f"projects/{grant.project_id}/regions/{region}/subnetworks/"
    if not grant.subnetwork.startswith(prefix) or not grant.subnetwork.removeprefix(prefix):
        raise ValueError("preparation subnetwork must be in the granted project and region")
    name = grant.subnetwork.removeprefix(prefix)
    if "/" in name or "?" in name or "#" in name:
        raise ValueError("preparation subnetwork must be a concrete resource")


def _validate_worker_endpoint(worker_endpoint: str) -> None:
    """Handle validate worker endpoint."""
    endpoint = urlsplit(worker_endpoint)
    try:
        endpoint_port = endpoint.port
    except ValueError as exc:
        raise ValueError("preparation worker endpoint has an invalid port") from exc
    if (
        endpoint.scheme != "https"
        or not endpoint.hostname
        or endpoint_port not in {None, 443}
        or endpoint.username is not None
        or endpoint.password is not None
        or endpoint.query
        or endpoint.fragment
        or endpoint.path != "/api/v1/cms/artifact-preparation/workers/"
    ):
        raise ValueError("preparation worker endpoint must be the tenant HTTPS worker boundary")


def _validate_grant_collections(grant: PreparationGrantConfiguration) -> None:
    """Handle validate grant collections."""
    for values in (
        grant.image_pull_secrets,
        grant.registry_prefixes,
        grant.approved_verifier_images,
        grant.approved_worker_images,
        grant.permissions,
    ):
        if len(values) != len(set(values)):
            raise ValueError("preparation grant entries must be unique")
    executables = grant.approved_verifier_images + grant.approved_worker_images + [grant.cleanup_image]
    if any(not grant.permits_image(image) for image in executables):
        raise ValueError("approved executables must use a granted private registry")
