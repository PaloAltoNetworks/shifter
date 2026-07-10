"""Behavior tests for engine.secrets helpers.

Drives the real provider secrets store (``get_secrets_store`` -> AWSSecretsStore)
with the Secrets Manager client mocked at the ``boto3`` boundary, instead of
patching the first-party ``get_secrets_store`` factory.
"""

import pytest
from botocore.exceptions import ClientError

from .conftest import boto3_secrets, make_secrets_client


class TestGetRdpPassword:
    """Provider-neutral RDP password fetch from the active secrets store."""

    @pytest.mark.parametrize(
        ("secret_ref", "expected_value"),
        [
            (
                "arn:aws:secretsmanager:us-east-2:1:secret:shifter/dev/range/1/victim-abc-rdp-password",
                "AWS-shaped-value!",
            ),
            (
                "projects/test/secrets/shifter-gcp-dev-range-1-victim-abc-rdp-password",
                "GCP-shaped-value!",
            ),
            ("opaque-token-with-no-shape", "PassThrough!"),
        ],
    )
    def test_passes_ref_through_to_secrets_store_and_returns_its_value(self, settings, secret_ref, expected_value):
        # Contract: get_rdp_password forwards the caller's reference to the
        # secrets store verbatim (no normalization) and returns its value.
        # Proven at the boto3 boundary: the SecretId passed to get_secret_value
        # is the caller's ref, and the SecretString flows back unchanged.
        from engine.secrets import get_rdp_password

        settings.CLOUD_PROVIDER = "aws"
        client = make_secrets_client(value=expected_value)
        with boto3_secrets(client):
            assert get_rdp_password(secret_ref) == expected_value
        client.get_secret_value.assert_called_once_with(SecretId=secret_ref)

    def test_empty_secret_ref_raises_secrets_error(self):
        from engine.secrets import SecretsError, get_rdp_password

        with pytest.raises(SecretsError, match="Secret reference is required"):
            get_rdp_password("")

    def test_none_secret_ref_raises_secrets_error(self):
        from engine.secrets import SecretsError, get_rdp_password

        with pytest.raises(SecretsError, match="Secret reference is required"):
            get_rdp_password(None)  # type: ignore[arg-type]

    def test_cloud_secrets_error_wrapped_in_secrets_error(self, settings):
        from engine.secrets import SecretsError, get_rdp_password

        settings.CLOUD_PROVIDER = "aws"
        client = make_secrets_client()
        client.get_secret_value.side_effect = ClientError(
            {"Error": {"Code": "ResourceNotFoundException", "Message": "missing"}}, "GetSecretValue"
        )
        with boto3_secrets(client), pytest.raises(SecretsError, match="Failed to retrieve RDP password"):
            get_rdp_password("secret-ref-bad")
