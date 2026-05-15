"""Engine-side helpers for fetching secrets from the active provider store.

These wrap ``shared.cloud.get_secrets_store()`` so callers do not need to know
which cloud backs the deployment. The helpers fail closed when a reference is
missing or unreadable rather than returning empty strings or silently falling
back to literals.
"""

import logging

from shared.cloud import get_secrets_store
from shared.cloud.exceptions import CloudSecretsError

logger = logging.getLogger(__name__)


class SecretsError(Exception):
    """Error retrieving a secret from the active provider secret store."""


def get_ssh_key(secret_arn: str) -> str:
    """Retrieve an SSH private key from the active provider secret store.

    Args:
        secret_arn: The provider-native reference (AWS Secrets Manager ARN or
            GCP Secret Manager resource path) for the SSH private key.

    Returns:
        The SSH private key PEM as a string.

    Raises:
        SecretsError: If the reference is empty or the underlying fetch fails.
    """
    if not secret_arn:
        raise SecretsError("Secret ARN is required")

    try:
        return get_secrets_store().get_secret(secret_arn)
    except CloudSecretsError as e:
        logger.exception("Failed to retrieve SSH key secret")
        raise SecretsError(f"Failed to retrieve SSH key: {e}") from e


def get_rdp_password(secret_ref: str) -> str:
    """Retrieve a per-instance RDP password from the active provider secret store.

    The reference is a provider-native identifier — an AWS Secrets Manager
    secret ARN, a GCP Secret Manager resource path
    (``projects/<id>/secrets/<name>``), or any other value the active
    ``SecretsStore`` understands.

    Args:
        secret_ref: The provider-native reference for the RDP password.

    Returns:
        The password value.

    Raises:
        SecretsError: If the reference is empty or the underlying fetch fails.
    """
    if not secret_ref:
        raise SecretsError("Secret reference is required")

    try:
        return get_secrets_store().get_secret(secret_ref)
    except CloudSecretsError as e:
        logger.exception("Failed to retrieve RDP password secret")
        raise SecretsError(f"Failed to retrieve RDP password: {e}") from e
