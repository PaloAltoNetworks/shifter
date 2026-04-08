"""GCP Secret Manager adapter implementing SecretsStore protocol.

Replaces AWS Secrets Manager for SSH key retrieval.
Used by engine/secrets.py:get_ssh_key() for terminal/RDP connections.
"""

from __future__ import annotations

import logging

from django.conf import settings

from shared.cloud.exceptions import CloudSecretsError

logger = logging.getLogger(__name__)


class GCPSecretsStore:
    """Secret Manager implementation of SecretsStore protocol."""

    def _get_client(self):  # type: ignore[no-untyped-def]
        from google.cloud import secretmanager  # type: ignore[attr-defined]

        return secretmanager.SecretManagerServiceClient()

    def _get_project(self) -> str:
        project: str | None = getattr(settings, "GCP_PROJECT_ID", None)
        if not project:
            raise CloudSecretsError("GCP_PROJECT_ID setting is required for Secret Manager")
        return project

    def get_secret(self, secret_id: str) -> str:
        logger.debug("get_secret: secret_id=%s", secret_id)
        try:
            client = self._get_client()
            # Support both full resource names and short secret IDs.
            # Full: projects/123/secrets/my-secret/versions/latest
            # Short: my-secret (we append project and version)
            if secret_id.startswith("projects/"):
                name = secret_id
            else:
                project = self._get_project()
                name = f"projects/{project}/secrets/{secret_id}/versions/latest"
            response = client.access_secret_version(request={"name": name})
            return response.payload.data.decode("utf-8")
        except Exception as e:
            logger.exception("get_secret: failed secret_id=%s", secret_id)
            raise CloudSecretsError(f"Failed to retrieve secret: {e}") from e
