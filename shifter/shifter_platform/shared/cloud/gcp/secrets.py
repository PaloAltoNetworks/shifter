"""Google Secret Manager adapter implementing SecretsStore protocol."""

from __future__ import annotations

import logging

from shared.cloud.exceptions import CloudSecretsError
from shared.cloud.gcp.base import build_secret_version_name, import_google_module

logger = logging.getLogger(__name__)


class GCPSecretsStore:
    """Secret Manager implementation of SecretsStore protocol."""

    def get_secret(self, secret_ref: str) -> str:
        logger.debug("get_secret: secret_ref=%s", secret_ref)
        try:
            secretmanager = import_google_module("google.cloud.secretmanager")
            client = secretmanager.SecretManagerServiceClient()
            response = client.access_secret_version(request={"name": build_secret_version_name(secret_ref)})
            return response.payload.data.decode("utf-8")
        except ImportError as e:
            raise CloudSecretsError("GCP secrets support requires google-cloud-secret-manager") from e
        except Exception as e:
            logger.exception("get_secret: failed secret_ref=%s", secret_ref)
            raise CloudSecretsError(f"Failed to retrieve GCP secret: {e}") from e
