"""Scenario overlay declarations.

A scenario is expressed as a ScenarioOverlaySpec that patches a
baseline CTFRangeSpec: image swaps, config patches, flag plants, vuln
injections, network-policy patches, scheduled events, CTFd authoring,
and sidecar additions. See
scenario-dev/hospital/design/scenario-overlay.md for the overlay
mental model.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Discriminator, Field, field_validator, model_validator

from .flag import FlagSpec

OperationKind = Literal[
    "tag",
    "config_patch",
    "image_swap",
    "plant_flag",
    "inject_vuln",
    "network_policy_patch",
    "schedule_event",
    "ctfd_config",
    "sidecar_add",
]


class OverlayOperationBase(BaseModel):
    """Fields common to every overlay operation."""

    op_id: str
    op: OperationKind
    depends_on: list[str] = []
    rationale: str | None = None

    @field_validator("op_id")
    @classmethod
    def op_id_nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("op_id must be non-empty")
        return v.strip()


class TagOperation(OverlayOperationBase):
    op: Literal["tag"] = "tag"
    target: str
    tags: dict[str, str]


class ImageSwapOperation(OverlayOperationBase):
    op: Literal["image_swap"] = "image_swap"
    target: str
    from_digest: str
    to_digest: str
    wait_for_health: bool = True


class ConfigPatchOperation(OverlayOperationBase):
    op: Literal["config_patch"] = "config_patch"
    target: str
    file: str
    mode: Literal["overwrite", "append", "sed"] = "overwrite"
    content: str | None = None
    sed_expressions: list[str] = []
    reload_command: str | None = None


class PlantFlagPolicy(BaseModel):
    kind: Literal[
        "static_file",
        "db_row",
        "registry_value",
        "secret",
        "programmatic_marker",
    ]
    # static_file
    path: str | None = None
    content: str | None = None
    # db_row
    table: str | None = None
    columns: dict[str, str] | None = None
    # registry_value
    hive: str | None = None
    key: str | None = None
    name: str | None = None
    reg_type: Literal["REG_SZ", "REG_DWORD", "REG_BINARY"] | None = None
    # secret
    secret_name: str | None = None
    secret_keys: dict[str, str] | None = None
    # programmatic_marker
    marker_name: str | None = None
    expected_state: dict[str, str] | None = None


class PlantFlagOperation(OverlayOperationBase):
    op: Literal["plant_flag"] = "plant_flag"
    flag_id: str
    target: str
    policy: PlantFlagPolicy


class ADUserInjection(BaseModel):
    sam: str
    spn: str | None = None
    password_policy: Literal["weak", "normal", "strong"] = "normal"
    group_memberships: list[str] = []


class InjectVulnOperation(OverlayOperationBase):
    op: Literal["inject_vuln"] = "inject_vuln"
    target: str
    vuln_id: str
    patch: dict[str, Any] | None = None
    ad_user: ADUserInjection | None = None
    override_safety_envelope: bool = False


class NetworkPolicyPatchOperation(OverlayOperationBase):
    op: Literal["network_policy_patch"] = "network_policy_patch"
    target: str
    change: Literal[
        "allow_egress_to",
        "deny_egress_to",
        "allow_ingress_from",
        "deny_ingress_from",
    ]
    counterparty: str
    schedule_after_day: int | None = None


class ScheduledAction(BaseModel):
    kind: Literal[
        "toggle",
        "http_call",
        "kubectl_patch",
        "publish_message",
        "custom_job",
    ]
    target: str | None = None
    property: str | None = None
    value: Any = None
    url: str | None = None
    method: str | None = None
    body: str | None = None
    patch: dict[str, Any] | None = None
    topic: str | None = None
    message: str | None = None
    job_image: str | None = None
    job_cmd: list[str] | None = None


class ScheduleEventOperation(OverlayOperationBase):
    op: Literal["schedule_event"] = "schedule_event"
    event_id: str
    at: str
    action: ScheduledAction


class CTFdPageRef(BaseModel):
    title: str
    slug: str
    from_file: str
    visible_from_day: int | None = None


class CTFdConfigOperation(OverlayOperationBase):
    op: Literal["ctfd_config"] = "ctfd_config"
    challenges_from: Literal["flags", "explicit_list"] = "flags"
    pages: list[CTFdPageRef] = []
    hints_policy: Literal["none", "one", "progressive"] = "progressive"
    rate_limit_per_5min: int = 15

    @field_validator("rate_limit_per_5min")
    @classmethod
    def rate_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("rate_limit_per_5min must be positive")
        return v


class SidecarAddOperation(OverlayOperationBase):
    op: Literal["sidecar_add"] = "sidecar_add"
    target: str
    sidecar_name: str
    image: str
    env: dict[str, str] = {}
    args: list[str] = []


AnyOverlayOperation = Annotated[
    TagOperation
    | ImageSwapOperation
    | ConfigPatchOperation
    | PlantFlagOperation
    | InjectVulnOperation
    | NetworkPolicyPatchOperation
    | ScheduleEventOperation
    | CTFdConfigOperation
    | SidecarAddOperation,
    Discriminator("op"),
]


class SafetyReview(BaseModel):
    """Required when an overlay overrides a safety envelope.

    Operator-level acknowledgement that the envelope change has been
    reviewed and does not enable simulated-harm paths. Consumed by the
    overlay applier's validation step.
    """

    reviewed_by: str
    reviewed_at: str
    summary: str


class ScenarioOverlayMetadata(BaseModel):
    title: str
    summary: str
    duration_days: int
    difficulty_profile: Literal["mixed", "novice", "intermediate", "advanced"] = "mixed"
    ai_agent_expected: bool = True
    safety_notes: str | None = None


class ScenarioOverlaySpec(BaseModel):
    """Overlay applied on top of a baseline CTFRangeSpec."""

    overlay_version: Literal["v1"] = "v1"
    scenario_id: str
    cyberscript_version: Literal["v1"] = "v1"
    baseline_fingerprint: str
    operations: list[AnyOverlayOperation] = Field(default_factory=list)
    flags: list[FlagSpec] = Field(default_factory=list)
    metadata: ScenarioOverlayMetadata
    safety_review: SafetyReview | None = None

    @field_validator("scenario_id")
    @classmethod
    def scenario_id_nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("scenario_id must be non-empty")
        return v.strip()

    @model_validator(mode="after")
    def validate_unique_op_ids(self) -> ScenarioOverlaySpec:
        seen: set[str] = set()
        for op in self.operations:
            if op.op_id in seen:
                raise ValueError(f"duplicate op_id {op.op_id!r}")
            seen.add(op.op_id)
        return self

    @model_validator(mode="after")
    def validate_no_dep_cycles(self) -> ScenarioOverlaySpec:
        """Ensure depends_on forms a DAG."""
        op_ids = {op.op_id for op in self.operations}
        deps: dict[str, list[str]] = {op.op_id: list(op.depends_on) for op in self.operations}
        for op in self.operations:
            for d in op.depends_on:
                if d not in op_ids:
                    raise ValueError(
                        f"op {op.op_id!r} depends_on unknown op {d!r}"
                    )
        # DFS cycle check
        visited: dict[str, int] = {k: 0 for k in op_ids}  # 0=unseen,1=onstack,2=done

        def visit(n: str, stack: list[str]) -> None:
            if visited[n] == 1:
                raise ValueError(
                    f"dependency cycle: {' -> '.join([*stack, n])}"
                )
            if visited[n] == 2:
                return
            visited[n] = 1
            for d in deps.get(n, []):
                visit(d, [*stack, n])
            visited[n] = 2

        for n in op_ids:
            if visited[n] == 0:
                visit(n, [])
        return self

    @model_validator(mode="after")
    def validate_unique_flag_ids(self) -> ScenarioOverlaySpec:
        seen: set[str] = set()
        for f in self.flags:
            if f.id in seen:
                raise ValueError(f"duplicate flag id {f.id!r}")
            seen.add(f.id)
        return self

    @model_validator(mode="after")
    def validate_safety_review_presence(self) -> ScenarioOverlaySpec:
        """Any InjectVulnOperation with override_safety_envelope=True demands a safety_review block."""
        for op in self.operations:
            if isinstance(op, InjectVulnOperation) and op.override_safety_envelope:
                if self.safety_review is None:
                    raise ValueError(
                        f"op {op.op_id!r} overrides safety_envelope; scenario must include safety_review block"
                    )
        return self
