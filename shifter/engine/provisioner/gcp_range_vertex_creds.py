"""Delete legacy per-range provider-key copies without provider IAM authority.

The deployment retires the old invocation service account and its keys. Shared
or externally owned keys must be revoked by their owner during migration. Guest
teardown deletes only this range's stored copies; it never reads a key payload,
assumes key ownership from its contents, or grants the provisioner key-admin IAM.
"""

from __future__ import annotations

import logging

from cloud.gcp.base import get_project_id, import_google_module
from gcp_dynamic_secrets import (
    DynamicSecretClass,
    GoogleSecretExceptions,
    SecretDeletionClient,
    canonical_secret_id,
    delete_all,
    dynamic_secret_project_id,
    secret_locations,
)
from log_redact import safe_log_fingerprint

logger = logging.getLogger(__name__)


def delete_range_vertex_key(
    range_id: int,
    *,
    secret_client: SecretDeletionClient | None = None,
    google_exceptions: GoogleSecretExceptions | None = None,
    project_id: str | None = None,
) -> None:
    """Remove only legacy and canonical copies owned by the retiring range."""
    resolved_project = project_id or get_project_id()
    if not resolved_project:
        return
    secrets = secret_client or import_google_module("google.cloud.secretmanager").SecretManagerServiceClient()
    exceptions = google_exceptions or import_google_module("google.api_core.exceptions")
    locations = secret_locations(
        platform_project_id=resolved_project,
        dynamic_project_id=dynamic_secret_project_id(),
        legacy_secret_id=f"shifter-range-{int(range_id)}-vertex-key",
        canonical_secret_id=canonical_secret_id(
            credential_class=DynamicSecretClass.VERTEX_SERVICE_ACCOUNT_KEY,
            scope=f"range-{range_id}",
        ),
    )
    delete_all(secrets, exceptions, locations)
    logger.info(
        "Deleted legacy model credential copies secret_fp=%s", safe_log_fingerprint("|".join(locations.delete_refs))
    )
