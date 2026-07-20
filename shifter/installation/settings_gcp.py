"""Closed settings model for the GCP backend bundle (PLAT-2003, #729).

This is the operator-authored GCP intent carried under ``RootConfig.settings`` when
``backend: gcp`` — the deployment project and region. It is the ``settings_model`` the
``gcp`` bundle registers (:mod:`installation.registry`), so
:meth:`installation.contract.BackendBundle.validate_settings` validates a GCP
``shifter.yaml``'s backend-specific ``settings`` against it before any Terraform, Helm, or
cluster mutation.

The model is *closed* (``extra="forbid"``): an unknown GCP setting fails fast rather than
being silently ignored, which is the contract guarantee the backend-bundle design relies on
(ADR-011). ``project_id`` and ``region`` are constrained with schema-expressible ``pattern``
/ length bounds (not custom validators) so the exact same grammar the loader enforces is
also carried into the *published* settings JSON schema — a contract consumer validating
against the published schema cannot accept an identifier ``load_root_config`` would reject.

The shared cross-backend ``range_egress`` policy is intentionally *absent* here, mirroring
:class:`installation.registry.AwsSettings`: it is owned and validated by
:mod:`installation.range_egress` (verbatim, non-secret CIDR diagnostics, #775), and the
loader (:mod:`installation.loader`) strips it out of ``settings`` before validating the
backend model and validates it separately for every backend. See
``docs/architecture/gcp-backend-bundle-migration-preflight-729.md``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

# GCP project id grammar: 6-30 characters, starting with a lowercase letter, then lowercase
# letters, digits, and hyphens, and not ending in a hyphen. This is Google's documented
# project-id rule; expressing it as a schema ``pattern`` (rather than a custom validator)
# turns a typo into a fail-fast config error AND publishes the constraint into the settings
# JSON schema so downstream contract consumers reject the same identifiers.
_GCP_PROJECT_ID_PATTERN = r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$"
# GCP region/location grammar: a lowercase DNS-label-ish token (letters, digits, internal
# hyphens), e.g. ``us-central1``, ``europe-west4``. Kept deliberately permissive over the
# exact region list, which changes as Google adds regions; the deploy tooling validates a
# region actually exists.
_GCP_REGION_PATTERN = r"^[a-z][a-z0-9-]*[a-z0-9]$"


class GcpBackendSettings(BaseModel):
    """Closed operator-intent settings for the ``gcp`` backend bundle (PLAT-2003, #729).

    Only genuine operator intent lives here (project and region). Terraform variables,
    generated runtime outputs, and provider SDK payloads are not settings — copying them in
    would turn ``settings`` into a second provider schema. ``extra='forbid'`` fails unknown
    GCP settings closed. The shared cross-backend ``range_egress`` policy is deliberately not
    declared; the loader validates it separately for every backend (see the module docstring).
    """

    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(
        pattern=_GCP_PROJECT_ID_PATTERN,
        min_length=6,
        max_length=30,
        description=(
            "GCP project id: 6-30 characters, a lowercase letter followed by lowercase letters, digits, "
            "and hyphens, not ending in a hyphen."
        ),
    )
    region: str = Field(
        pattern=_GCP_REGION_PATTERN,
        description="Lowercase GCP region/location token (letters, digits, and internal hyphens), e.g. 'us-central1'.",
    )
