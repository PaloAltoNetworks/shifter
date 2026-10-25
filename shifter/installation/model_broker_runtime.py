"""Non-secret broker execution configuration, separate from infrastructure state."""

import base64
import json
import ssl
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
from shared.model_access import load_catalog_json
from shared.model_access.catalog import ModelAccessCatalog
from shared.model_access.core_models import BillingComponent, Identifier
from shared.model_access.provider_runtime import ProviderInventory

from .gcp_model_broker import ResourceName


class ModelBrokerRuntimeSettings(BaseModel):
    """Mounted provider bindings and versioned Kubernetes Secret references only."""

    model_config = ConfigDict(extra="forbid")
    provider_inventory: ProviderInventory
    fingerprint_secret_name: ResourceName
    fingerprint_key_version: Identifier
    fingerprint_previous_secret_name: ResourceName = ""
    guest_trust_ca_pem: str = Field(default="", max_length=16384)

    @field_validator("guest_trust_ca_pem")
    @classmethod
    def validate_guest_ca(cls, value: str) -> str:
        """Admit only bounded public certificate bundles with valid X.509 data."""
        if value:
            _validate_certificate_envelopes(value)
            try:
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                context.minimum_version = ssl.TLSVersion.TLSv1_2
                context.load_verify_locations(cadata=value)
            except (ValueError, ssl.SSLError):
                raise ValueError("guest trust requires a PEM CA certificate") from None
        return value


def _validate_certificate_envelopes(value: str) -> None:
    """Scan PEM boundaries once, without ambiguous whitespace backtracking."""
    parts = value.split("-----END CERTIFICATE-----")
    if len(parts) < 2 or parts[-1].strip():
        raise ValueError("guest trust accepts only public PEM certificates")
    for part in parts[:-1]:
        certificate = part.strip()
        header = "-----BEGIN CERTIFICATE-----"
        if not certificate.startswith(header):
            raise ValueError("guest trust accepts only public PEM certificates")
        try:
            encoded = "".join(certificate[len(header) :].split())
            if not base64.b64decode(encoded, validate=True):
                raise ValueError
        except ValueError:
            raise ValueError("guest trust requires a PEM CA certificate") from None


def project_broker_runtime(
    value: object,
    *,
    catalog_json: str,
    provider: str,
    model_identities: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Reject incomplete execution bindings before Helm or cloud deployment."""
    if provider not in {"gcp", "aws"}:
        raise ValueError("unsupported broker provider")
    settings = ModelBrokerRuntimeSettings.model_validate(value)
    if not settings.fingerprint_secret_name:
        raise ValueError("model broker requires a versioned fingerprint Secret")
    catalog = load_catalog_json(catalog_json)
    if catalog.contract_version != "model-access-policy/v3" or not catalog.enabled:
        raise ValueError("active model broker requires an enabled v3 accounting catalog")
    _validate_execution_inventory(settings, catalog, provider, model_identities)
    result = settings.model_dump(mode="json", exclude={"provider_inventory", "guest_trust_ca_pem"})
    result["providers_json"] = json.dumps(
        settings.provider_inventory.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    )
    return result


def _validate_execution_inventory(
    settings: ModelBrokerRuntimeSettings,
    catalog: ModelAccessCatalog,
    provider: str,
    model_identities: Mapping[str, str] | None,
) -> None:
    """Bind every enabled shard to its approved provider identity and price schedule."""
    shards = {shard.shard_id: shard for shard in catalog.shards if shard.enabled}
    targets = {target.shard_id: target for target in settings.provider_inventory.targets}
    if set(shards) != set(targets):
        raise ValueError("provider inventory must match the enabled catalog shards")
    for name, target in targets.items():
        target.bind(shards[name])
        if target.provider != ("vertex-v1" if provider == "gcp" else "bedrock-v1"):
            raise ValueError("provider inventory requires a supported workload identity on this deployment")
        if provider == "gcp" and (model_identities or {}).get(target.project) != target.principal:
            raise ValueError("provider target differs from the applied invocation identity")
    _validate_messages_pricing(catalog)


def _validate_messages_pricing(catalog: ModelAccessCatalog) -> None:
    """Require complete token pricing and non-billable count-token requests."""
    schedules = {schedule.price_schedule_id: schedule for schedule in catalog.price_schedules}
    for alias in catalog.aliases:
        prices = {price.component: price.price_micro_units for price in schedules[alias.price_schedule_id].prices}
        if (
            not {BillingComponent.INPUT_TOKENS, BillingComponent.OUTPUT_TOKENS, BillingComponent.REQUEST}.issubset(
                prices
            )
            or prices[BillingComponent.REQUEST] != 0
        ):
            raise ValueError("Messages delivery needs input/output prices and free token-count request pricing")


def project_enrollment_env(
    runtime_settings: object,
    *,
    hostname: str,
    guest_vip: str = "",
    guest_cidrs: Sequence[str] = (),
) -> dict[str, str]:
    """Public TLS trust and fixed private service coordinates; no capabilities."""
    ca = ModelBrokerRuntimeSettings.model_validate(runtime_settings).guest_trust_ca_pem
    if not ca:
        return {}
    return {
        "MODEL_BROKER_GUEST_URL": f"https://{hostname}",
        **({"MODEL_BROKER_GUEST_VIP": guest_vip} if guest_vip else {}),
        **({"MODEL_BROKER_GUEST_CIDRS": ",".join(guest_cidrs)} if guest_cidrs else {}),
        "MODEL_ENROLLMENT_CONTROL_URL": "https://model-access-control.shifter-platform.svc:8444",
        "MODEL_ENROLLMENT_CA_PEM_B64": base64.b64encode(ca.encode("ascii")).decode("ascii"),
    }
