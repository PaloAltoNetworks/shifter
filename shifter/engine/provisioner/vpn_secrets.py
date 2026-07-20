"""Provider secret-store adapters for OpenVPN generation material."""

from __future__ import annotations

import os
from collections.abc import Callable
from contextlib import suppress
from typing import Protocol
from uuid import UUID

from botocore.exceptions import ClientError

from cloud.gcp.base import get_project_id, import_google_module
from config import is_gce_range_cell_backend, resolve_cloud_provider
from gcp_vpn_identity import (
    gcp_vpn_gateway_service_account_email,
    gcp_vpn_gateway_service_account_id,
)
from vpn_access import VpnSecretOps


class _AWSSecretsClient(Protocol):
    """Subset of the boto3 Secrets Manager client used by the adapter."""

    def get_secret_value(self, **kwargs: object) -> dict[str, object]: ...

    def create_secret(self, **kwargs: object) -> dict[str, object]: ...

    def put_secret_value(self, **kwargs: object) -> dict[str, object]: ...

    def describe_secret(self, **kwargs: object) -> dict[str, object]: ...

    def delete_secret(self, **kwargs: object) -> dict[str, object]: ...


def _aws_secret_names(range_id: int, generation: UUID) -> dict[str, str]:
    """Return the deterministic AWS secret names for one range generation."""
    environment = os.environ.get("ENVIRONMENT", "dev").strip() or "dev"
    base = f"shifter/{environment}/range/{range_id}/vpn-{generation}"
    return {
        "issuer": f"shifter/{environment}/vpn-issuer/range-{range_id}/{generation}",
        "server": f"{base}-server",
        "profile": f"{base}-profile",
    }


class AWSVpnSecretOps(VpnSecretOps):
    """AWS Secrets Manager implementation with deterministic generation names."""

    def __init__(self, client: _AWSSecretsClient | None = None) -> None:
        if client is None:
            import boto3

            client = boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION"))
        self._client = client

    def _create(self, name: str, payload: str, range_id: int) -> str:
        kwargs: dict[str, object] = {
            "Name": name,
            "SecretString": payload,
            "Tags": [
                {"Key": "shifter:system", "Value": "shifter"},
                {"Key": "shifter:range_id", "Value": str(range_id)},
                {"Key": "shifter:credential", "Value": "openvpn"},
            ],
        }
        kms_key = os.environ.get("SECRETS_KMS_KEY_ARN", "").strip()
        if kms_key:
            kwargs["KmsKeyId"] = kms_key
        try:
            response = self._client.create_secret(**kwargs)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "ResourceExistsException":
                raise
            response = self._client.describe_secret(SecretId=name)
        return str(response.get("ARN") or name)

    def _put(self, name: str, payload: str, range_id: int) -> str:
        try:
            current = self._client.get_secret_value(SecretId=name)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "ResourceNotFoundException":
                raise
            return self._create(name, payload, range_id)
        if current.get("SecretString") != payload:
            self._client.put_secret_value(SecretId=name, SecretString=payload)
        described = self._client.describe_secret(SecretId=name)
        return str(described.get("ARN") or name)

    def read_or_create_issuer(self, range_id: int, generation: UUID, payload_factory: Callable[[], str]) -> str:
        name = _aws_secret_names(range_id, generation)["issuer"]
        try:
            response = self._client.get_secret_value(SecretId=name)
            value = response.get("SecretString")
            if not isinstance(value, str):
                raise ValueError("OpenVPN issuer secret must contain a text payload")
            return value
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "ResourceNotFoundException":
                raise
        payload = payload_factory()
        self._create(name, payload, range_id)
        response = self._client.get_secret_value(SecretId=name)
        value = response.get("SecretString")
        if not isinstance(value, str):
            raise ValueError("OpenVPN issuer secret was not readable after creation")
        return value

    def put_server(self, range_id: int, generation: UUID, payload: str) -> None:
        self._put(_aws_secret_names(range_id, generation)["server"], payload, range_id)

    def put_profile(self, range_id: int, generation: UUID, payload: str) -> str:
        return self._put(_aws_secret_names(range_id, generation)["profile"], payload, range_id)

    def _delete(self, name: str) -> None:
        try:
            self._client.delete_secret(SecretId=name, ForceDeleteWithoutRecovery=True)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "ResourceNotFoundException":
                raise

    def delete_generation(self, range_id: int, generation: UUID, *, delete_identity: bool = True) -> None:
        for name in _aws_secret_names(range_id, generation).values():
            self._delete(name)


class _GCPExceptions(Protocol):
    """Subset of google.api_core.exceptions used by the adapter."""

    NotFound: type[Exception]
    AlreadyExists: type[Exception]


class _GCPSecretsClient(Protocol):
    """Subset of the GCP Secret Manager client used by the adapter."""

    def access_secret_version(self, *, request: dict[str, object]) -> _GCPAccessResponse: ...

    def create_secret(self, *, request: dict[str, object]) -> object: ...

    def add_secret_version(self, *, request: dict[str, object]) -> object: ...

    def set_iam_policy(self, *, request: dict[str, object]) -> object: ...

    def delete_secret(self, *, request: dict[str, object]) -> object: ...


class _GCPIamClient(Protocol):
    """Subset of the GCP IAM admin client used by the adapter."""

    def create_service_account(self, *, request: dict[str, object]) -> object: ...

    def delete_service_account(self, *, request: dict[str, object]) -> object: ...


class _GCPPayload(Protocol):
    """Secret version payload shape returned by the GCP client."""

    data: bytes


class _GCPAccessResponse(Protocol):
    """access_secret_version response shape returned by the GCP client."""

    payload: _GCPPayload


def _gcp_secret_ids(range_id: int, generation: UUID) -> dict[str, str]:
    """Return the deterministic GCP secret ids for one range generation."""
    suffix = str(generation).replace("-", "")
    return {kind: f"shifter-range-{range_id}-vpn-{suffix}-{kind}" for kind in ("issuer", "server", "profile")}


class GCPVpnSecretOps(VpnSecretOps):
    """GCP Secret Manager implementation for a GCE range cell."""

    def __init__(
        self,
        client: _GCPSecretsClient | None = None,
        iam_client: _GCPIamClient | None = None,
        exceptions: _GCPExceptions | None = None,
        *,
        project_id: str | None = None,
    ) -> None:
        self._client = client or import_google_module("google.cloud.secretmanager").SecretManagerServiceClient()
        self._iam_client = iam_client or import_google_module("google.cloud.iam_admin_v1").IAMClient()
        self._exceptions = exceptions or import_google_module("google.api_core.exceptions")
        self._project_id = project_id or get_project_id()
        if not self._project_id:
            raise RuntimeError("GCP project ID is required for OpenVPN secrets")

    def _gateway_email(self, range_id: int, generation: UUID) -> str:
        return gcp_vpn_gateway_service_account_email(self._project_id, range_id, generation)

    def _ensure_gateway_identity(self, range_id: int, generation: UUID) -> str:
        account_id = gcp_vpn_gateway_service_account_id(range_id, generation)
        with suppress(self._exceptions.AlreadyExists):
            self._iam_client.create_service_account(
                request={
                    "name": f"projects/{self._project_id}",
                    "account_id": account_id,
                    "service_account": {
                        "display_name": f"Shifter range {range_id} OpenVPN gateway",
                    },
                }
            )
        return self._gateway_email(range_id, generation)

    def _name(self, secret_id: str) -> str:
        return f"projects/{self._project_id}/secrets/{secret_id}"

    def _read(self, name: str) -> str:
        response = self._client.access_secret_version(request={"name": f"{name}/versions/latest"})
        return response.payload.data.decode("utf-8")

    def _create_or_update(self, secret_id: str, payload: str, *, gateway_email: str = "") -> str:
        name = self._name(secret_id)
        try:
            current = self._read(name)
        except self._exceptions.NotFound:
            with suppress(self._exceptions.AlreadyExists):
                self._client.create_secret(
                    request={
                        "parent": f"projects/{self._project_id}",
                        "secret_id": secret_id,
                        "secret": {"replication": {"automatic": {}}},
                    }
                )
            current = ""
        if current != payload:
            self._client.add_secret_version(request={"parent": name, "payload": {"data": payload.encode("utf-8")}})
        if gateway_email:
            self._client.set_iam_policy(
                request={
                    "resource": name,
                    "policy": {
                        "bindings": [
                            {
                                "role": "roles/secretmanager.secretAccessor",
                                "members": [f"serviceAccount:{gateway_email}"],
                            }
                        ]
                    },
                }
            )
        return name

    def read_or_create_issuer(self, range_id: int, generation: UUID, payload_factory: Callable[[], str]) -> str:
        secret_id = _gcp_secret_ids(range_id, generation)["issuer"]
        name = self._name(secret_id)
        try:
            return self._read(name)
        except self._exceptions.NotFound:
            payload = payload_factory()
            self._create_or_update(secret_id, payload)
            return self._read(name)

    def put_server(self, range_id: int, generation: UUID, payload: str) -> None:
        gateway_email = self._ensure_gateway_identity(range_id, generation)
        self._create_or_update(
            _gcp_secret_ids(range_id, generation)["server"],
            payload,
            gateway_email=gateway_email,
        )

    def put_profile(self, range_id: int, generation: UUID, payload: str) -> str:
        return self._create_or_update(_gcp_secret_ids(range_id, generation)["profile"], payload)

    def delete_generation(self, range_id: int, generation: UUID, *, delete_identity: bool = True) -> None:
        for secret_id in _gcp_secret_ids(range_id, generation).values():
            with suppress(self._exceptions.NotFound):
                self._client.delete_secret(request={"name": self._name(secret_id)})
        if not delete_identity:
            return
        gateway_email = self._gateway_email(range_id, generation)
        with suppress(self._exceptions.NotFound):
            self._iam_client.delete_service_account(
                request={"name": f"projects/{self._project_id}/serviceAccounts/{gateway_email}"}
            )


def get_vpn_secret_ops() -> VpnSecretOps:
    """Return the selected provider's OpenVPN secret adapter."""
    provider = resolve_cloud_provider()
    if provider == "aws":
        return AWSVpnSecretOps()
    if provider == "gcp":
        return GCPVpnSecretOps()
    raise RuntimeError("The selected provider does not support OpenVPN secrets")


def _env(name: str, default: str = "") -> str:
    """Return a stripped environment value."""
    return os.environ.get(name, default).strip()


def _portal_cidrs_configured() -> bool:
    """Return whether portal-side network CIDRs are declared."""
    return bool(_env("PORTAL_NETWORK_CIDRS") or _env("PORTAL_VPC_CIDR"))


def _aws_openvpn_prerequisites() -> bool:
    """Return whether the AWS substrate for the VPN gateway is configured."""
    return bool(
        _env("RANGE_VPN_EDGE_SUBNET_ID")
        and _env("RANGE_VPN_GATEWAY_PERMISSIONS_BOUNDARY_ARN")
        and _env("RANGE_VPN_PROVIDER_ENDPOINT_SECURITY_GROUP_ID")
        and _portal_cidrs_configured()
    )


def _gcp_openvpn_prerequisites() -> bool:
    """Return whether the GCE range-cell substrate for the VPN gateway is configured."""
    scopes = {
        value.strip()
        for value in os.environ.get(
            "GCP_RANGE_HOST_SERVICE_ACCOUNT_SCOPES",
            "https://www.googleapis.com/auth/cloud-platform",
        ).split(",")
        if value.strip()
    }
    return bool(
        is_gce_range_cell_backend()
        and _env("GCP_RANGE_CELL_NETWORK_MODE", "shared-vpc").lower() == "shared-vpc"
        and _env("GCP_RANGE_PRIVATE_GOOGLE_ACCESS").lower() in {"1", "true", "yes", "on"}
        and _env("GCP_RANGE_HOST_SERVICE_ACCOUNT_EMAIL")
        and _env("GCP_RANGE_LINUX_IMAGE")
        and _portal_cidrs_configured()
        and "https://www.googleapis.com/auth/cloud-platform" in scopes
    )


def openvpn_access_enabled() -> bool:
    """Return whether this installation has the selected adapter prerequisites.

    The participant control is derived from a persisted binding, so leaving the
    adapter disabled is fail-closed: no profile is published and the UI does not
    offer a download. This also lets existing installations roll the provider
    substrate out before enabling it through their already-validated runtime
    configuration.
    """
    provider = resolve_cloud_provider()
    if provider == "aws":
        return _aws_openvpn_prerequisites()
    if provider == "gcp":
        return _gcp_openvpn_prerequisites()
    return False


__all__ = ["AWSVpnSecretOps", "GCPVpnSecretOps", "get_vpn_secret_ops", "openvpn_access_enabled"]
