"""Provider-neutral range egress policy (PLAT-220).

The platform shall accept configuration for allowlisted egress IP ranges that apply
uniformly to range network egress on every supported cloud backend (AWS, GCP). This
module owns the public *shape* and the cross-backend validation of that policy. AWS
and GCP backend implementations consume the validated form (canonical CIDR strings,
explicit mode) and bridge into their cloud-native firewall syntax — AWS Network
Firewall rule groups under ``platform/terraform/modules/range/vpc/firewall.tf`` and
GCP VPC firewall egress rules under ``platform/terraform/gcp/modules/platform-core``.

The validation logic deliberately lives here, not in either provider's Terraform
module, so the installation package remains the validation boundary and operators
get the same error envelopes for both clouds (``InstallationConfigError``).

Default behavior when the operator omits the block is ``mode='status-quo'``: each
backend keeps its existing posture (AWS Network Firewall with the existing
allow-lanes; GCP Cloud NAT with no egress filter). ``mode='deny-all'`` and
``mode='allowlist'`` cross over into active enforcement.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError, model_validator

from .errors import ConfigIssue


class RangeEgressMode(StrEnum):
    """Operating mode for the range egress policy.

    ``status-quo`` is the documented default when the operator omits the block: each
    backend preserves its existing posture so PLAT-220 is opt-in. The other two modes
    are active platform contracts and apply identically on AWS and GCP.
    """

    STATUS_QUO = "status-quo"
    DENY_ALL = "deny-all"
    ALLOWLIST = "allowlist"


def _validate_cidr(value: str) -> str:
    """Validate one CIDR entry and return its canonical network form.

    Rejects malformed strings, missing prefix lengths, host-bits-set inputs, and the
    default routes ``0.0.0.0/0`` / ``::/0`` — an explicit allow-all is a separate
    operating mode, not a sentinel CIDR (out of scope for PLAT-220).
    """
    if not isinstance(value, str):
        raise ValueError("CIDR entries must be strings")
    if not value or value != value.strip():
        raise ValueError("CIDR entries must be non-empty with no surrounding whitespace")
    if "/" not in value:
        raise ValueError(f"{value!r} is missing a prefix length; use CIDR form (e.g. '10.0.0.0/24' or '8.8.8.8/32')")
    try:
        network = ipaddress.ip_network(value, strict=True)
    except ValueError as exc:
        # Try strict=False to surface a more useful error: host-bits-set vs. fully
        # malformed. ip_network rejects "10.0.0.0" (no prefix) at either strictness.
        try:
            relaxed = ipaddress.ip_network(value, strict=False)
        except ValueError:
            raise ValueError(f"{value!r} is not a valid CIDR: {exc}") from None
        raise ValueError(f"{value!r} has host bits set; use the network address {str(relaxed)!r} instead") from None
    if network.prefixlen == 0:
        raise ValueError(f"{value!r} is a default route (/0); allow-all is a separate mode, not a CIDR sentinel")
    return str(network)


CidrString = Annotated[str, AfterValidator(_validate_cidr)]


class RangeEgressPolicy(BaseModel):
    """Operator-declared egress policy for range networks (PLAT-220).

    The platform contract is provider-neutral: ``mode`` + ``allowed_cidrs``. AWS and
    GCP backends each translate this into their cloud-native firewall syntax.
    """

    model_config = ConfigDict(extra="forbid")

    mode: RangeEgressMode = RangeEgressMode.STATUS_QUO
    allowed_cidrs: list[CidrString] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_mode_invariants(self) -> RangeEgressPolicy:
        if self.mode == RangeEgressMode.ALLOWLIST and not self.allowed_cidrs:
            raise ValueError(
                "mode='allowlist' requires a non-empty allowed_cidrs list; use mode='deny-all' "
                "to forbid all egress or omit the block to preserve backend status-quo"
            )
        if self.mode != RangeEgressMode.ALLOWLIST and self.allowed_cidrs:
            raise ValueError(
                f"allowed_cidrs is only meaningful when mode='allowlist' (current mode={self.mode.value!r}); "
                "set mode='allowlist' or remove the allowed_cidrs list"
            )
        seen: set[str] = set()
        dupes: list[str] = []
        for cidr in self.allowed_cidrs:
            if cidr in seen:
                dupes.append(cidr)
            seen.add(cidr)
        if dupes:
            raise ValueError(f"duplicate CIDR(s) after normalization: {sorted(set(dupes))}")
        return self


#: The reserved key under ``RootConfig.settings`` that carries the policy.
SETTINGS_KEY = "range_egress"


def validate_settings_block(settings: Mapping[str, Any]) -> tuple[dict[str, Any], list[ConfigIssue]]:
    """Validate the ``range_egress`` block within a backend's ``settings`` mapping.

    Returns a (normalized_settings, issues) tuple:

    - ``normalized_settings`` is a shallow copy of the input with ``range_egress``
      replaced by the normalized form (canonical CIDR strings, default mode applied).
      When the block is absent, the input is returned unchanged.
    - ``issues`` is a list of sanitized :class:`ConfigIssue` records anchored under
      ``settings.range_egress``. CIDR allowlists are operator config, not secrets
      (preflight #775), so the underlying validation messages are surfaced verbatim
      rather than redacted as ``settings`` values are elsewhere.

    Callers that want fail-fast semantics can raise
    :class:`~installation.errors.InstallationConfigError` when issues is non-empty.
    """
    normalized = dict(settings)
    raw = settings.get(SETTINGS_KEY)
    issues: list[ConfigIssue] = []
    if raw is None:
        pass
    elif not isinstance(raw, Mapping):
        issues.append(
            ConfigIssue(
                f"settings.{SETTINGS_KEY}",
                f"must be a mapping with mode and allowed_cidrs; got {type(raw).__name__}",
            )
        )
    else:
        try:
            policy = RangeEgressPolicy.model_validate(dict(raw))
            normalized[SETTINGS_KEY] = policy.model_dump(mode="json")
        except ValidationError as exc:
            issues = _issues_from_pydantic_error(exc)
    return normalized, issues


def _issues_from_pydantic_error(exc: ValidationError) -> list[ConfigIssue]:
    """Convert a ``RangeEgressPolicy`` validation error to ``settings.range_egress.*`` issues.

    CIDRs are operator config (not secrets per PLAT-220 preflight), so the underlying
    message is surfaced. The path prefix anchors each issue under
    ``settings.range_egress`` so a multi-issue render maps clearly onto the user's YAML.
    """
    issues: list[ConfigIssue] = []
    for err in exc.errors():
        loc_parts = [str(part) for part in err["loc"]]
        path = ".".join(["settings", SETTINGS_KEY, *loc_parts]) if loc_parts else f"settings.{SETTINGS_KEY}"
        issues.append(ConfigIssue(path, err["msg"]))
    return issues
