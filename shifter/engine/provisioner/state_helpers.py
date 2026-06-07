"""Pure helpers for validating provisioner outputs and shaping persisted state.

Extracted from ``main.py`` (Sonar S104). These functions have no I/O
side effects beyond ``os.environ.get`` lookups: they validate the
shape of Terraform/Pulumi outputs and build the JSON blobs that get
stored into ``engine_subnet.state``, ``engine_instance.state``, and
the legacy ``Range.provisioned_instances`` payload.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def _assert_subnet_output(subnet_name: str, subnet_data: dict[str, Any]) -> None:
    """Reject a Pulumi subnet record missing any required field."""
    for field in ("uuid", "subnet_id", "subnet_cidr"):
        if not subnet_data.get(field):
            raise ValueError(f"Subnet '{subnet_name}' missing '{field}'")


def _assert_instance_output(index: int, inst: dict[str, Any]) -> None:
    """Reject a Pulumi instance record missing any required field."""
    if not inst.get("uuid"):
        raise ValueError(f"Instance[{index}] (role={inst.get('role')}) missing 'uuid'")
    if not inst.get("instance_id"):
        raise ValueError(f"Instance[{index}] missing 'instance_id'")
    if not inst.get("private_ip"):
        raise ValueError(f"Instance[{index}] (role={inst.get('role')}, os={inst.get('os')}) missing 'private_ip'")


def _validate_provisioned_outputs(
    subnets: dict[str, dict[str, Any]],
    instances: list[dict[str, Any]],
    expected_subnet_names: set[str] | None = None,
) -> None:
    """Validate Pulumi outputs have required fields before DB write.

    Args:
        subnets: Dict of subnet_name -> subnet details.
        instances: List of instance dicts.
        expected_subnet_names: Optional set of expected subnet names from spec.

    Raises:
        ValueError: If required fields are missing or empty.
    """
    for subnet_name, subnet_data in subnets.items():
        _assert_subnet_output(subnet_name, subnet_data)
    for i, inst in enumerate(instances):
        _assert_instance_output(i, inst)

    if expected_subnet_names:
        actual_subnets = set(subnets.keys())
        missing = expected_subnet_names - actual_subnets
        if missing:
            raise ValueError(f"Expected subnets not created: {missing}")
        extra = actual_subnets - expected_subnet_names
        if extra:
            logger.warning("Unexpected subnets in output: %s", extra)


def _get_cloud_provider() -> str:
    """Return the active cloud provider for range state persistence."""
    return os.environ.get("CLOUD_PROVIDER", "aws")


def _get_bool_env(name: str) -> bool | None:
    """Parse a boolean env var if set, otherwise return None."""
    raw_value = os.environ.get(name)
    if raw_value is None:
        return None

    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean-like value, got: {raw_value!r}")


def _should_promote_dc_at_runtime(provider: str | None = None) -> bool:
    """Decide whether DC promotion should run during setup."""
    override = _get_bool_env("DC_RUNTIME_PROMOTION")
    if override is not None:
        return override
    return (provider or _get_cloud_provider()) == "gcp"


def _should_run_dc_bootstrap_plan(provider: str | None = None) -> bool:
    """Decide whether DC hostname/SSH bootstrap should run via setup plans."""
    override = _get_bool_env("DC_BOOTSTRAP_VIA_SETUP_PLAN")
    if override is not None:
        return override
    return (provider or _get_cloud_provider()) == "gcp"


def _compact_state_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """Drop empty provider metadata fields so persisted state stays readable."""
    return {key: value for key, value in fields.items() if value not in (None, "", [], {}, ())}


def _get_provider_metadata_prefixes(provider: str) -> list[str]:
    """Return the accepted output prefixes for provider metadata extraction."""
    if provider == "gcp":
        return ["gcp_", "gdc_", "vmruntime_"]
    return [f"{provider}_"]


def _extract_provider_metadata(resource: dict[str, Any], provider: str) -> dict[str, Any]:
    """Collect provider-prefixed keys into a nested metadata block."""
    metadata: dict[str, Any] = {}
    for prefix in _get_provider_metadata_prefixes(provider):
        metadata.update({key.removeprefix(prefix): value for key, value in resource.items() if key.startswith(prefix)})
    return _compact_state_fields(metadata)


def _build_subnet_provider_metadata(subnet_data: dict[str, Any], provider: str) -> dict[str, Any]:
    """Build provider-specific subnet metadata for persisted state."""
    if provider == "aws":
        metadata = {
            "subnet_id": subnet_data.get("subnet_id"),
            "cidr": subnet_data.get("subnet_cidr"),
            "security_group_id": subnet_data.get("security_group_id"),
            "route_table_id": subnet_data.get("route_table_id"),
        }
    else:
        metadata = _extract_provider_metadata(subnet_data, provider)

    return {provider: metadata} if metadata else {}


def _build_instance_provider_metadata(instance_data: dict[str, Any], provider: str) -> dict[str, Any]:
    """Build provider-specific instance metadata for persisted state."""
    if provider == "aws":
        metadata = {
            "instance_id": instance_data.get("instance_id"),
        }
    else:
        metadata = _extract_provider_metadata(instance_data, provider)

    return {provider: metadata} if metadata else {}


def _build_subnet_state(subnet_data: dict[str, Any], provider: str | None = None) -> dict[str, Any]:
    """Build the persisted engine_subnet.state payload."""
    resolved_provider = provider or _get_cloud_provider()
    state = {
        "cloud_provider": resolved_provider,
        "subnet_id": subnet_data.get("subnet_id"),
        "subnet_cidr": subnet_data.get("subnet_cidr"),
        "security_group_id": subnet_data.get("security_group_id"),
        "route_table_id": subnet_data.get("route_table_id"),
        "provider_metadata": _build_subnet_provider_metadata(subnet_data, resolved_provider),
        # Preserve the current AWS field names for existing AWS callers.
        "aws_subnet_id": subnet_data.get("subnet_id") if resolved_provider == "aws" else None,
        "aws_cidr": subnet_data.get("subnet_cidr") if resolved_provider == "aws" else None,
        "aws_security_group_id": subnet_data.get("security_group_id") if resolved_provider == "aws" else None,
        "aws_route_table_id": subnet_data.get("route_table_id") if resolved_provider == "aws" else None,
    }
    return state


def _build_instance_state(instance_data: dict[str, Any], provider: str | None = None) -> dict[str, Any]:
    """Build the persisted engine_instance.state payload for range guests."""
    resolved_provider = provider or _get_cloud_provider()
    state = {
        "asset_type": instance_data.get("asset_type", "vm_runtime_vm"),
        "cloud_provider": resolved_provider,
        "instance_id": instance_data.get("instance_id"),
        "private_ip": instance_data.get("private_ip"),
        "ssh_key_secret_arn": instance_data.get("ssh_key_secret_arn"),
        # Per-instance RDP password secret reference (#762). Carries the
        # provider-native identifier (AWS Secrets Manager ARN or GCP
        # Secret Manager resource path); the password value itself is
        # never persisted in state.
        "rdp_password_secret_arn": instance_data.get("rdp_password_secret_arn"),
        # SSM Parameter Store SecureString name for the same per-
        # instance password (AWS only; GCP carries ``None``). Used by
        # the AWS push path's ``{{ssm-secure:<name>}}`` substitution so
        # the value never lands in SSM Run Command history (#762 codex
        # cycle 3). Mirrors the Secrets Manager copy referenced above;
        # the portal continues to read the value from Secrets Manager
        # via ``shared.cloud`` at access time.
        "rdp_password_ssm_param_name": instance_data.get("rdp_password_ssm_param_name"),
        "ssh_username": instance_data.get("ssh_username"),
        "subnet_name": instance_data.get("subnet_name"),
        "provider_metadata": _build_instance_provider_metadata(instance_data, resolved_provider),
        # Preserve the current AWS field name for existing pause/resume readers.
        "aws_instance_id": instance_data.get("instance_id") if resolved_provider == "aws" else None,
    }
    return state


def _build_provisioned_instance_payload(instance_data: dict[str, Any], provider: str | None = None) -> dict[str, Any]:
    """Build the legacy Range.provisioned_instances entry with provider metadata."""
    resolved_provider = provider or _get_cloud_provider()
    return {
        "uuid": instance_data.get("uuid"),
        "name": instance_data.get("name"),
        "asset_type": instance_data.get("asset_type", "vm_runtime_vm"),
        "role": instance_data.get("role"),
        "os_type": instance_data.get("os"),
        "subnet_name": instance_data.get("subnet_name"),
        "instance_id": instance_data.get("instance_id"),
        "private_ip": instance_data.get("private_ip"),
        "ssh_key_secret_arn": instance_data.get("ssh_key_secret_arn"),
        # Per-instance RDP password secret reference (#762).
        "rdp_password_secret_arn": instance_data.get("rdp_password_secret_arn"),
        # AWS-only mirror in SSM Parameter Store SecureString (#762 cycle 3).
        "rdp_password_ssm_param_name": instance_data.get("rdp_password_ssm_param_name"),
        "ssh_username": instance_data.get("ssh_username"),
        "cloud_provider": resolved_provider,
        "provider_metadata": _build_instance_provider_metadata(instance_data, resolved_provider),
    }
