"""GCP Secret Manager adapter (stub).

Will replace AWS Secrets Manager for SSH key retrieval.
Used by engine/secrets.py:get_ssh_key() for terminal/RDP connections.
"""

from __future__ import annotations

from shared.cloud.exceptions import CloudProviderNotImplementedError


class GCPSecretsStore:
    """Secret Manager — stub, not yet implemented."""

    def get_secret(self, secret_id: str) -> str:
        raise CloudProviderNotImplementedError("gcp")
