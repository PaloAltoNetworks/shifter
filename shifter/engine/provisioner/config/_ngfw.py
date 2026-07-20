"""Provider-neutral NGFW attachment resolution.

Depends on the ``_env`` and ``_crypto`` leaves only.
"""

from dataclasses import dataclass, field
from typing import Any

from ._crypto import resolve_cloud_provider
from ._env import _first_non_empty_string


@dataclass(frozen=True)
class NGFWAttachmentConfig:
    """Provider-neutral attachment and access contract for an NGFW instance."""

    cloud_provider: str
    management_ip: str = ""
    ssh_key_secret_ref: str = ""
    dataplane_ip: str = ""
    route_next_hop_ip: str = ""
    data_attachment_id: str = ""
    attachment_mode: str = ""
    provider_metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_attachable(self) -> bool:
        """Return True when the NGFW has the state needed for range attachment."""
        return bool(
            self.management_ip
            and self.ssh_key_secret_ref
            and (self.data_attachment_id or self.route_next_hop_ip or self.dataplane_ip)
        )


def _get_ngfw_provider_metadata(state: dict[str, Any], cloud_provider: str) -> dict[str, Any]:
    """Return the provider metadata block for an NGFW state payload."""
    provider_metadata = state.get("provider_metadata")
    if not isinstance(provider_metadata, dict):
        return {}

    metadata = provider_metadata.get(cloud_provider) if cloud_provider else None
    if not isinstance(metadata, dict):
        for provider_name in ("gcp", "gdc", "aws"):
            candidate = provider_metadata.get(provider_name)
            if isinstance(candidate, dict):
                metadata = candidate
                break

    return metadata if isinstance(metadata, dict) else {}


def _infer_ngfw_cloud_provider(data_attachment_id: str, route_next_hop_ip: str, env_default: str) -> str:
    """Infer the cloud provider when state omits an explicit ``cloud_provider``.

    GCP data attachments are namespaced KubeVirt references such as
    ``"<namespace>/<vm>:eth1"``; AWS ENI ids (``"eni-..."``) never contain a
    ``"/"`` or ``":"``. Inferring AWS from any ``data_attachment_id`` would
    misclassify a GCP NGFW whose explicit ``cloud_provider`` was dropped.
    """
    if data_attachment_id:
        return "gcp" if ("/" in data_attachment_id or ":" in data_attachment_id) else "aws"
    if route_next_hop_ip:
        return "gcp"
    return env_default


def _resolve_ngfw_attachment_mode(
    payload: dict[str, Any],
    provider_metadata: dict[str, Any],
    cloud_provider: str,
    data_attachment_id: str,
    route_next_hop_ip: str,
) -> str:
    """Resolve the attachment mode, falling back to a provider-appropriate default."""
    default_mode = ""
    if cloud_provider == "gcp" and (route_next_hop_ip or data_attachment_id):
        default_mode = "gdc-static-route"
    elif cloud_provider == "aws" and data_attachment_id:
        default_mode = "aws-route-table-eni"
    return _first_non_empty_string(
        payload.get("attachment_mode"),
        provider_metadata.get("attachment_mode"),
        default_mode,
    )


def resolve_ngfw_attachment_config(state: dict[str, Any] | None) -> NGFWAttachmentConfig:
    """Resolve provider-neutral NGFW attachment details from stored state."""
    payload = state if isinstance(state, dict) else {}
    explicit_provider = _first_non_empty_string(payload.get("cloud_provider")).lower()
    # Only consult the resolver when the persisted state has no provider tag of
    # its own -- a persisted value must win outright and must not force a
    # resolution (and possible fail-closed error) that is not actually needed.
    env_default = "" if explicit_provider else resolve_cloud_provider()
    cloud_provider = explicit_provider or env_default
    provider_metadata = _get_ngfw_provider_metadata(payload, cloud_provider)

    management_ip = _first_non_empty_string(
        payload.get("management_ip"),
        provider_metadata.get("management_ip"),
    )
    ssh_key_secret_ref = _first_non_empty_string(
        payload.get("ssh_key_secret_arn"),
        payload.get("ssh_key_secret_id"),
        provider_metadata.get("ssh_key_secret_arn"),
        provider_metadata.get("ssh_key_secret_id"),
        provider_metadata.get("ssh_secret_ref"),
        provider_metadata.get("ssh_secret_id"),
    )
    dataplane_ip = _first_non_empty_string(
        payload.get("dataplane_ip"),
        provider_metadata.get("dataplane_ip"),
    )
    route_next_hop_ip = _first_non_empty_string(
        payload.get("route_next_hop_ip"),
        provider_metadata.get("route_next_hop_ip"),
        dataplane_ip,
    )
    data_attachment_id = _first_non_empty_string(
        payload.get("data_attachment_id"),
        payload.get("data_eni_id"),
        provider_metadata.get("data_attachment_id"),
        provider_metadata.get("data_eni_id"),
        provider_metadata.get("attachment_id"),
    )
    if not explicit_provider:
        cloud_provider = _infer_ngfw_cloud_provider(data_attachment_id, route_next_hop_ip, env_default)
        provider_metadata = _get_ngfw_provider_metadata(payload, cloud_provider)
    attachment_mode = _resolve_ngfw_attachment_mode(
        payload, provider_metadata, cloud_provider, data_attachment_id, route_next_hop_ip
    )

    return NGFWAttachmentConfig(
        cloud_provider=cloud_provider or "aws",
        management_ip=management_ip,
        ssh_key_secret_ref=ssh_key_secret_ref,
        dataplane_ip=dataplane_ip,
        route_next_hop_ip=route_next_hop_ip,
        data_attachment_id=data_attachment_id,
        attachment_mode=attachment_mode,
        provider_metadata=provider_metadata,
    )


def has_ngfw_attachment_state(state: dict[str, Any] | None) -> bool:
    """Return True when an NGFW state payload can attach to range networks."""
    return resolve_ngfw_attachment_config(state).is_attachable
