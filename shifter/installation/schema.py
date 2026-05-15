"""Typed schema for the root installation configuration (``shifter.yaml``).

``shifter.yaml`` is the single user-authored contract that selects a Shifter backend
bundle and supplies deployment-level settings. This module is the *one* authoritative
model for that file — setup, doctor, CI, and (later) runtime derivation must validate
against it rather than re-parsing the YAML by hand or maintaining a parallel schema.

Scope: this module owns the *root* keys (``version``, ``backend``, ``deployment``,
``secrets``, ``settings``) — including that ``settings`` is a mapping, but not its
contents: validating the per-backend ``settings`` keys (and the per-backend secret
reference grammar) belongs to the selected backend bundle's contract, and the loader
(:mod:`installation.loader`) runs those checks against the bundle from
:mod:`installation.registry`, which is also where the known backends and the profiles
each supports come from.
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from . import registry

# A DNS-label-safe identifier: lowercase letters/digits with internal hyphens, 1-40 chars.
_DEPLOYMENT_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$")
# A single hostname label: lowercase letters/digits with internal hyphens, 1-63 chars.
_DOMAIN_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
# A logical secret name (the key in the ``secrets`` mapping).
_SECRET_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
# The root schema treats ``secrets`` values as opaque references and cannot fully
# distinguish a short secret value from a secret *name* — the selected backend bundle
# owns the precise per-provider reference grammar (``RequiredSecret.reference_grammar`` /
# ``reference_pattern`` in ``installation.contract``), and gitleaks scans for raw
# secrets independently. This package only rejects values that are *clearly* raw key
# material: multi-line, PEM-headered, or implausibly long. The cap sits well above the
# longest realistic reference (an AWS Secrets Manager name is up to 512 chars, plus
# ARN/region/version text; a GCP Secret Manager resource path is well under that) while
# still catching a pasted base64 blob or PEM body.
_MAX_SECRET_REFERENCE_LEN = 1024
_MAX_DOMAIN_LEN = 253

#: Schema versions this module understands.
SUPPORTED_VERSIONS: tuple[int, ...] = (1,)


def _validate_deployment_name(value: str) -> str:
    if not _DEPLOYMENT_NAME_RE.match(value):
        raise ValueError(
            "must be 1-40 characters of lowercase letters, digits, and internal hyphens (a DNS-label-safe identifier)"
        )
    return value


def _assert_domain_surface(value: str) -> None:
    """Reject whole-string formatting problems: empty/whitespace/case/trailing-dot/IP."""
    if not value or value != value.strip():
        raise ValueError("must be a non-empty hostname with no surrounding whitespace")
    if value != value.lower():
        raise ValueError("must be lowercase")
    if value.endswith("."):
        raise ValueError("must not end with a trailing dot")
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return
    raise ValueError("must be a DNS hostname, not an IP address")


def _assert_domain_labels(value: str, labels: list[str]) -> None:
    """Reject label-shape problems: too few labels, oversize total, malformed labels, invalid TLD."""
    if len(labels) < 2:
        raise ValueError("must be a fully qualified hostname with at least two labels (e.g. shifter.example.com)")
    if len(value) > _MAX_DOMAIN_LEN:
        raise ValueError(f"must be at most {_MAX_DOMAIN_LEN} characters")
    for label in labels:
        if not _DOMAIN_LABEL_RE.match(label):
            raise ValueError(
                f"label {label!r} is invalid: each label must be 1-63 characters of lowercase letters, "
                "digits, and internal hyphens"
            )
    tld = labels[-1]
    if tld.isdigit() or len(tld) < 2:
        raise ValueError(
            f"the rightmost label {tld!r} is not a valid public DNS suffix; the hostname must end in a "
            "registry-style TLD (e.g. shifter.example.com)"
        )


def _validate_domain(value: str) -> str:
    _assert_domain_surface(value)
    _assert_domain_labels(value, value.split("."))
    return value


def _validate_secret_entry(key: str, raw_value: Any) -> tuple[str | None, str | None]:
    """Validate one ``secrets`` mapping entry.

    Returns ``(reference, None)`` for a usable entry, or ``(None, problem)`` describing
    what is wrong. The schema treats ``secrets`` values as opaque references and only
    rejects ones that are *clearly* raw key material; see :data:`_MAX_SECRET_REFERENCE_LEN`.
    """
    if not _SECRET_NAME_RE.match(key):
        return None, f"secret name {key!r} must match ^[a-z][a-z0-9_]*$"
    if not isinstance(raw_value, str):
        return None, f"secret reference for {key!r} must be a string"
    ref: str = raw_value
    if ref != ref.strip() or not ref.strip():
        return None, f"secret reference for {key!r} must be a non-empty string with no surrounding whitespace"
    if any(ch in ref for ch in "\r\n\t"):
        return None, (
            f"secret reference for {key!r} must be a single line; the root config holds a reference "
            "(a provider secret name, a GitHub Actions secret name, an env var, or 'prompt'), not the "
            "secret value itself"
        )
    if ref.startswith("-----BEGIN"):
        return None, (
            f"secret reference for {key!r} looks like raw PEM key/certificate material; store the value in "
            "a secret store and reference it by name"
        )
    if len(ref) > _MAX_SECRET_REFERENCE_LEN:
        return None, (
            f"secret reference for {key!r} is implausibly long for a reference ({len(ref)} characters, "
            f"limit {_MAX_SECRET_REFERENCE_LEN}); the root config holds a reference, not the secret value itself"
        )
    return ref, None


def _validate_secrets(value: Any) -> dict[str, str]:
    # A *present* ``secrets:`` key must be a mapping. An explicit YAML null (a dangling
    # ``secrets:``) is treated as a malformed block and rejected, not silently coerced
    # to ``{}`` — omit the key entirely to get the empty default.
    if not isinstance(value, dict):
        raise ValueError("must be a mapping of logical secret name to a reference identifier")
    problems: list[str] = []
    cleaned: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key)
        ref, problem = _validate_secret_entry(key, raw_value)
        if problem is not None:
            problems.append(problem)
        elif ref is not None:
            cleaned[key] = ref
    if problems:
        raise ValueError("; ".join(problems))
    return cleaned


def _validate_settings(value: Any) -> dict[str, Any]:
    # The root schema only checks that ``settings`` is a mapping; its *contents* are
    # backend-specific and are validated by the selected backend bundle's contract
    # (#1113) — including which settings are required for that backend and which keys
    # are even allowed. Do not add per-backend settings validation here; that dispatch
    # belongs to the backend bundle, not the root schema. A present-but-null
    # ``settings:`` is rejected as malformed (omit the key to get the empty default).
    if not isinstance(value, dict):
        raise ValueError(
            "must be a mapping of backend-specific keys; the selected backend bundle validates its contents"
        )
    return value


class DeploymentConfig(BaseModel):
    """Deployment-level settings shared by every backend."""

    model_config = ConfigDict(extra="forbid")

    name: str
    domain: str
    # Validated against the registry's known profiles; the profile/backend combination
    # is checked by RootConfig once the backend is also known.
    profile: str = "prod"

    @field_validator("name")
    @classmethod
    def _check_name(cls, v: str) -> str:
        return _validate_deployment_name(v)

    @field_validator("domain")
    @classmethod
    def _check_domain(cls, v: str) -> str:
        return _validate_domain(v)

    @field_validator("profile")
    @classmethod
    def _check_profile(cls, v: str) -> str:
        if v not in registry.KNOWN_PROFILES:
            valid = ", ".join(sorted(registry.KNOWN_PROFILES))
            raise ValueError(f"unknown deployment profile {v!r}; must be one of {valid}")
        return v


class RootConfig(BaseModel):
    """The authoritative root installation configuration loaded from ``shifter.yaml``."""

    model_config = ConfigDict(extra="forbid")

    version: int = 1
    backend: str
    deployment: DeploymentConfig
    secrets: dict[str, str] = Field(default_factory=dict)
    settings: dict[str, Any] = Field(default_factory=dict)

    @field_validator("version", mode="before")
    @classmethod
    def _check_version(cls, v: Any) -> int:
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError("must be the integer 1")
        if v not in SUPPORTED_VERSIONS:
            supported = ", ".join(str(s) for s in SUPPORTED_VERSIONS)
            raise ValueError(f"unsupported schema version {v!r}; supported versions: {supported}")
        return v

    @field_validator("backend")
    @classmethod
    def _check_backend(cls, v: str) -> str:
        if v not in registry.KNOWN_BACKENDS:
            valid = ", ".join(sorted(registry.KNOWN_BACKENDS))
            raise ValueError(f"unknown backend {v!r}; must be one of {valid}")
        return v

    @field_validator("secrets", mode="before")
    @classmethod
    def _check_secrets(cls, v: Any) -> dict[str, str]:
        return _validate_secrets(v)

    @field_validator("settings", mode="before")
    @classmethod
    def _check_settings(cls, v: Any) -> dict[str, Any]:
        return _validate_settings(v)

    @model_validator(mode="after")
    def _check_profile_backend_combination(self) -> RootConfig:
        allowed = registry.ALLOWED_PROFILES.get(self.backend, frozenset())
        if self.deployment.profile not in allowed:
            allowed_text = ", ".join(sorted(allowed)) or "(none)"
            raise ValueError(
                f"deployment profile {self.deployment.profile!r} is not supported by backend "
                f"{self.backend!r}; allowed profiles for {self.backend!r}: {allowed_text}"
            )
        return self
