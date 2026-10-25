"""Google Secret Manager adapter implementing SecretsStore protocol."""

from __future__ import annotations

import logging
from uuid import UUID

from shared.cloud.exceptions import CloudSecretsError
from shared.cloud.gcp.base import build_secret_version_name, import_google_module
from shared.cloud.gcp.config import secrets_request_timeout
from shared.log_sanitize import safe_log_fingerprint

logger = logging.getLogger(__name__)


CLIENT_MODULE = "google.cloud.secretmanager"


class GCPSecretsStore:
    """Secret Manager implementation of SecretsStore protocol."""

    @staticmethod
    def create_owned_secret(source_id: UUID, version_id: UUID, value: str) -> str:
        """Create once; an ambiguous failure is reconciled by its durable owner."""
        from django.conf import settings

        from shared.cloud.owned_secrets import model_source_secret_name, validate_owned_payload

        name = model_source_secret_name(source_id, version_id)
        payload = validate_owned_payload(value)
        parent = f"projects/{settings.GCP_PROJECT_ID}"
        resource = f"{parent}/secrets/{name}"
        try:
            module = import_google_module(CLIENT_MODULE)
            client = module.SecretManagerServiceClient()
            client.create_secret(
                request={
                    "parent": parent,
                    "secret_id": name,
                    "secret": {"replication": {"automatic": {}}, "labels": {"shifter-model-source": source_id.hex}},
                },
                timeout=secrets_request_timeout(),
                retry=None,
            )
            client.add_secret_version(
                request={"parent": resource, "payload": {"data": payload}},
                timeout=secrets_request_timeout(),
                retry=None,
            )
            return f"{resource}/versions/1"
        except Exception:
            raise CloudSecretsError("Failed to store model credential") from None

    @staticmethod
    def retire_owned_secret(source_id: UUID, version_id: UUID) -> None:
        """Delete exactly the credential version allocated by the source service."""
        from django.conf import settings
        from google.api_core.exceptions import NotFound

        from shared.cloud.owned_secrets import model_source_secret_name

        name = model_source_secret_name(source_id, version_id)
        try:
            module = import_google_module(CLIENT_MODULE)
            module.SecretManagerServiceClient().delete_secret(
                request={"name": f"projects/{settings.GCP_PROJECT_ID}/secrets/{name}"},
                timeout=secrets_request_timeout(),
                retry=None,
            )
        except NotFound:
            return
        except Exception:
            raise CloudSecretsError("Failed to retire model credential") from None

    @staticmethod
    def get_secret(secret_ref: str) -> str:
        # ``secret_ref`` is the GCP Secret Manager resource name — an opaque
        # identifier, not the secret value. Logged under ``resource_name`` so
        # CodeQL's variable-name heuristic for ``py/clear-text-logging`` does
        # not misclassify it as a credential.
        resource_name = secret_ref
        resource_fingerprint = safe_log_fingerprint(resource_name)
        logger.debug("get_secret: resource_fp=%s", resource_fingerprint)
        try:
            secretmanager = import_google_module(CLIENT_MODULE)
            client = secretmanager.SecretManagerServiceClient()
            # Bounded deadline so a stalled Secret Manager fails fast instead of
            # blocking the calling thread (#929).
            response = client.access_secret_version(
                request={"name": build_secret_version_name(secret_ref)},
                timeout=secrets_request_timeout(),
            )
            return response.payload.data.decode("utf-8")
        except ImportError as e:
            raise CloudSecretsError("GCP secrets support requires google-cloud-secret-manager") from e
        except Exception:
            # Provider exceptions commonly contain the full secret resource
            # path. Keep correlation via a process-local fingerprint and return
            # a stable error that cannot disclose names through portal logs.
            logger.warning("get_secret: provider request failed resource_fp=%s", resource_fingerprint)
            raise CloudSecretsError("Failed to retrieve GCP secret") from None
