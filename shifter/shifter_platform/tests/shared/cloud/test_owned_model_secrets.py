"""Managed credential versions never accept a tenant-supplied secret path."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

from shared.cloud.exceptions import CloudSecretsError
from shared.cloud.gcp.secrets import GCPSecretsStore

SOURCE = UUID(int=1)
VERSION = UUID(int=2)


def test_gcp_owned_version_creates_server_named_secret_without_readback(settings):
    settings.GCP_PROJECT_ID = "platform-example"
    client = MagicMock()
    module = SimpleNamespace(SecretManagerServiceClient=lambda: client)
    with patch.dict("sys.modules", {"google.cloud.secretmanager": module}):
        ref = GCPSecretsStore().create_owned_secret(SOURCE, VERSION, "synthetic-key")
    name = f"shifter-model-source-{SOURCE.hex}-{VERSION.hex}"
    assert ref == f"projects/platform-example/secrets/{name}/versions/1"
    assert client.create_secret.call_args.kwargs["request"]["secret_id"] == name
    assert client.add_secret_version.call_args.kwargs["request"]["payload"]["data"] == b"synthetic-key"
    client.access_secret_version.assert_not_called()


def test_gcp_failed_write_has_no_secret_or_provider_diagnostics(settings, caplog):
    settings.GCP_PROJECT_ID = "platform-example"
    client = MagicMock()
    client.create_secret.side_effect = RuntimeError("synthetic-key provider path")
    module = SimpleNamespace(SecretManagerServiceClient=lambda: client)
    with patch.dict("sys.modules", {"google.cloud.secretmanager": module}), pytest.raises(CloudSecretsError) as error:
        GCPSecretsStore().create_owned_secret(SOURCE, VERSION, "synthetic-key")
    assert "synthetic-key" not in str(error.value) + caplog.text
    assert error.value.__cause__ is None
    client.add_secret_version.assert_not_called()


def test_aws_owned_version_is_create_only_and_redacts_failures(monkeypatch):
    from shared.cloud.aws.secrets import AWSSecretsStore

    client = MagicMock()
    client.create_secret.return_value = {"ARN": "arn:aws:secretsmanager:us-east-1:123456789012:secret:owned"}
    store = AWSSecretsStore()
    monkeypatch.setattr(store, "_get_client", lambda: client)
    reference = store.create_owned_secret(SOURCE, VERSION, "synthetic-key")
    assert reference.endswith(":secret:owned")
    assert client.create_secret.call_args.kwargs["Name"] == f"shifter-model-source-{SOURCE.hex}-{VERSION.hex}"
    assert client.create_secret.call_args.kwargs["ClientRequestToken"] == str(VERSION)
    client.put_secret_value.assert_not_called()
    client.create_secret.side_effect = RuntimeError("synthetic-key")
    with pytest.raises(CloudSecretsError, match="Failed to store model credential"):
        store.create_owned_secret(SOURCE, VERSION, "synthetic-key")


def test_aws_read_failures_never_log_or_reflect_provider_diagnostics(monkeypatch, caplog):
    from unittest.mock import Mock

    from botocore.exceptions import ClientError

    from shared.cloud.aws.secrets import AWSSecretsStore
    from shared.cloud.exceptions import CloudSecretsError

    client = Mock()
    client.get_secret_value.side_effect = ClientError(
        {"Error": {"Code": "Denied", "Message": "synthetic-secret-sentinel"}}, "GetSecretValue"
    )
    monkeypatch.setattr(AWSSecretsStore, "_get_client", lambda _: client)
    with pytest.raises(CloudSecretsError) as caught:
        AWSSecretsStore().get_secret("synthetic-owned-reference-sentinel")
    assert "synthetic-secret-sentinel" not in str(caught.value)
    assert "synthetic-secret-sentinel" not in caplog.text
    assert "synthetic-owned-reference-sentinel" not in caplog.text
