"""Resolve exact allocation source revisions for the authenticated private broker."""

from shared.model_access import ContractError, validate_catalog
from shared.model_access.catalog_v4 import ModelAccessCatalogV4
from shared.model_access.messages import strict_json
from shared.model_access.source_credentials import validate_source_credential
from shared.model_access.sources import ModelSourceConfiguration

SOURCE_UNAVAILABLE = "source.unavailable"


def model_source_execution(*, token: str, transport_peer: str, logical_alias: str) -> dict[str, object]:
    """Never accept a source ID, cloud path or provider URL from the caller."""
    from engine.models import ModelAllocation, ModelSourceRevision
    from engine.services import authenticate_model_access
    from shared.cloud import get_secrets_store
    from shared.cloud.exceptions import CloudSecretsError

    authority = authenticate_model_access(token=token, transport_peer=transport_peer)
    shard = authority.aliases.get(logical_alias)
    if shard is None:
        raise ContractError(SOURCE_UNAVAILABLE)
    allocation = ModelAllocation.objects.get(pk=authority.allocation_id)
    catalog = validate_catalog(allocation.snapshot["catalog"])
    if not isinstance(catalog, ModelAccessCatalogV4):
        raise ContractError(SOURCE_UNAVAILABLE)
    binding = next((item for item in catalog.source_bindings if item.shard_id == shard.shard_id), None)
    if binding is None or binding.source_id is None:
        raise ContractError(SOURCE_UNAVAILABLE)
    revision = (
        ModelSourceRevision.objects.select_related("source")
        .filter(
            source_id=binding.source_id,
            revision=binding.source_revision,
            state="ready",
            source__enabled=True,
            source__revision=binding.source_revision,
        )
        .first()
    )
    if revision is None:
        raise ContractError(SOURCE_UNAVAILABLE)
    config = ModelSourceConfiguration.model_validate(revision.configuration)
    target = config.target(binding.source_id, binding.source_revision).model_copy(update={"shard_id": shard.shard_id})
    target.bind(shard)
    credential = ""
    if target.authentication == "stored-credential":
        try:
            credential = get_secrets_store().get_secret(revision.credential_reference)
            validate_source_credential(config, strict_json(credential.encode(), limit=32768))
        except (CloudSecretsError, ValueError):
            raise ContractError("source.credential_unavailable") from None
    # The cloud read holds no database lock. Reauthorize after it so a revoke
    # committed during I/O cannot publish a fresh credential projection.
    current = authenticate_model_access(token=token, transport_peer=transport_peer)
    if current != authority:
        raise ContractError(SOURCE_UNAVAILABLE)
    return {
        "target": target.model_dump(mode="json"),
        "credential": credential,
        "upstream_provider": config.upstream_provider,
    }
