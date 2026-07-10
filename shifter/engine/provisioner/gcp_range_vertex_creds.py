"""Per-range Vertex AI agent credential lifecycle for GCE range cells.

The participant-facing agent container (for example the Polaris ``a14-kali``
container) needs a Vertex AI credential. It must NOT reach the range-host
service account through the metadata server: a CTF participant has shell in the
container and could mint the host SA token and exfiltrate it. Instead the
range-cell backend mints a *per-range* key on a pre-provisioned, Vertex-only
service account (``GCERangeCellConfig.vertex_service_account_email``), stores it
by reference in Secret Manager, and the range bootstrap injects it into the
container host-side while blocking the container from the metadata server.

The credential is created with the range and destroyed with it, so a leaked key
is scoped to Vertex only and revocable per range. The Vertex-only SA and its
``roles/aiplatform.user`` binding are provisioned once out-of-band (Terraform),
which avoids per-range IAM-policy races and service-account quota pressure; the
dynamic, per-range part is the key.
"""

from __future__ import annotations

import json
import logging
from contextlib import suppress
from typing import Protocol

from cloud.gcp.base import get_project_id, import_google_module
from log_redact import safe_log_fingerprint

logger = logging.getLogger(__name__)

_IAM_ADMIN_MODULE = "google.cloud.iam_admin_v1"
_SECRETMANAGER_MODULE = "google.cloud.secretmanager"
_GOOGLE_EXCEPTIONS_MODULE = "google.api_core.exceptions"


class _ServiceAccountKey(Protocol):
    """Service-account key response subset used by the Vertex credential path."""

    name: str
    private_key_data: bytes


class _SecretPayload(Protocol):
    """Secret Manager payload subset."""

    data: bytes


class _SecretVersion(Protocol):
    """Secret Manager version response subset."""

    payload: _SecretPayload


class _IamClient(Protocol):
    """IAM Admin client subset used to mint and revoke range Vertex keys."""

    def create_service_account_key(self, *, request: dict[str, object]) -> _ServiceAccountKey:
        """Create a service-account key."""

    def delete_service_account_key(self, *, request: dict[str, object]) -> object:
        """Delete a service-account key."""


class _SecretClient(Protocol):
    """Secret Manager client subset used to store the range Vertex key."""

    def access_secret_version(self, *, request: dict[str, object]) -> _SecretVersion:
        """Return the latest secret version."""

    def create_secret(self, *, request: dict[str, object]) -> object:
        """Create a Secret Manager secret."""

    def add_secret_version(self, *, request: dict[str, object]) -> object:
        """Add a Secret Manager secret version."""

    def set_iam_policy(self, *, request: dict[str, object]) -> object:
        """Set the IAM policy on a secret (scoped per-range accessor grant)."""

    def delete_secret(self, *, request: dict[str, object]) -> object:
        """Delete a Secret Manager secret."""


class _GoogleExceptions(Protocol):
    """Google exception module subset used by the Vertex credential path."""

    NotFound: type[Exception]
    AlreadyExists: type[Exception]


def _vertex_secret_id(range_id: int) -> str:
    """Return the deterministic Secret Manager id for a range's Vertex key."""
    return f"shifter-range-{int(range_id)}-vertex-key"


def _resolve_project_id(project_id: str | None) -> str:
    """Resolve the active GCP project id, requiring one to be available."""
    resolved = project_id or get_project_id()
    if not resolved:
        raise RuntimeError("GCP project ID is required to manage range Vertex credentials")
    return resolved


def _build_iam_client() -> _IamClient:
    """Build the IAM Admin client used to mint/revoke Vertex keys."""
    return import_google_module(_IAM_ADMIN_MODULE).IAMClient()


def _build_secret_client() -> _SecretClient:
    """Build the Secret Manager client used to store the Vertex key."""
    return import_google_module(_SECRETMANAGER_MODULE).SecretManagerServiceClient()


def _google_exceptions() -> _GoogleExceptions:
    """Return the Google API exception module (NotFound / AlreadyExists)."""
    return import_google_module(_GOOGLE_EXCEPTIONS_MODULE)


def ensure_range_vertex_key(
    range_id: int,
    service_account_email: str,
    *,
    iam_client: _IamClient | None = None,
    secret_client: _SecretClient | None = None,
    google_exceptions: _GoogleExceptions | None = None,
    project_id: str | None = None,
    host_service_account_email: str = "",
) -> str:
    """Mint (or reuse) a per-range Vertex SA key and return its secret name.

    Idempotent: if the range's key secret already exists it is returned
    unchanged, so re-running provisioning does not accumulate keys.

    When ``host_service_account_email`` is set, the range host SA is granted
    ``secretmanager.secretAccessor`` on *this* secret only (the range host reads
    its own Vertex key from Secret Manager during bootstrap). Scoping the grant
    to the per-range secret keeps the host SA from reading platform secrets and
    avoids a broad project-level grant; the binding is dropped with the secret at
    teardown.
    """
    if not service_account_email:
        raise RuntimeError("A Vertex service account email is required to mint a range Vertex credential")
    resolved_project = _resolve_project_id(project_id)
    exceptions = google_exceptions or _google_exceptions()
    secrets = secret_client or _build_secret_client()
    secret_id = _vertex_secret_id(range_id)
    secret_name = f"projects/{resolved_project}/secrets/{secret_id}"

    with suppress(exceptions.NotFound):
        secrets.access_secret_version(request={"name": f"{secret_name}/versions/latest"})
        logger.info("Range Vertex key secret exists secret_fp=%s", safe_log_fingerprint(secret_name))
        return secret_name

    iam = iam_client or _build_iam_client()
    key = iam.create_service_account_key(request={"name": f"projects/-/serviceAccounts/{service_account_email}"})
    key_json = (
        key.private_key_data.decode("utf-8") if isinstance(key.private_key_data, bytes) else str(key.private_key_data)
    )

    with suppress(exceptions.AlreadyExists):
        secrets.create_secret(
            request={
                "parent": f"projects/{resolved_project}",
                "secret_id": secret_id,
                "secret": {"replication": {"automatic": {}}},
            }
        )
    secrets.add_secret_version(request={"parent": secret_name, "payload": {"data": key_json.encode("utf-8")}})
    if host_service_account_email:
        # The secret is freshly created here, so set (not merge) a policy that
        # grants only the range host SA read access to this one secret.
        secrets.set_iam_policy(
            request={
                "resource": secret_name,
                "policy": {
                    "bindings": [
                        {
                            "role": "roles/secretmanager.secretAccessor",
                            "members": [f"serviceAccount:{host_service_account_email}"],
                        }
                    ]
                },
            }
        )
    logger.info("Minted range Vertex key secret_fp=%s", safe_log_fingerprint(secret_name))
    return secret_name


def delete_range_vertex_key(
    range_id: int,
    *,
    iam_client: _IamClient | None = None,
    secret_client: _SecretClient | None = None,
    google_exceptions: _GoogleExceptions | None = None,
    project_id: str | None = None,
) -> None:
    """Delete a range's Vertex SA key and its secret, ignoring missing resources."""
    try:
        resolved_project = _resolve_project_id(project_id)
    except RuntimeError:
        return
    exceptions = google_exceptions or _google_exceptions()
    secrets = secret_client or _build_secret_client()
    secret_id = _vertex_secret_id(range_id)
    secret_name = f"projects/{resolved_project}/secrets/{secret_id}"

    key_name = ""
    with suppress(exceptions.NotFound):
        response = secrets.access_secret_version(request={"name": f"{secret_name}/versions/latest"})
        key_name = _key_resource_name(response.payload.data)

    if key_name:
        iam = iam_client or _build_iam_client()
        with suppress(exceptions.NotFound):
            iam.delete_service_account_key(request={"name": key_name})
            logger.info("Deleted range Vertex SA key key_fp=%s", safe_log_fingerprint(key_name))

    with suppress(exceptions.NotFound):
        secrets.delete_secret(request={"name": secret_name})
        logger.info("Deleted range Vertex key secret secret_fp=%s", safe_log_fingerprint(secret_name))


def _key_resource_name(payload_data: bytes) -> str:
    """Reconstruct the SA key resource name from stored key JSON."""
    try:
        parsed = json.loads(payload_data.decode("utf-8") if isinstance(payload_data, bytes) else str(payload_data))
    except (ValueError, AttributeError):
        return ""
    email = str(parsed.get("client_email", "")).strip()
    key_id = str(parsed.get("private_key_id", "")).strip()
    if not email or not key_id:
        return ""
    return f"projects/-/serviceAccounts/{email}/keys/{key_id}"
