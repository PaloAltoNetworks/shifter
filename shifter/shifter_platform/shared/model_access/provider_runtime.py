"""Deployment-owned provider targets; participants select only logical aliases."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from shared.model_access import ContractError
from shared.model_access.core_models import ClosedModel, Identifier, ModelShard

ProviderKind = Literal["vertex-v1", "bedrock-v1", "anthropic-v1", "openai-v1", "openrouter-v1"]
AuthenticationKind = Literal["workload-identity", "stored-credential"]


class ProviderTarget(ClosedModel):
    """Explicit approved transport, principal and conservative model context bound."""

    shard_id: Identifier
    provider: ProviderKind
    authentication: AuthenticationKind = Field(
        default="workload-identity", exclude_if=lambda value: value == "workload-identity"
    )
    region: Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{1,62}[a-z0-9]$")]
    model: Annotated[str, Field(pattern=r"^[a-zA-Z0-9@.:/-]{1,256}$")]
    credential_reference: Annotated[str, Field(max_length=256)]
    principal: Annotated[str, Field(max_length=256)]
    project: Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$|^$")] = ""
    # Counts may have a different service geography; it must be explicitly
    # approved in deployment intent, never inferred from the compute region.
    count_region: Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{0,62}[a-z0-9]$|^$")] = ""
    context_window_tokens: Annotated[int, Field(strict=True, ge=1, le=2_000_000)]

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        import re

        if self.authentication == "stored-credential" and not re.fullmatch(
            r"source:[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}:[1-9]\d{0,9}",
            self.credential_reference,
            flags=re.ASCII,
        ):
            raise ValueError("stored credentials require an owned source revision")
        if self.provider in {"anthropic-v1", "openai-v1", "openrouter-v1"}:
            self._validate_direct_identity()
        elif self.provider == "vertex-v1":
            self._validate_vertex_identity()
        elif (
            self.project
            or self.count_region
            or not re.fullmatch(r"arn:aws:iam::\d{12}:role/[a-zA-Z0-9/+=,.@_-]+", self.principal, flags=re.ASCII)
        ):
            raise ValueError("Bedrock requires an approved invocation role")
        return self

    def _validate_direct_identity(self) -> None:
        """Direct provider keys carry no cloud identity or caller-selected geography."""
        if self.region != "provider-managed":
            raise ValueError("direct provider origins require provider-managed geography")
        if self.authentication != "stored-credential" or self.project or self.principal or self.count_region:
            raise ValueError("direct providers require a stored credential without a cloud principal")

    def _validate_vertex_identity(self) -> None:
        """Validate the approved project, service account, and publisher model."""
        import re

        if not self.project or not self.count_region or self.count_region == "global":
            raise ValueError("Vertex requires approved project and count geography")
        if not re.fullmatch(
            r"[a-z][a-z0-9-]{4,28}[a-z0-9]@" + re.escape(self.project) + r"\.iam\.gserviceaccount\.com",
            self.principal,
        ):
            raise ValueError("Vertex principal must belong to the approved project")
        if not re.fullmatch(r"publishers/anthropic/models/[a-z0-9@-]+", self.model):
            raise ValueError("Vertex requires a pinned Anthropic publisher model")

    def bind(self, shard: ModelShard) -> Self:
        if (
            shard.shard_id != self.shard_id
            or shard.provider_adapter_id != self.provider
            or shard.region != self.region
            or shard.provider_model != self.model
            or shard.credential_ref.reference != self.credential_reference
            or shard.protocol != "anthropic-messages/2023-06-01"
        ):
            raise ContractError("provider.target_mismatch")
        return self


class ProviderInventory(ClosedModel):
    """Closed mounted non-secret configuration independent of guest packages."""

    contract_version: Literal["model-broker-providers/v1"]
    targets: Annotated[list[ProviderTarget], Field(min_length=1, max_length=128)]

    @model_validator(mode="after")
    def unique_targets(self) -> Self:
        if len({target.shard_id for target in self.targets}) != len(self.targets):
            raise ValueError("duplicate provider target")
        return self


class SourceExecutionProjection(ClosedModel):
    """Ephemeral private-control reply; never a participant-facing contract."""

    target: ProviderTarget
    credential: Annotated[str, Field(max_length=32768, repr=False)]
    upstream_provider: Annotated[str, Field(max_length=128)] = ""

    @model_validator(mode="after")
    def validate_credential(self) -> Self:
        from shared.model_access.messages import strict_json
        from shared.model_access.source_credentials import parse_source_credential

        if self.target.authentication == "stored-credential":
            parse_source_credential(self.target.provider, strict_json(self.credential.encode(), limit=32768))
        elif self.credential:
            raise ValueError("workload identity does not accept stored credentials")
        if bool(self.upstream_provider) != (self.target.provider == "openrouter-v1"):
            raise ValueError("routing provider must be explicit only for OpenRouter")
        return self
