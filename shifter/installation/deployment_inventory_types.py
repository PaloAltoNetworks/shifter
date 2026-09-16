"""Version-one provider-neutral deployment inventory and GCP bootstrap inputs."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .schema import RootConfig

Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{0,38}[a-z0-9]$")]
Repository = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+$", max_length=200)]
Revision = Annotated[str, Field(pattern=r"^[a-f0-9]{40}$")]
Environment = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$")]
Purpose = Literal["build", "validate", "promote", "release_scan", "deploy", "destroy"]
Stack = Literal["identity", "runner", "platform"]
Bucket = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$")]

# These are product capabilities, not deployment IDs. Inventory selects a
# supported entry point; it cannot authorize arbitrary workflow code.
PURPOSE_WORKFLOWS = {
    "build": frozenset({"packer.yml", "packer-gcp.yml"}),
    "validate": frozenset({"packer.yml", "packer-gcp-validate.yml"}),
    "promote": frozenset({"packer-promote.yml", "packer-gcp-promote.yml"}),
    "release_scan": frozenset({"deploy.yml", "packer-gcp-release-scan.yml"}),
    "deploy": frozenset({"deploy.yml"}),
    "destroy": frozenset({"aws-env-destroy.yml", "gcp-dev-destroy.yml", "destroy.yml"}),
}


class ClosedRecord(BaseModel):
    """Immutable inventory object that rejects unknown fields."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class ProductRevision(ClosedRecord):
    """Canonical product repository pinned to an immutable commit."""

    repository: Literal["Brad-Edwards/shifter"]
    revision: Revision


class ExecutionContext(ClosedRecord):
    """One exact Environment, branch and supported workflow tuple."""

    environment: Environment
    ref: str = Field(pattern=r"^refs/heads/[A-Za-z0-9][A-Za-z0-9_/-]{0,150}$")
    workflow: str = Field(pattern=r"^[a-z][a-z0-9_-]*\.yml$")
    reusable_workflow: str | None = Field(
        default=None,
        pattern=r"^Brad-Edwards/shifter/\.github/workflows/_[a-z0-9_-]+\.yml@[a-f0-9]{40}$",
    )


class ExecutionRepository(ClosedRecord):
    """Private execution authority identified by immutable GitHub IDs."""

    repository: Repository
    repository_id: str = Field(pattern=r"^[1-9][0-9]{0,19}$")
    owner_id: str = Field(pattern=r"^[1-9][0-9]{0,19}$")
    subject_format: Literal["default", "immutable"]
    purposes: dict[Purpose, list[ExecutionContext]] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def validate_purposes(self) -> ExecutionRepository:
        owners: dict[str, str] = {}
        count = 0
        for purpose, contexts in self.purposes.items():
            if not contexts or len(contexts) > 8:
                raise ValueError("purpose must have one to eight execution contexts")
            count += len(contexts)
            self._validate_contexts(purpose, contexts, owners)
        if count > 12:
            raise ValueError("too many trust tuples for the bounded provider condition")
        return self

    @staticmethod
    def _validate_contexts(purpose: Purpose, contexts: list[ExecutionContext], owners: dict[str, str]) -> None:
        """Enforce supported entry points, disjoint subjects and unique tuples."""
        seen: set[tuple[str, str, str, str | None]] = set()
        for context in contexts:
            if context.workflow not in PURPOSE_WORKFLOWS[purpose]:
                raise ValueError("workflow is not a supported entry point for this purpose")
            # GitHub Environment identity is case insensitive.
            environment = context.environment.lower()
            if environment in owners and owners[environment] != purpose:
                raise ValueError("purpose subjects must be disjoint")
            owners[environment] = purpose
            key = (environment, context.ref, context.workflow, context.reusable_workflow)
            if key in seen:
                raise ValueError("duplicate execution context")
            seen.add(key)


class StateReference(ClosedRecord):
    """Dedicated remote state bucket and prefix for one stack."""

    bucket: Bucket
    prefix: str = Field(pattern=r"^[a-z0-9][a-z0-9_/-]{0,180}[a-z0-9]$")


class SecretReference(ClosedRecord):
    """Scoped secret locator without a secret value."""

    store: Literal["gcp-secret-manager", "aws-secrets-manager", "github-environment"]
    resource: str = Field(min_length=1, max_length=1024)
    repository: Repository | None = None
    environment: Environment | None = None

    @model_validator(mode="after")
    def validate_reference(self) -> SecretReference:
        import re

        patterns = {
            "gcp-secret-manager": (
                r"projects/[a-z][a-z0-9-]{4,28}[a-z0-9]/secrets/[A-Za-z0-9_-]{1,255}/versions/[1-9][0-9]*"
            ),
            "aws-secrets-manager": r"arn:aws:secretsmanager:[a-z0-9-]+:[0-9]{12}:secret:[A-Za-z0-9/_+=.@-]+",
            "github-environment": r"[A-Z][A-Z0-9_]{0,99}",
        }
        if re.fullmatch(patterns[self.store], self.resource) is None:
            raise ValueError("invalid scoped secret reference")
        scoped = self.repository is not None and self.environment is not None
        if self.store == "github-environment":
            if not scoped:
                raise ValueError("execution secret requires exact repository and environment")
        elif self.repository is not None or self.environment is not None:
            raise ValueError("cloud secret must not contain execution scope")
        return self


class GcpIdentityInputs(ClosedRecord):
    """Resource names and bounded capabilities within the deployment project."""

    name_prefix: str = Field(pattern=r"^[a-z][a-z0-9-]{2,21}[a-z0-9]$")
    evidence_bucket: Bucket
    runner_zone: str = Field(pattern=r"^[a-z]+-[a-z]+[0-9]-[a-z]$")
    build_read_bucket_names: list[Bucket] = Field(default_factory=list, max_length=20)
    platform_external_bucket_names: list[Bucket] = Field(default_factory=list, max_length=20)
    promotion_reader_service_account_email: str = Field(
        default="",
        pattern=r"^(?:|[a-z][a-z0-9-]{4,28}[a-z0-9]@[a-z][a-z0-9-]{4,28}[a-z0-9]\.iam\.gserviceaccount\.com)$",
    )

    @model_validator(mode="after")
    def validate_derived_names(self) -> GcpIdentityInputs:
        if len(self.name_prefix.replace("-", "") + "-validate") > 30:
            raise ValueError("derived service account ID exceeds provider limit")
        if self.evidence_bucket in self.platform_external_bucket_names:
            raise ValueError("platform cannot administer private evidence")
        return self


class DeploymentRecord(ClosedRecord):
    """Versioned deployment, execution, state and secret-reference contract."""

    version: Literal[1]
    installation: RootConfig
    product: ProductRevision
    execution: ExecutionRepository
    state: dict[Stack, StateReference]
    secrets: dict[Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]{0,99}$")], SecretReference]
    gcp: GcpIdentityInputs | None = None

    @model_validator(mode="after")
    def validate_boundaries(self) -> DeploymentRecord:
        if set(self.state) != {"identity", "runner", "platform"}:
            raise ValueError("identity, runner and platform state are required")
        if len({state.bucket for state in self.state.values()}) != 3:
            raise ValueError("foundation, runner and platform state require distinct bucket authority")
        if self.installation.backend == "gcp":
            if self.gcp is None:
                raise ValueError("GCP identity inputs are required")
            if not self.gcp.runner_zone.startswith(str(self.installation.settings["region"]) + "-"):
                raise ValueError("runner zone must belong to the configured region")
            protected = {state.bucket for state in self.state.values()} | {self.gcp.evidence_bucket}
            if protected.intersection(self.gcp.build_read_bucket_names + self.gcp.platform_external_bucket_names):
                raise ValueError("external capability buckets cannot include owned state or evidence")
            if self.gcp.evidence_bucket in {s.bucket for s in self.state.values()}:
                raise ValueError("release evidence and state must have separate ownership")
        elif self.installation.backend != "aws" or self.gcp is not None:
            raise ValueError("inventory supports AWS or GCP with matching cloud inputs")
        return self

    @model_validator(mode="after")
    def validate_consumers(self) -> DeploymentRecord:
        if set(self.installation.secrets.values()) != set(self.secrets):
            raise ValueError("installation secrets must reference exactly the common secret bindings")
        for contexts in self.execution.purposes.values():
            for context in contexts:
                if context.reusable_workflow and not context.reusable_workflow.endswith("@" + self.product.revision):
                    raise ValueError("reusable workflow must use the reviewed product revision")
        for secret in self.secrets.values():
            if secret.store == "github-environment" and secret.repository != self.execution.repository:
                raise ValueError("execution secret repository must match execution authority")
        return self
