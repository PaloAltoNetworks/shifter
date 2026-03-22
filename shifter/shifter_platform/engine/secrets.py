"""AWS Secrets Manager service for SSH key retrieval."""

import logging

from shared.cloud import get_secrets_store
from shared.cloud.exceptions import CloudSecretsError

logger = logging.getLogger(__name__)


class SecretsError(Exception):
    """Error retrieving secret from AWS Secrets Manager."""

    pass


def get_ssh_key(secret_arn: str) -> str:
    """
    Retrieve SSH private key from AWS Secrets Manager.

    Args:
        secret_arn: The ARN of the secret containing the SSH private key

    Returns:
        The SSH private key as a string

    Raises:
        SecretsError: If the secret cannot be retrieved
    """
    if not secret_arn:
        raise SecretsError("Secret ARN is required")

    try:
        return get_secrets_store().get_secret(secret_arn)
    except CloudSecretsError as e:
        logger.exception("Failed to retrieve secret %s", secret_arn)
        raise SecretsError(f"Failed to retrieve SSH key: {e}") from e
