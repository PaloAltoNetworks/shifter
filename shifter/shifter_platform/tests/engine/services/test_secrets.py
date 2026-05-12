"""Tests for engine.secrets helpers."""

from unittest.mock import Mock, patch

import pytest


class TestGetRdpPassword:
    """Provider-neutral RDP password fetch from the active secrets store."""

    def test_returns_secret_value_from_secrets_store(self):
        from engine.secrets import get_rdp_password

        fake_store = Mock()
        fake_store.get_secret = Mock(return_value="r4nd-per-instance!")
        with patch("engine.secrets.get_secrets_store", return_value=fake_store):
            assert get_rdp_password("secret-ref-123") == "r4nd-per-instance!"
        fake_store.get_secret.assert_called_once_with("secret-ref-123")

    def test_empty_secret_ref_raises_secrets_error(self):
        from engine.secrets import SecretsError, get_rdp_password

        with pytest.raises(SecretsError, match="Secret reference is required"):
            get_rdp_password("")

    def test_none_secret_ref_raises_secrets_error(self):
        from engine.secrets import SecretsError, get_rdp_password

        with pytest.raises(SecretsError, match="Secret reference is required"):
            get_rdp_password(None)  # type: ignore[arg-type]

    def test_cloud_secrets_error_wrapped_in_secrets_error(self):
        from engine.secrets import SecretsError, get_rdp_password
        from shared.cloud.exceptions import CloudSecretsError

        fake_store = Mock()
        fake_store.get_secret = Mock(side_effect=CloudSecretsError("missing"))
        with (
            patch("engine.secrets.get_secrets_store", return_value=fake_store),
            pytest.raises(SecretsError, match="Failed to retrieve RDP password"),
        ):
            get_rdp_password("secret-ref-bad")
