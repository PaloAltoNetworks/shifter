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
dynamic, per-range part is the key. Service-account keys are credentials for the
same IAM principal, not separate principals: every key on that shared account
has the account's identical Vertex authorization. Per-range deletion revokes one
credential but does not provide per-range IAM isolation; #681 owns any future
move to genuinely separate workload principals.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator, MutableSequence
from contextlib import suppress
from typing import Protocol, cast

from cloud.gcp.base import get_project_id, import_google_module
from gcp_dynamic_secrets import (
    DynamicSecretClass,
    SecretLocations,
    canonical_secret_id,
    delete_all,
    dynamic_secret_project_id,
    read_or_create,
    secret_locations,
)
from log_redact import safe_log_fingerprint

logger = logging.getLogger(__name__)

_IAM_ADMIN_MODULE = "google.cloud.iam_admin_v1"
_SECRETMANAGER_MODULE = "google.cloud.secretmanager"
_GOOGLE_EXCEPTIONS_MODULE = "google.api_core.exceptions"
_CREDENTIAL_ACCESSOR_ROLE = "roles/secretmanager.secretAccessor"


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

    def get_secret(self, *, request: dict[str, object]) -> object:
        """Return an existing secret container."""

    def create_secret(self, *, request: dict[str, object]) -> object:
        """Create a Secret Manager secret."""

    def add_secret_version(self, *, request: dict[str, object]) -> object:
        """Add a Secret Manager secret version."""

    def set_iam_policy(self, *, request: dict[str, object]) -> object:
        """Set the IAM policy on a secret (scoped per-range accessor grant)."""

    def get_iam_policy(self, *, request: dict[str, object]) -> object:
        """Get the IAM policy on a secret before merging an accessor grant."""

    def delete_secret(self, *, request: dict[str, object]) -> object:
        """Delete a Secret Manager secret."""


class _GoogleExceptions(Protocol):
    """Google exception module subset used by the Vertex credential path."""

    NotFound: type[Exception]
    AlreadyExists: type[Exception]


class _PolicyBinding(Protocol):
    """IAM policy binding fields used by this module."""

    role: str
    members: MutableSequence[str]


class _PolicyBindings(Protocol):
    """Protobuf repeated-binding operations used by this module."""

    def __iter__(self) -> Iterator[object]:
        """Iterate through bindings."""

    def add(self, *, role: str, members: list[str]) -> object:
        """Append one binding."""


class _Policy(Protocol):
    """IAM policy fields used by this module."""

    bindings: _PolicyBindings


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


def _shared_secret_id() -> str:
    """Return the configured shared Vertex key secret id (empty when unset).

    When set, ranges copy the key from this one shared secret instead of minting
    a fresh per-range SA key, which avoids service-account key quota pressure on
    deployments that provision the shared key out-of-band.
    """
    return os.environ.get("GCP_RANGE_VERTEX_SHARED_KEY_SECRET_ID", "").strip()


def _shared_secret_name(shared_secret_id: str, fallback_project_id: str) -> str:
    """Resolve a shared secret id to its full Secret Manager resource name."""
    if shared_secret_id.startswith("projects/"):
        return shared_secret_id
    source_project_id = os.environ.get("GCP_RANGE_VERTEX_PROJECT_ID", "").strip() or fallback_project_id
    return f"projects/{source_project_id}/secrets/{shared_secret_id}"


def _as_bytes(data: object) -> bytes:
    """Coerce a Secret Manager / SA-key payload to bytes."""
    return data if isinstance(data, bytes) else str(data).encode("utf-8")


def _resolve_range_key_json(
    *,
    service_account_email: str,
    resolved_project: str,
    secrets: _SecretClient,
    shared_secret_id: str,
    iam_client: _IamClient | None,
) -> tuple[bytes, str]:
    """Return the Vertex key JSON, copied from the shared secret or freshly minted."""
    if shared_secret_id:
        shared_secret_name = _shared_secret_name(shared_secret_id, resolved_project)
        shared_version = secrets.access_secret_version(request={"name": f"{shared_secret_name}/versions/latest"})
        return _as_bytes(shared_version.payload.data), ""
    iam = iam_client or _build_iam_client()
    key = iam.create_service_account_key(request={"name": f"projects/-/serviceAccounts/{service_account_email}"})
    return _as_bytes(key.private_key_data), str(key.name)


def _vertex_secret_locations(platform_project_id: str, range_id: int) -> SecretLocations:
    """Resolve legacy and canonical locations for a range Vertex key."""
    return secret_locations(
        platform_project_id=platform_project_id,
        dynamic_project_id=dynamic_secret_project_id(),
        legacy_secret_id=_vertex_secret_id(range_id),
        canonical_secret_id=canonical_secret_id(
            credential_class=DynamicSecretClass.VERTEX_SERVICE_ACCOUNT_KEY,
            scope=f"range-{range_id}",
        ),
    )


def _binding_role(binding: object) -> str:
    """Read a role from either a dictionary or protobuf IAM binding."""
    if isinstance(binding, dict):
        return str(cast(dict[str, object], binding).get("role", ""))
    return str(cast(_PolicyBinding, binding).role)


def _binding_members(binding: object) -> MutableSequence[str]:
    """Read the mutable members list from a dictionary or protobuf binding."""
    if isinstance(binding, dict):
        raw_members = cast(dict[str, object], binding).setdefault("members", [])
        if not isinstance(raw_members, list):
            raise TypeError("IAM binding members must be a list")
        return cast(list[str], raw_members)
    return cast(_PolicyBinding, binding).members


def _policy_bindings(policy: object) -> list[object] | _PolicyBindings:
    """Read the mutable bindings collection from a dictionary or protobuf policy."""
    if isinstance(policy, dict):
        raw_bindings = cast(dict[str, object], policy).setdefault("bindings", [])
        if not isinstance(raw_bindings, list):
            raise TypeError("IAM policy bindings must be a list")
        return cast(list[object], raw_bindings)
    return cast(_Policy, policy).bindings


def _grant_host_access(secrets: _SecretClient, secret_name: str, host_service_account_email: str) -> None:
    """Merge the per-secret host grant without discarding unrelated bindings."""
    member = f"serviceAccount:{host_service_account_email}"
    policy = secrets.get_iam_policy(request={"resource": secret_name})
    bindings = _policy_bindings(policy)
    for binding in bindings:
        if _binding_role(binding) == _CREDENTIAL_ACCESSOR_ROLE:
            members = _binding_members(binding)
            if member not in members:
                members.append(member)
            break
    else:
        if isinstance(bindings, list):
            bindings.append({"role": _CREDENTIAL_ACCESSOR_ROLE, "members": [member]})
        else:
            bindings.add(role=_CREDENTIAL_ACCESSOR_ROLE, members=[member])
    secrets.set_iam_policy(request={"resource": secret_name, "policy": policy})


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
    locations = _vertex_secret_locations(resolved_project, range_id)
    shared_secret_id = _shared_secret_id()
    minted_key_name = ""

    def _payload_factory() -> str:
        """Resolve the key payload and retain any newly minted key name for cleanup."""
        nonlocal minted_key_name
        key_json, minted_key_name = _resolve_range_key_json(
            service_account_email=service_account_email,
            resolved_project=resolved_project,
            secrets=secrets,
            shared_secret_id=shared_secret_id,
            iam_client=iam_client,
        )
        return key_json.decode("utf-8")

    try:
        secret_name, _key_json = read_or_create(
            secrets,
            exceptions,
            locations,
            _payload_factory,
        )
    except Exception as publication_error:
        if not minted_key_name:
            raise
        # A failed add-version response can be ambiguous: the server may have
        # committed the version before the client saw an error. Read it back
        # before deleting the newly minted key. If a concurrent writer won,
        # revoke only this invocation's unused key and continue with the winner.
        try:
            response = secrets.access_secret_version(request={"name": f"{locations.create_ref}/versions/latest"})
        except exceptions.NotFound:
            iam = iam_client or _build_iam_client()
            with suppress(exceptions.NotFound):
                iam.delete_service_account_key(request={"name": minted_key_name})
            raise publication_error from None
        stored_key_name = _key_resource_name(response.payload.data)
        if stored_key_name.rsplit("/", 1)[-1] != minted_key_name.rsplit("/", 1)[-1]:
            iam = iam_client or _build_iam_client()
            with suppress(exceptions.NotFound):
                iam.delete_service_account_key(request={"name": minted_key_name})
        secret_name = locations.create_ref
    if host_service_account_email:
        _grant_host_access(secrets, secret_name, host_service_account_email)
    action = "Copied shared" if shared_secret_id else "Minted"
    logger.info("%s range Vertex key secret_fp=%s", action, safe_log_fingerprint(secret_name))
    return secret_name


def _stored_vertex_key_names(
    secrets: _SecretClient,
    exceptions: _GoogleExceptions,
    locations: SecretLocations,
) -> set[str]:
    """Collect the distinct SA key names referenced by all migration locations."""
    key_names: set[str] = set()
    for secret_name in locations.read_refs:
        try:
            response = secrets.access_secret_version(request={"name": f"{secret_name}/versions/latest"})
        except exceptions.NotFound:
            continue
        if key_name := _key_resource_name(response.payload.data):
            key_names.add(key_name)
    return key_names


def _delete_vertex_keys(
    key_names: set[str],
    iam: _IamClient,
    exceptions: _GoogleExceptions,
) -> None:
    """Delete collected service-account keys, ignoring already-absent keys."""
    for key_name in sorted(key_names):
        with suppress(exceptions.NotFound):
            iam.delete_service_account_key(request={"name": key_name})
            logger.info("Deleted range Vertex SA key key_fp=%s", safe_log_fingerprint(key_name))


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
    locations = _vertex_secret_locations(resolved_project, range_id)

    shared_secret_id = _shared_secret_id()

    key_names = set() if shared_secret_id else _stored_vertex_key_names(secrets, exceptions, locations)

    if key_names:
        _delete_vertex_keys(key_names, iam_client or _build_iam_client(), exceptions)

    delete_all(secrets, exceptions, locations)
    logger.info(
        "Deleted range Vertex key secret locations secret_fp=%s",
        safe_log_fingerprint("|".join(locations.delete_refs)),
    )


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
