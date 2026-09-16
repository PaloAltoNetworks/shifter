"""Security tests for the GCP Secret Manager adapter."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from shared.cloud.exceptions import CloudSecretsError
from shared.cloud.gcp.secrets import GCPSecretsStore


def test_provider_failure_redacts_resource_name_and_provider_message(caplog):
    resource = "projects/range-secrets/secrets/shifter-prod-dynamic-participant-gce-range-42-ssh"
    client = MagicMock()
    client.access_secret_version.side_effect = RuntimeError(f"permission denied for {resource}")
    module = SimpleNamespace(SecretManagerServiceClient=lambda: client)

    with (
        patch.dict("sys.modules", {"google.cloud.secretmanager": module}),
        pytest.raises(CloudSecretsError) as excinfo,
    ):
        GCPSecretsStore.get_secret(resource)

    assert str(excinfo.value) == "Failed to retrieve GCP secret"
    assert excinfo.value.__cause__ is None
    assert resource not in caplog.text
    assert "permission denied" not in caplog.text
