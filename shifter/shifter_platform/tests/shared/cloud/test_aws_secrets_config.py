"""Tests for the shared botocore client config and its use by AWSSecretsStore.

A stalled Secrets Manager on (or one hop off) the portal request path must fail
fast rather than hang on botocore's long default connect/read timeouts (#929).
The timeout/retry policy lives in one place — ``secrets_client_config`` — and the
Secrets Manager adapter builds its client through it.
"""

from unittest.mock import MagicMock, patch

from botocore.config import Config


class TestSecretsClientConfig:
    def test_returns_botocore_config_with_default_timeouts(self, settings):
        from shared.cloud.aws.config import secrets_client_config

        for name in (
            "AWS_SECRETS_CONNECT_TIMEOUT_SECONDS",
            "AWS_SECRETS_READ_TIMEOUT_SECONDS",
            "AWS_SECRETS_MAX_ATTEMPTS",
        ):
            if hasattr(settings, name):
                delattr(settings, name)

        config = secrets_client_config()

        assert isinstance(config, Config)
        assert config.connect_timeout == 2
        assert config.read_timeout == 5
        assert config.retries["max_attempts"] == 2

    def test_honors_configured_timeouts(self, settings):
        from shared.cloud.aws.config import secrets_client_config

        settings.AWS_SECRETS_CONNECT_TIMEOUT_SECONDS = 3
        settings.AWS_SECRETS_READ_TIMEOUT_SECONDS = 7
        settings.AWS_SECRETS_MAX_ATTEMPTS = 4

        config = secrets_client_config()

        assert config.connect_timeout == 3
        assert config.read_timeout == 7
        assert config.retries["max_attempts"] == 4

    def test_clamps_non_positive_values_to_minimum(self, settings):
        from shared.cloud.aws.config import secrets_client_config

        settings.AWS_SECRETS_CONNECT_TIMEOUT_SECONDS = 0
        settings.AWS_SECRETS_READ_TIMEOUT_SECONDS = -1
        settings.AWS_SECRETS_MAX_ATTEMPTS = 0

        config = secrets_client_config()

        assert config.connect_timeout == 1
        assert config.read_timeout == 1
        assert config.retries["max_attempts"] == 1


class TestSecretsStoreUsesConfig:
    def test_get_client_passes_bounded_config(self, settings):
        from shared.cloud.aws.secrets import AWSSecretsStore

        settings.CLOUD_PROVIDER = "aws"
        with patch("boto3.client", return_value=MagicMock()) as mock_client:
            AWSSecretsStore._get_client()

        config = mock_client.call_args.kwargs["config"]
        assert isinstance(config, Config)
        assert config.connect_timeout == 2
        assert config.read_timeout == 5
        assert config.retries["max_attempts"] == 2
