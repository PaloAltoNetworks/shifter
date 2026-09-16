"""Closed settings model and secret-reference grammar for the AWS backend bundle.

Split out of :mod:`installation.registry` for GCP symmetry (its GCP counterpart
lives in :mod:`installation.settings_gcp`). This is the operator-authored AWS
intent carried under ``RootConfig.settings`` when ``backend: aws`` — only the
deployment region today. It is the ``settings_model`` the ``aws`` bundle
registers, so :meth:`installation.contract.BackendBundle.validate_settings`
validates an AWS ``shifter.yaml``'s backend-specific ``settings`` against it
before any Terraform, Helm, or cluster mutation.

The model is *closed* (``extra="forbid"``): an unknown AWS setting fails fast
rather than being silently ignored (ADR-011). ``region`` is constrained with a
schema-expressible ``pattern`` (not a custom validator) so the exact grammar the
loader enforces is also carried into the *published* settings JSON schema — a
contract consumer validating against the published schema cannot accept a region
``load_root_config`` would reject (the boundary-contract gap #728 must not open).

The shared cross-backend ``range_egress`` policy is intentionally *absent*,
mirroring :class:`installation.settings_gcp.GcpBackendSettings`: it is owned and
validated by :mod:`installation.range_egress` (verbatim, non-secret CIDR
diagnostics, #775), and the loader strips it out of ``settings`` and validates it
separately for every backend.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

# A plausible AWS region token: two letters, one or more lowercase words, then a trailing
# number — ``us-east-2``, ``us-gov-east-1``, ``ap-southeast-4``. Deliberately permissive:
# the exact region set is an AWS concern validated at deploy time, so this only catches
# config-time typos (wrong case, underscores, missing number) rather than pinning a list.
# It is applied via ``Field(pattern=...)`` (not a ``@field_validator``) so the *same*
# constraint governs both runtime validation and the published JSON schema — a validator
# would enforce it at load time while leaving the published contract permitting any string
# (the boundary-contract gap #728 must not open).
AWS_REGION_PATTERN = r"^[a-z]{2}(?:-[a-z]+)+-\d+$"

# The reference grammar shared by both AWS secrets: an AWS Secrets Manager secret name or
# ARN, a GitHub Actions secret name, or an environment variable name — a single-line token
# of reference-safe characters, matched full-string by ``RequiredSecret.matches_reference``
# (which accepts ``prompt`` independently). This is a *positive* grammar layered on top of
# the root schema's raw-material rejection (multi-line / PEM / over-long), not a duplicate
# of it; it never sees or echoes the value.
AWS_REFERENCE_PATTERN = r"[A-Za-z0-9][A-Za-z0-9._/+=@:-]*"

# The reference_grammar description shared by both AWS secrets (kept in one place so the
# human text and the machine pattern stay in step).
AWS_REFERENCE_GRAMMAR = (
    "an AWS Secrets Manager secret name or ARN, a GitHub Actions secret name, an environment "
    "variable, or the literal 'prompt'"
)


class AwsSettings(BaseModel):
    """Closed operator-intent settings for the AWS backend (PLAT-2006, GH #728).

    Only genuine operator intent lives here. Terraform variables, generated runtime
    outputs, workflow secret names, and provider SDK payloads are *not* settings — copying
    them in would turn ``settings`` into a second provider schema (preflight #728).
    ``extra='forbid'`` fails unknown AWS settings closed, so a typo or a stale key is a
    config-time error rather than a silently-ignored value.

    The shared cross-backend ``range_egress`` policy is intentionally *absent*: it is owned
    and validated by :mod:`installation.range_egress` (which surfaces verbatim, non-secret
    CIDR diagnostics, #775), and the loader validates it separately for every backend. See
    the module docstring.
    """

    model_config = ConfigDict(extra="forbid")

    region: str = Field(pattern=AWS_REGION_PATTERN)
