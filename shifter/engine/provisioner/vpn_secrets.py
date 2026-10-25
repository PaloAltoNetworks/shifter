"""Provider secret-store adapter for participant OpenVPN material (#2030, #2480).

The tenant issuer (CA certificate, CA key and pool tls-crypt key) is created by
the deploy workflow directly in Secret Manager; only the provisioner may read
it. Each range generation stores one participant profile in the dynamic
participant secret location the portal reads at download time.
"""

from __future__ import annotations

import os
from typing import Protocol
from uuid import UUID

from cloud.gcp.base import get_project_id, import_google_module
from config import is_gce_range_cell_backend, resolve_cloud_provider
from gcp_dynamic_secrets import (
    DynamicSecretClass,
    SecretLocations,
    canonical_secret_id,
    delete_all,
    dynamic_secret_project_id,
    read_or_create,
    secret_locations,
)
from vpn_access import VpnSecretOps

_ISSUER_LOCATOR_ENV = "RANGE_OPENVPN_ISSUER_SECRET_ID"


class _GCPExceptions(Protocol):
    """Subset of google.api_core.exceptions used by the adapter."""

    NotFound: type[Exception]
    AlreadyExists: type[Exception]
    InvalidArgument: type[Exception]


class _GCPPayload(Protocol):
    """Secret version payload shape returned by the GCP client."""

    data: bytes


class _GCPAccessResponse(Protocol):
    """access_secret_version response shape returned by the GCP client."""

    payload: _GCPPayload


class _GCPSecretsClient(Protocol):
    """Subset of the GCP Secret Manager client used by the adapter."""

    def access_secret_version(self, *, request: dict[str, object]) -> _GCPAccessResponse: ...

    def get_secret(self, *, request: dict[str, object]) -> object: ...

    def create_secret(self, *, request: dict[str, object]) -> object: ...

    def add_secret_version(self, *, request: dict[str, object]) -> object: ...

    def delete_secret(self, *, request: dict[str, object]) -> object: ...


def _issuer_secret_name() -> str:
    """Return the configured tenant issuer secret resource name."""
    return os.environ.get(_ISSUER_LOCATOR_ENV, "").strip()


class GCPVpnSecretOps(VpnSecretOps):
    """GCP Secret Manager implementation for the GCE range-cell backend."""

    def __init__(
        self,
        client: _GCPSecretsClient | None = None,
        exceptions: _GCPExceptions | None = None,
        *,
        project_id: str | None = None,
        issuer_secret: str | None = None,
    ) -> None:
        self._client = client or import_google_module("google.cloud.secretmanager").SecretManagerServiceClient()
        self._exceptions = exceptions or import_google_module("google.api_core.exceptions")
        self._project_id = project_id or get_project_id()
        if not self._project_id:
            raise RuntimeError("GCP project ID is required for OpenVPN secrets")
        self._storage_project_id = dynamic_secret_project_id()
        self._issuer_secret = issuer_secret if issuer_secret is not None else _issuer_secret_name()

    def _profile_locations(self, range_id: int, generation: UUID) -> SecretLocations:
        suffix = str(generation).replace("-", "")
        return secret_locations(
            platform_project_id=self._project_id,
            dynamic_project_id=self._storage_project_id,
            legacy_secret_id=f"shifter-range-{range_id}-vpn-{suffix}-profile",
            canonical_secret_id=canonical_secret_id(
                credential_class=DynamicSecretClass.VPN_PROFILE, scope=f"range-{range_id}-{suffix}"
            ),
        )

    def read_issuer(self) -> str:
        if not self._issuer_secret.startswith("projects/"):
            raise RuntimeError(f"{_ISSUER_LOCATOR_ENV} must name the tenant OpenVPN issuer secret")
        response = self._client.access_secret_version(request={"name": f"{self._issuer_secret}/versions/latest"})
        return response.payload.data.decode("utf-8")

    def put_profile(self, range_id: int, generation: UUID, payload: str) -> str:
        name, _value = read_or_create(
            self._client, self._exceptions, self._profile_locations(range_id, generation), lambda: payload
        )
        return name

    def delete_profile(self, range_id: int, generation: UUID) -> None:
        delete_all(self._client, self._exceptions, self._profile_locations(range_id, generation))

    def profile_present(self, range_id: int, generation: UUID) -> bool:
        """Return True iff this exact generation's participant profile still resolves."""
        for name in self._profile_locations(range_id, generation).read_refs:
            try:
                self._client.access_secret_version(request={"name": f"{name}/versions/latest"})
                return True
            except self._exceptions.NotFound:
                continue
        return False


def get_vpn_secret_ops() -> VpnSecretOps:
    """Return the selected provider's OpenVPN secret adapter."""
    if resolve_cloud_provider() == "gcp":
        return GCPVpnSecretOps()
    raise RuntimeError("The selected provider does not support the shared OpenVPN pool")


def _env(name: str, default: str = "") -> str:
    """Return a stripped environment value."""
    return os.environ.get(name, default).strip()


def openvpn_access_enabled() -> bool:
    """Return whether this installation has a deployed shared OpenVPN pool.

    The participant control is derived from a persisted binding, so leaving the
    pool unconfigured is fail-closed: no profile is published and the UI offers
    no download. The pool lives in the shared range VPC, so a range minted in its
    own VPC cannot reach it.
    """
    return bool(
        resolve_cloud_provider() == "gcp"
        and is_gce_range_cell_backend()
        and _env("GCP_RANGE_CELL_NETWORK_MODE", "shared-vpc").lower() == "shared-vpc"
        and _env("RANGE_OPENVPN_ENDPOINT")
        and _issuer_secret_name()
        and _env("RANGE_OPENVPN_POOL_CIDRS")
    )


__all__ = ["GCPVpnSecretOps", "get_vpn_secret_ops", "openvpn_access_enabled"]
