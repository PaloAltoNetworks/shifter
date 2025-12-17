"""AWS Secrets Manager service for SSH key retrieval."""

import logging

import boto3
from botocore.exceptions import ClientError
from django.conf import settings

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
        client = boto3.client("secretsmanager", region_name=settings.AWS_REGION)
        response = client.get_secret_value(SecretId=secret_arn)

        # Secret can be stored as string or binary
        if "SecretString" in response:
            return response["SecretString"]
        else:
            # Binary secrets are base64-encoded
            import base64

            return base64.b64decode(response["SecretBinary"]).decode("utf-8")

    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "Unknown")
        logger.exception("Failed to retrieve secret %s: %s", secret_arn, error_code)
        raise SecretsError(f"Failed to retrieve SSH key: {error_code}") from e
