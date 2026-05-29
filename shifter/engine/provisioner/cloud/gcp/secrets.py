"""Google Secret Manager adapter implementing SecretsStore protocol."""

from __future__ import annotations

import logging

from cloud.exceptions import CloudSecretsError
from cloud.gcp.base import build_secret_version_name, import_google_module
from log_redact import safe_log_id

logger = logging.getLogger(__name__)


class GCPSecretsStore:
    """Secret Manager implementation of SecretsStore protocol."""

    @staticmethod
    def get_secret(secret_id: str) -> str:
        logger.debug("get_secret: secret_id=%s", safe_log_id(secret_id))
        try:
            secretmanager = import_google_module("google.cloud.secretmanager")
            client = secretmanager.SecretManagerServiceClient()
            response = client.access_secret_version(request={"name": build_secret_version_name(secret_id)})
            return response.payload.data.decode("utf-8")
        except ImportError as e:
            raise CloudSecretsError("GCP secrets support requires google-cloud-secret-manager") from e
        except Exception as e:
            logger.exception("get_secret: failed secret_id=%s", safe_log_id(secret_id))
            raise CloudSecretsError(f"Failed to retrieve GCP secret: {e}") from e
