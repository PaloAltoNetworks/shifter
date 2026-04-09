"""Google Secret Manager-backed config store implementing ConfigStore."""

from __future__ import annotations

import logging
import os

from cloud.exceptions import CloudConfigStoreError
from cloud.gcp.base import build_secret_version_name, import_google_module, normalize_parameter_name

logger = logging.getLogger(__name__)


class GCPConfigStore:
    """Secret Manager implementation of ConfigStore.

    AWS Parameter Store paths are normalized into Secret Manager IDs by replacing
    `/` with `--`. An environment variable override always wins so local or CI
    runs can inject values without creating matching secrets.
    """

    def get_parameter(self, name: str) -> str:
        logger.debug("get_parameter: name=%s", name)
        env_key = f"CLOUD_CONFIG__{name.strip('/').replace('/', '__').upper()}"
        env_value = os.environ.get(env_key)
        if env_value:
            return env_value

        try:
            secretmanager = import_google_module("google.cloud.secretmanager")
            client = secretmanager.SecretManagerServiceClient()
            secret_id = normalize_parameter_name(name)
            response = client.access_secret_version(request={"name": build_secret_version_name(secret_id)})
            return response.payload.data.decode("utf-8")
        except ImportError as e:
            raise CloudConfigStoreError("GCP config store support requires google-cloud-secret-manager") from e
        except Exception as e:
            logger.error("get_parameter: failed name=%s error=%s", name, e)
            raise CloudConfigStoreError(f"Failed to get GCP config parameter: {e}") from e
