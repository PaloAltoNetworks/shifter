"""Closed, application-independent wire contract for isolated runtime plugins.

The plugin produces a plan; the host authorizes targets and executes actions.
Producing a plan never constitutes evidence that a guest is configured or ready.
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Final, Literal, Protocol, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

PROTOCOL: Final = "shifter.runtime-plugin/v1"
ENTRY_POINT_GROUP = "shifter.runtime.plugins"
# Fits one injected environment value on Linux, including its name and terminator.
MAX_INPUT_BYTES = 65_536
MAX_OUTPUT_BYTES = 1_048_576

Identifier = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]*$")]
Digest = Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
Version = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._+!-]*$")]
WorkerImage = Annotated[
    str,
    Field(max_length=1024, pattern=r"^[a-z0-9][a-z0-9.:-]+/[a-z0-9/._-]+@sha256:[a-f0-9]{64}$"),
]
Phase = Literal["validate", "configure", "verify", "cleanup"]
Capability = Literal["guest.configure", "guest.verify"]


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")


def decode_message(raw: str | bytes, *, limit: int) -> object:
    """Reject oversized, ambiguous, or non-JSON worker messages before validation."""
    if len(raw.encode("utf-8") if isinstance(raw, str) else raw) > limit:
        raise ValueError("plugin message exceeds its bound")

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate plugin message key")
            result[key] = value
        return result

    def invalid_constant(_value: str) -> None:
        raise ValueError("non-JSON plugin message value")

    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="strict")
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("invalid plugin message encoding or nesting") from exc


def canonical_digest(value: object) -> str:
    """Bind JSON bytes independently of object-key ordering."""
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


class PluginManifest(ClosedModel):
    """Executable identity and capabilities requested by an author-provided plugin."""

    protocol: Literal["shifter.runtime-plugin/v1"]
    plugin_id: Identifier
    version: Version
    distribution: Identifier
    entry_point: Identifier
    worker_image: WorkerImage
    capabilities: list[Capability] = Field(min_length=1, max_length=2)
    required_bindings: list[Identifier] = Field(min_length=1, max_length=64)
    required_parameters: list[Identifier] = Field(default_factory=list, max_length=64)
    model_bindings: dict[Identifier, Identifier] = Field(default_factory=dict, max_length=16)

    @model_validator(mode="after")
    def unique_declarations(self) -> Self:
        for values in (self.capabilities, self.required_bindings, self.required_parameters):
            if len(values) != len(set(values)):
                raise ValueError("plugin declarations must be unique")
        if not set(self.model_bindings.values()).issubset(self.required_bindings):
            raise ValueError("model bindings must name declared guest bindings")
        if "guest.verify" not in self.capabilities:
            raise ValueError("a runtime plugin must provide readiness verification")
        return self

    @property
    def digest(self) -> str:
        return canonical_digest(self.model_dump(mode="json"))


class GuestTarget(ClosedModel):
    """Authorized projection; cloud locators, passwords and private keys stay in core."""

    node_address: Annotated[str, Field(min_length=1, max_length=1024)]
    os_family: Literal["linux", "windows"]
    private_address: Annotated[str, Field(max_length=256)] = ""
    public_key: Annotated[str, Field(max_length=16_384)] = ""


class InspectionInput(ClosedModel):
    """Installation probe with no range, guest, credential, or operation context."""

    protocol: Literal["shifter.runtime-plugin/v1"]
    invocation_id: UUID
    phase: Literal["inspect"]
    manifest: PluginManifest

    @property
    def digest(self) -> str:
        return canonical_digest(self.model_dump(mode="json"))


class InspectionResult(ClosedModel):
    """Checks packaging compatibility, never claims guest readiness."""

    protocol: Literal["shifter.runtime-plugin/v1"]
    invocation_id: UUID
    phase: Literal["inspect"]
    input_digest: Digest
    status: Literal["compatible", "failed"]

    def authorize(self, request: InspectionInput) -> None:
        if self.invocation_id != request.invocation_id or self.input_digest != request.digest:
            raise ValueError("plugin inspection does not match its invocation")


class RuntimeInput(ClosedModel):
    """Exactly one operation and phase; values are never taken from plugin output."""

    protocol: Literal["shifter.runtime-plugin/v1"]
    invocation_id: UUID
    operation_id: UUID
    pack_digest: Digest
    manifest: PluginManifest
    phase: Phase
    provider: Literal["aws", "gcp"]
    range_id: Annotated[int, Field(strict=True, ge=1)]
    targets: dict[Identifier, GuestTarget] = Field(min_length=1, max_length=64)
    parameters: dict[Identifier, Annotated[str, Field(max_length=8192)]] = Field(default_factory=dict, max_length=64)

    @model_validator(mode="after")
    def validate_bindings(self) -> Self:
        if set(self.targets) != set(self.manifest.required_bindings):
            raise ValueError("target bindings must exactly match the installed declaration")
        if set(self.parameters) != set(self.manifest.required_parameters):
            raise ValueError("parameter bindings must exactly match the installed declaration")
        if len(self.model_dump_json().encode("utf-8")) > MAX_INPUT_BYTES:
            raise ValueError("plugin input exceeds its bound")
        return self

    @property
    def digest(self) -> str:
        return canonical_digest(self.model_dump(mode="json"))


class GuestValueReference(ClosedModel):
    """A public value resolved by the host from an original guest binding.

    Values reach the guest action only, never the isolated planning worker.
    This cannot name an arbitrary output key, secret reference, or cloud object.
    """

    binding: Identifier
    field: Literal["private_address", "participant_ssh_public_key"]


class GuestAction(ClosedModel):
    """An action on a declared guest; interpreter and transport are host-owned."""

    action_id: Identifier
    binding: Identifier
    script: Annotated[str, Field(min_length=1, max_length=65_536)] = Field(repr=False)
    timeout_seconds: Annotated[int, Field(strict=True, ge=1, le=300)] = 60
    runtime_values: dict[Identifier, GuestValueReference] = Field(default_factory=dict, max_length=64)


class RuntimePlan(ClosedModel):
    """Untrusted worker response. Core must bind it to input before execution."""

    protocol: Literal["shifter.runtime-plugin/v1"]
    invocation_id: UUID
    input_digest: Digest
    phase: Phase
    status: Literal["planned", "failed"]
    failure_code: Literal["", "incompatible", "invalid-input", "planning-failed"] = ""
    actions: list[GuestAction] = Field(default_factory=list, max_length=64, repr=False)

    @model_validator(mode="after")
    def validate_plan(self) -> Self:
        if self.status == "failed":
            if not self.failure_code or self.actions:
                raise ValueError("failed planning must carry only a bounded failure code")
        elif self.failure_code:
            raise ValueError("planned actions cannot carry a failure code")
        elif self.phase == "validate" and self.actions:
            raise ValueError("validation cannot execute guest actions")
        elif self.phase == "verify" and not self.actions:
            raise ValueError("readiness requires at least one verification action")
        if len({action.action_id for action in self.actions}) != len(self.actions):
            raise ValueError("action identifiers must be unique")
        if sum(action.timeout_seconds for action in self.actions) > 1200:
            raise ValueError("plugin plan exceeds the execution budget")
        if len(self.model_dump_json().encode("utf-8")) > MAX_OUTPUT_BYTES:
            raise ValueError("plugin output exceeds its bound")
        return self

    def authorize(self, request: RuntimeInput) -> None:
        """Reject replay, another phase or operation, and undeclared guest targets."""
        if (
            self.invocation_id != request.invocation_id
            or self.input_digest != request.digest
            or self.phase != request.phase
            or any(action.binding not in request.targets for action in self.actions)
            or any(
                value.binding not in request.targets
                for action in self.actions
                for value in action.runtime_values.values()
            )
        ):
            raise ValueError("plugin plan does not match its authorized invocation")
        capability = "guest.verify" if self.phase == "verify" else "guest.configure"
        if self.actions and capability not in request.manifest.capabilities:
            raise ValueError("plugin plan requires an undeclared capability")


class RuntimePlugin(Protocol):
    """Author implementation loaded only inside the isolated worker."""

    def plan(self, request: RuntimeInput) -> RuntimePlan: ...


def parse_input(raw: str | bytes) -> RuntimeInput | InspectionInput:
    """Parse a bounded request without importing any executable plugin."""
    value = decode_message(raw, limit=MAX_INPUT_BYTES)
    if isinstance(value, dict) and value.get("phase") == "inspect":
        return InspectionInput.model_validate(value)
    return RuntimeInput.model_validate(value)


def parse_result(raw: str | bytes, request: RuntimeInput | InspectionInput) -> RuntimePlan | InspectionResult:
    """Host-side parser: validate shape and invocation before using worker output."""
    value = decode_message(raw, limit=MAX_OUTPUT_BYTES)
    if isinstance(request, InspectionInput):
        inspection = InspectionResult.model_validate(value)
        inspection.authorize(request)
        return inspection
    plan = RuntimePlan.model_validate(value)
    plan.authorize(request)
    return plan
