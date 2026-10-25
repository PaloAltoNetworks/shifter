"""GCP range audit telemetry policy (issue #2535).

One immutable typed contract for the three provider-generated range logging controls:

* VPC Flow Logs on range subnetworks,
* Cloud NAT logging on range egress gateways,
* Cloud Audit Logs Data Access entries for Vertex AI (``aiplatform.googleapis.com``).

Every control is on by default. The operator may change a control through
``settings.range_telemetry`` in ``shifter.yaml`` because each one has a cost. The
installation package validates that block with this type, renders it into the Terraform
bridge and the ``GCP_RANGE_TELEMETRY_POLICY_JSON`` runtime value, and the provisioner
parses the runtime value with this type again. Fields use provider enum spellings so
consumers translate shapes, not meanings.
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictBool, ValidationError
from pydantic.types import StrictFloat, StrictInt

__all__ = [
    "FlowLogAggregationInterval",
    "FlowLogMetadata",
    "GcpRangeTelemetryPolicy",
    "GcpRangeTelemetryPolicyError",
    "NatLogFilter",
    "NatLogPolicy",
    "VertexDataAccessLogPolicy",
    "VpcFlowLogPolicy",
    "dump_policy_json",
    "load_policy_json",
]


class FlowLogAggregationInterval(StrEnum):
    """Subnetwork flow-log aggregation intervals supported by Compute Engine."""

    INTERVAL_5_SEC = "INTERVAL_5_SEC"
    INTERVAL_30_SEC = "INTERVAL_30_SEC"
    INTERVAL_1_MIN = "INTERVAL_1_MIN"
    INTERVAL_5_MIN = "INTERVAL_5_MIN"
    INTERVAL_10_MIN = "INTERVAL_10_MIN"
    INTERVAL_15_MIN = "INTERVAL_15_MIN"


class FlowLogMetadata(StrEnum):
    """Flow-log metadata modes. ``CUSTOM_METADATA`` is not offered (no field list)."""

    INCLUDE_ALL_METADATA = "INCLUDE_ALL_METADATA"
    EXCLUDE_ALL_METADATA = "EXCLUDE_ALL_METADATA"


class NatLogFilter(StrEnum):
    """Cloud NAT log filters: both record categories, errors only, or translations only."""

    ALL = "ALL"
    ERRORS_ONLY = "ERRORS_ONLY"
    TRANSLATIONS_ONLY = "TRANSLATIONS_ONLY"


# Secondary sampling in (0, 1]. Zero would emit nothing while claiming the control is on;
# disable the control explicitly instead. Strict types reject bools and numeric strings.
_FlowSampling = Annotated[StrictFloat | StrictInt, Field(gt=0, le=1), AfterValidator(float)]


class VpcFlowLogPolicy(BaseModel):
    """VPC Flow Logs on every range subnetwork."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: StrictBool = True
    aggregation_interval: FlowLogAggregationInterval = FlowLogAggregationInterval.INTERVAL_5_SEC
    flow_sampling: _FlowSampling = 0.5
    metadata: FlowLogMetadata = FlowLogMetadata.INCLUDE_ALL_METADATA


class NatLogPolicy(BaseModel):
    """Cloud NAT logging on every range egress gateway."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: StrictBool = True
    filter: NatLogFilter = NatLogFilter.ALL


class VertexDataAccessLogPolicy(BaseModel):
    """Vertex AI ``DATA_READ`` and ``DATA_WRITE`` audit logs, with no exempted callers."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: StrictBool = True


class GcpRangeTelemetryPolicyError(Exception):
    """The range telemetry policy JSON is blank, malformed, or invalid."""


class GcpRangeTelemetryPolicy(BaseModel):
    """Operator range telemetry policy for a GCP deployment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    vpc_flow_logs: VpcFlowLogPolicy = Field(default_factory=VpcFlowLogPolicy)
    nat_logs: NatLogPolicy = Field(default_factory=NatLogPolicy)
    vertex_data_access_logs: VertexDataAccessLogPolicy = Field(default_factory=VertexDataAccessLogPolicy)


def _error_locations(exc: ValidationError) -> str:
    """Name the rejected fields without echoing their values."""
    return ", ".join(sorted({".".join(str(part) for part in error["loc"]) or "<root>" for error in exc.errors()}))


def load_policy_json(raw: str | None) -> GcpRangeTelemetryPolicy:
    """Parse the runtime policy value, failing closed on bad input.

    Only absence (``None``) selects the default-on policy. A present but blank or invalid
    value is a broken deployment substitution and is rejected, so a typo can never turn
    a control off silently.
    """
    if raw is None:
        return GcpRangeTelemetryPolicy()
    text = raw.strip()
    if not text:
        raise GcpRangeTelemetryPolicyError("range telemetry policy is present but blank; unset it to use the defaults")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise GcpRangeTelemetryPolicyError("range telemetry policy is not valid JSON") from exc
    if not isinstance(data, dict):
        raise GcpRangeTelemetryPolicyError("range telemetry policy must be a JSON object")
    try:
        return GcpRangeTelemetryPolicy.model_validate(data)
    except ValidationError as exc:
        raise GcpRangeTelemetryPolicyError(f"range telemetry policy is invalid at: {_error_locations(exc)}") from None


def dump_policy_json(policy: GcpRangeTelemetryPolicy) -> str:
    """Serialize the policy to compact canonical JSON for env delivery."""
    return policy.model_dump_json()
