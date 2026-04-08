"""GCP Secret Manager config store adapter implementing ConfigStore protocol.

Replaces AWS SSM Parameter Store. On GCP, configuration parameters are stored
as Secret Manager secrets (there is no separate "parameter store" service).
"""

from __future__ import annotations

import logging

from cloud.exceptions import CloudConfigStoreError

from .base import BaseGCPAdapter

logger = logging.getLogger(__name__)


class GCPConfigStore(BaseGCPAdapter):
    """Secret Manager implementation of ConfigStore protocol."""

    def _get_client(self):  # type: ignore[no-untyped-def]
        from google.cloud import secretmanager  # type: ignore[attr-defined]

        return secretmanager.SecretManagerServiceClient()

    def get_parameter(self, name: str) -> str:
        logger.debug("get_parameter: name=%s", name)
        try:
            client = self._get_client()
            # Support both full resource names and short names.
            if name.startswith("projects/"):
                secret_name = name
            else:
                project = self._get_project()
                secret_name = f"projects/{project}/secrets/{name}/versions/latest"

            response = client.access_secret_version(request={"name": secret_name})
            return response.payload.data.decode("utf-8")
        except Exception as e:
            logger.error("get_parameter: failed name=%s error=%s", name, e)
            raise CloudConfigStoreError(f"Failed to get Secret Manager parameter: {e}") from e
