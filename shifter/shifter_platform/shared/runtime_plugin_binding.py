"""Immutable deployment bindings for an independently installed runtime plugin.

These are Shifter execution decisions beside the RAES plan, not authoring intent
inside that plan. A retained pin remains usable for cleanup after registry edits.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Self
from uuid import UUID, uuid5

from pydantic import Field, model_validator
from shifter_adapter_sdk.runtime import (
    PROTOCOL,
    ClosedModel,
    Digest,
    GuestTarget,
    Identifier,
    Phase,
    PluginManifest,
    RuntimeInput,
    canonical_digest,
)

_GCE_IMAGE_REF = re.compile(r"^projects/[a-z0-9][-a-z0-9.:]*/global/images/[a-z](?:[-a-z0-9]{0,61}[a-z0-9])?$")
_GCE_MACHINE_IMAGE_REF = re.compile(
    r"^projects/[a-z0-9][-a-z0-9.:]*/global/machineImages/[a-z](?:[-a-z0-9]{0,61}[a-z0-9])?$"
)
_AWS_AMI = re.compile(r"^ami-(?:[0-9a-f]{8}|[0-9a-f]{17})$")
_MACHINE_TYPE = re.compile(r"^[a-z][a-z0-9-]{1,30}(?:\.[a-z0-9]{1,20})?$")
_LOCAL_USER = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,31}$")
_CONTAINER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class RuntimeTargetImageProfile(ClosedModel):
    """Administrator-selected provider image for one adapter guest binding."""

    provider: Literal["gcp", "aws"]
    image_kind: Literal["image", "machine-image"] = "image"
    image_ref: Annotated[str, Field(min_length=1, max_length=500)]
    machine_type: Annotated[str, Field(max_length=100)] = ""
    disk_size_gb: Annotated[int, Field(strict=True, ge=1, le=16_384)] | None = None
    disk_type: Annotated[str, Field(max_length=100)] = ""
    allow_public_web_egress: bool = Field(default=False, strict=True)
    bootstrap_capability: Annotated[str, Field(max_length=64)] = "standard"
    management_ssh_username: Annotated[str, Field(max_length=32)] = ""
    management_ssh_port: Annotated[int, Field(strict=True, ge=1, le=65_535)] = 22
    participant_container_name: Annotated[str, Field(max_length=128)] = ""
    participant_username: Annotated[str, Field(max_length=32)] = ""
    participant_readiness_contract: Annotated[str, Field(max_length=64)] = ""
    participant_readiness_manifest_sha256: Annotated[str, Field(max_length=64)] = ""
    domain_dns_name: Annotated[str, Field(max_length=253)] = ""
    domain_netbios_name: Annotated[str, Field(max_length=15)] = ""

    @model_validator(mode="after")
    def validate_provider_profile(self) -> Self:
        """Reject provider image details that cannot be realized safely."""
        if self.machine_type and not _MACHINE_TYPE.fullmatch(self.machine_type):
            raise ValueError("image profile machine type is invalid")
        for value in (self.management_ssh_username, self.participant_username):
            if value and not _LOCAL_USER.fullmatch(value):
                raise ValueError("image profile usernames must be local OS usernames")
        if self.provider == "aws":
            _validate_aws_image_profile(self)
        else:
            _validate_gcp_image_profile(self)
        return self


def _participant_profile(profile: RuntimeTargetImageProfile) -> tuple[str, str, str, str]:
    """Collect the fields required to access and verify a participant host."""
    return (
        profile.participant_container_name,
        profile.participant_username,
        profile.participant_readiness_contract,
        profile.participant_readiness_manifest_sha256,
    )


def _domain_profile(profile: RuntimeTargetImageProfile) -> tuple[str, str]:
    """Collect the DNS and NetBIOS names for a prepromoted domain image."""
    return (profile.domain_dns_name, profile.domain_netbios_name)


def _validate_aws_image_profile(profile: RuntimeTargetImageProfile) -> None:
    """Require an exact AMI, EBS disks, and a closed bootstrap contract.

    Native EC2 hosts accept the same preconfigured participant host and
    prepromoted directory contracts as GCE images (#2527, #2528).
    """
    if profile.image_kind != "image" or not _AWS_AMI.fullmatch(profile.image_ref):
        raise ValueError("AWS image profiles require an exact AMI ID")
    if profile.disk_type and profile.disk_type not in {"gp2", "gp3"}:
        raise ValueError("AWS image profile disk type is unsupported")
    if profile.allow_public_web_egress:
        raise ValueError("AWS image profiles do not support public web egress")
    participant = _participant_profile(profile)
    domain = _domain_profile(profile)
    if profile.bootstrap_capability == "preconfigured-machine-host":
        _validate_participant_readiness(profile, participant, domain)
    else:
        _validate_boot_image_capability(profile, participant, domain)


def _validate_participant_readiness(
    profile: RuntimeTargetImageProfile,
    participant: tuple[str, str, str, str],
    domain: tuple[str, str],
) -> None:
    """Require a complete participant access and readiness contract on any provider."""
    if any(domain):
        raise ValueError("machine host images do not accept domain fields")
    if not profile.management_ssh_username or not all(participant):
        raise ValueError("machine host images require complete host and participant readiness fields")
    if not _CONTAINER.fullmatch(profile.participant_container_name):
        raise ValueError("participant container name is invalid")
    if profile.participant_readiness_contract != "participant-readiness/v1":
        raise ValueError("participant readiness contract is unsupported")
    if not re.fullmatch(r"[0-9a-f]{64}", profile.participant_readiness_manifest_sha256):
        raise ValueError("participant readiness manifest digest is invalid")


def _validate_boot_image_capability(
    profile: RuntimeTargetImageProfile,
    participant: tuple[str, str, str, str],
    domain: tuple[str, str],
) -> None:
    """Require compatible bootstrap fields for a standard or prepromoted boot image."""
    if any(participant):
        raise ValueError("participant host fields require a preconfigured machine host")
    if profile.bootstrap_capability == "standard" and any(domain):
        raise ValueError("standard boot images do not accept domain fields")
    if profile.bootstrap_capability == "prepromoted-domain-controller" and not all(domain):
        raise ValueError("prepromoted directory images require DNS and NetBIOS domain names")
    if profile.bootstrap_capability not in {"standard", "prepromoted-domain-controller"}:
        raise ValueError("adapter-selected boot image capability is unsupported")


def _validate_gcp_image_profile(profile: RuntimeTargetImageProfile) -> None:
    """Validate the selected GCP boot or machine-host image profile."""
    participant = _participant_profile(profile)
    domain = _domain_profile(profile)
    if profile.image_kind == "image" and profile.bootstrap_capability != "preconfigured-machine-host":
        _validate_gcp_boot_image_profile(profile, participant, domain)
        return
    _validate_gcp_preconfigured_source(profile)
    _validate_gcp_preconfigured_readiness(profile, participant, domain)


def _validate_gcp_preconfigured_source(profile: RuntimeTargetImageProfile) -> None:
    """Require an exact GCP host source and supported custom-image disk type."""
    if profile.image_kind == "machine-image" and not _GCE_MACHINE_IMAGE_REF.fullmatch(profile.image_ref):
        raise ValueError("GCP machine image profiles require an exact machine-image resource")
    if profile.image_kind == "image" and not _GCE_IMAGE_REF.fullmatch(profile.image_ref):
        raise ValueError("GCP preconfigured host profiles require an exact custom-image resource")
    if (
        profile.image_kind == "image"
        and profile.disk_type
        and profile.disk_type not in {"pd-standard", "pd-balanced", "pd-ssd", "pd-extreme", "hyperdisk-balanced"}
    ):
        raise ValueError("GCP image profile disk type is unsupported")


def _validate_gcp_preconfigured_readiness(
    profile: RuntimeTargetImageProfile,
    participant: tuple[str, str, str, str],
    domain: tuple[str, str],
) -> None:
    """Require the preconfigured capability and its participant readiness contract."""
    if profile.bootstrap_capability != "preconfigured-machine-host":
        raise ValueError("GCP machine images require the preconfigured-machine-host capability")
    _validate_participant_readiness(profile, participant, domain)


def _validate_gcp_boot_image_profile(
    profile: RuntimeTargetImageProfile,
    participant: tuple[str, str, str, str],
    domain: tuple[str, str],
) -> None:
    """Require a concrete GCP boot image and compatible bootstrap fields."""
    if not _GCE_IMAGE_REF.fullmatch(profile.image_ref):
        raise ValueError("GCP image profiles require an exact Compute Engine image resource")
    _validate_boot_image_capability(profile, participant, domain)
    if profile.disk_type and profile.disk_type not in {
        "pd-standard",
        "pd-balanced",
        "pd-ssd",
        "pd-extreme",
        "hyperdisk-balanced",
    }:
        raise ValueError("GCP image profile disk type is unsupported")


class PluginTargetBindings(ClosedModel):
    """The logical guest names requested by an installed plugin and exact nodes."""

    targets: dict[Identifier, Annotated[str, Field(min_length=1, max_length=1024)]] = Field(
        min_length=1,
        max_length=64,
    )
    parameters: dict[Identifier, Annotated[str, Field(max_length=8192)]] = Field(
        default_factory=dict,
        max_length=64,
        repr=False,
    )
    image_profiles: dict[Identifier, RuntimeTargetImageProfile] = Field(default_factory=dict, max_length=64)

    def validate_manifest(self, manifest: PluginManifest) -> None:
        if set(self.targets) != set(manifest.required_bindings):
            raise ValueError("Plugin target bindings do not match its declaration")
        if set(self.parameters) != set(manifest.required_parameters):
            raise ValueError("Plugin parameters do not match its declaration")
        if not set(self.image_profiles).issubset(self.targets):
            raise ValueError("Plugin image profiles must name declared target bindings")

    def validate_plan(self, plan: object) -> None:
        resources = plan.get("resources") if isinstance(plan, dict) else None
        if not isinstance(resources, dict):
            raise ValueError("Plugin binding requires a compiled resource plan")
        for address in self.targets.values():
            entry = resources.get(address)
            if not isinstance(entry, dict) or entry.get("resource_type") != "node":
                raise ValueError("Plugin binding references a guest absent from the compiled plan")
            payload = entry.get("payload")
            if not isinstance(payload, dict) or (
                payload.get("count") is not None and (type(payload["count"]) is not int or payload["count"] != 1)
            ):
                raise ValueError("A plugin binding requires exactly one guest")

    def image_profile_for(self, node_address: str) -> RuntimeTargetImageProfile | None:
        """Return the administrator profile for the logical binding targeting a node."""
        matches = [
            self.image_profiles[name]
            for name, address in self.targets.items()
            if address == node_address and name in self.image_profiles
        ]
        if len(matches) > 1 and len({profile.model_dump_json() for profile in matches}) != 1:
            raise ValueError("A guest cannot have conflicting adapter image profiles")
        return matches[0] if matches else None

    def validate_provider(self, backend: str) -> None:
        """Require every selected image profile to match the admitted range backend."""
        expected = {"gce": "gcp", "ec2": "aws"}.get(backend)
        if self.image_profiles and (
            expected is None or any(row.provider != expected for row in self.image_profiles.values())
        ):
            raise ValueError("Plugin image profile provider does not match the admitted range backend")


class RuntimePluginScope(ClosedModel):
    """Authorized tenancy and verified pack identity carried beside the plan."""

    organization_uuid: UUID
    pack_id: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    pack_digest: Digest


class RuntimePluginPin(RuntimePluginScope):
    """Exact executable and pack binding admitted for one range's lifetime."""

    binding_version: Literal[1] = 1
    installation_id: UUID
    manifest: PluginManifest
    bindings: PluginTargetBindings

    @model_validator(mode="after")
    def validate_pin(self) -> Self:
        self.bindings.validate_manifest(self.manifest)
        if len(self.model_dump_json().encode("utf-8")) > 32_768:
            raise ValueError("Plugin binding exceeds its input budget")
        return self

    @property
    def digest(self) -> str:
        return canonical_digest(self.model_dump(mode="json"))


def runtime_plugin_requests(
    pin: RuntimePluginPin,
    plan: dict[str, Any],
    operation_id: UUID,
    range_id: int,
    *,
    backend: str = "gce",
) -> tuple[RuntimeInput, ...]:
    """Plan guest actions before provisioning, with no realized addresses or secrets.

    Runtime hosts support RAES GCE and EC2 guest configuration. Plans are pure:
    the isolated worker cannot observe guests or call a provider. The host later
    resolves actions against its own realized node-to-transport map.
    """
    pin = RuntimePluginPin.model_validate(pin)
    providers: dict[str, Literal["aws", "gcp"]] = {"gce": "gcp", "ec2": "aws"}
    if backend not in providers:
        raise ValueError("Runtime plugins are not supported by this range backend")
    pin.bindings.validate_plan(plan)
    targets = {
        name: GuestTarget(node_address=address, os_family=plan["resources"][address]["payload"]["os_family"])
        for name, address in pin.bindings.targets.items()
    }
    phases: tuple[Phase, ...] = ("validate", "configure", "verify")
    return tuple(
        RuntimeInput(
            protocol=PROTOCOL,
            invocation_id=uuid5(operation_id, f"runtime-plugin:{phase}"),
            operation_id=operation_id,
            pack_digest=pin.pack_digest,
            manifest=pin.manifest,
            phase=phase,
            provider=providers[backend],
            range_id=range_id,
            targets=targets,
            parameters=pin.bindings.parameters,
        )
        for phase in phases
    )
