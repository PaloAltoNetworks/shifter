"""GCP Secret Manager secrets adapter implementing SecretsStore protocol.

Replaces AWS Secrets Manager for SSH key retrieval and other secrets.
"""

from __future__ import annotations

import logging

from cloud.exceptions import CloudSecretsError

from .base import BaseGCPAdapter

logger = logging.getLogger(__name__)


class GCPSecretsStore(BaseGCPAdapter):
    """Secret Manager implementation of SecretsStore protocol."""

    def _get_client(self):  # type: ignore[no-untyped-def]
        from google.cloud import secretmanager  # type: ignore[attr-defined]

        return secretmanager.SecretManagerServiceClient()

    def get_secret(self, secret_id: str) -> str:
        logger.debug("get_secret: secret_id=%s", secret_id)
        try:
            client = self._get_client()
            # Support both full resource names and short names.
            if secret_id.startswith("projects/"):
                name = secret_id
            else:
                project = self._get_project()
                name = f"projects/{project}/secrets/{secret_id}/versions/latest"

            response = client.access_secret_version(request={"name": name})
            return response.payload.data.decode("utf-8")
        except Exception as e:
            logger.error("get_secret: failed secret_id=%s error=%s", secret_id, e)
            raise CloudSecretsError(f"Failed to retrieve secret: {e}") from e
