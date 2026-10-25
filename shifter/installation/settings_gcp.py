"""Closed settings model for the GCP backend bundle (PLAT-2003, #729).

This is the operator-authored GCP intent carried under ``RootConfig.settings`` when
``backend: gcp`` — the deployment project, dynamic range-secret project, and region. It is the ``settings_model`` the
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

from collections.abc import Mapping
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from shared.gcp_range_telemetry import GcpRangeTelemetryPolicy

from .capacity_profiles_gcp import CapacityProfileId, resolve_capacity_profile
from .gcp_model_broker import GcpModelBrokerSettings
from .model_broker_runtime import ModelBrokerRuntimeSettings

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
_GCP_NAMED_RESOURCE_PATTERN = r"^projects/[a-z][a-z0-9-]{4,28}[a-z0-9]/secrets/[A-Za-z0-9_-]{1,255}$"

GcpProvisionerStaticSecretKey = Literal[
    "GDC_ACCESS_SECRET_ID",
    "GDC_VM_IMAGE_GCS_SECRET_ID",
    "GDC_VMSERIES_BOOTSTRAP_XML_TEMPLATE_SECRET_ID",
    "GDC_VMSERIES_IMAGE_GCS_SECRET_ID",
]
GcpNamedResourceRef = Annotated[
    str,
    Field(
        pattern=_GCP_NAMED_RESOURCE_PATTERN,
        description="Full projects/<project>/secrets/<id> Secret Manager resource name without a version.",
    ),
]


class GcpOpenFgaSettings(BaseModel):
    """Operator references for the private released policy service; no payloads."""

    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    store_id: str = Field(default="", pattern=r"^$|^[0-9A-HJKMNP-TV-Z]{26}$")
    model_id: str = Field(default="", pattern=r"^$|^[0-9A-HJKMNP-TV-Z]{26}$")
    runtime_secret_ref: GcpNamedResourceRef | None = None
    admin_secret_ref: GcpNamedResourceRef | None = None
    ca_secret_ref: GcpNamedResourceRef | None = None

    @model_validator(mode="after")
    def validate_enabled_boundary(self) -> GcpOpenFgaSettings:
        if self.enabled and (
            not all((self.runtime_secret_ref, self.admin_secret_ref, self.ca_secret_ref))
            or bool(self.store_id) != bool(self.model_id)
            or self.runtime_secret_ref == self.admin_secret_ref
            or self.ca_secret_ref in {self.runtime_secret_ref, self.admin_secret_ref}
        ):
            raise ValueError(
                "OpenFGA requires distinct runtime, admin and CA references and either both store/model IDs or neither"
            )
        return self


class GcpBackendSettings(BaseModel):
    """Closed operator-intent settings for the ``gcp`` backend bundle (PLAT-2003, #729).

    Only genuine operator intent lives here (projects and region). Terraform variables,
    generated runtime outputs, and provider SDK payloads are not settings — copying them in
    would turn ``settings`` into a second provider schema. ``extra='forbid'`` fails unknown
    GCP settings closed. The shared cross-backend ``range_egress`` policy is deliberately not
    declared; the loader validates it separately for every backend (see the module docstring).
    """

    # The YAML/Terraform contract keeps its established key names through aliases,
    # while internal Python names make the security distinction explicit: these
    # values are public resource identifiers and references, never secret payloads.
    # Serializing by alias preserves the normalized RootConfig surface consumed by
    # downstream deployment tooling.
    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)

    project_id: str = Field(
        pattern=_GCP_PROJECT_ID_PATTERN,
        min_length=6,
        max_length=30,
        description=(
            "GCP project id: 6-30 characters, a lowercase letter followed by lowercase letters, digits, "
            "and hyphens, not ending in a hyphen."
        ),
    )
    range_resource_project_id: str = Field(
        alias="dynamic_secret_project_id",
        pattern=_GCP_PROJECT_ID_PATTERN,
        min_length=6,
        max_length=30,
        description=(
            "Pre-existing deployment-scoped GCP project for provisioner-created range secrets. "
            "It may equal project_id for the supported single-project topology."
        ),
    )
    provisioner_static_resource_refs: dict[GcpProvisionerStaticSecretKey, GcpNamedResourceRef] = Field(
        alias="provisioner_static_secret_refs",
        default_factory=dict,
        description=(
            "Closed map of operator-created GDC input references. The same full references drive "
            "per-secret provisioner IAM and runtime environment publication."
        ),
    )
    region: str = Field(
        pattern=_GCP_REGION_PATTERN,
        description="Lowercase GCP region/location token (letters, digits, and internal hyphens), e.g. 'us-central1'.",
    )
    cloud_sql_iam_auth: bool = Field(
        default=False,
        description=(
            "Use attached workload identities and the official native Cloud SQL proxy for runtime database login."
        ),
    )
    openfga: GcpOpenFgaSettings = Field(default_factory=GcpOpenFgaSettings)

    @model_validator(mode="after")
    def validate_native_policy_datastore(self) -> GcpBackendSettings:
        if self.openfga.enabled and not self.cloud_sql_iam_auth:
            raise ValueError("The GCP OpenFGA deployment requires cloud_sql_iam_auth")
        return self

    shared_service_capacity_profile: CapacityProfileId = Field(
        default="gcp-shared-v1-p10",
        description=(
            "Immutable GCP shared-service event-capacity contract. The selected entry projects the "
            "same profile identity and settings into Terraform, Helm, the public-path gate, and drift checks."
        ),
    )

    range_telemetry: GcpRangeTelemetryPolicy = Field(
        default_factory=GcpRangeTelemetryPolicy,
        description=(
            "Range audit telemetry (#2535): VPC Flow Logs on range subnets, Cloud NAT logging on range "
            "egress, and Vertex AI Data Access audit logs. Every control is on by default; an explicit "
            "change reduces coverage and cost as documented in docs/dev/gcp-range-cell-deploy.md."
        ),
    )
    model_broker: GcpModelBrokerSettings = Field(default_factory=GcpModelBrokerSettings)
    model_broker_runtime: ModelBrokerRuntimeSettings | None = None

    @model_validator(mode="after")
    def validate_capacity_profile(self) -> GcpBackendSettings:
        """Validate the selected shared-service capacity contract."""
        resolve_capacity_profile(self.shared_service_capacity_profile)
        return self

    @classmethod
    def from_root_settings(cls, settings: Mapping[str, object]) -> GcpBackendSettings:
        """Rebuild the backend-owned model from normalized root settings.

        Root settings also contain shared policy blocks owned by their own
        validators. Select only this model's externally aliased contract keys
        before applying the closed backend model again.
        """
        contract_keys = {field.alias or name for name, field in cls.model_fields.items()}
        return cls.model_validate({key: value for key, value in settings.items() if key in contract_keys})
