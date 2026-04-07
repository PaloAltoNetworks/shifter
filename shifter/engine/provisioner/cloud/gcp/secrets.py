"""GCP Secret Manager secrets adapter (stub).

Will replace AWS Secrets Manager for secret retrieval.
"""

from __future__ import annotations

from cloud.exceptions import CloudProviderNotImplementedError

from .base import BaseGCPAdapter


class GCPSecretsStore(BaseGCPAdapter):
    """Secret Manager secrets store — stub, not yet implemented."""

    def get_secret(self, secret_id: str) -> str:
        raise CloudProviderNotImplementedError("gcp", "SecretsStore")
