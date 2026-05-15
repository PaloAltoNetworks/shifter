"""Tests for engine.secrets helpers."""

from unittest.mock import Mock, patch

import pytest


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
    def test_passes_ref_through_to_secrets_store_and_returns_its_value(self, secret_ref, expected_value):
        # The contract is: get_rdp_password forwards the caller's
        # reference to ``shared.cloud.get_secrets_store().get_secret()``
        # verbatim (no normalization, no provider-detection in this
        # helper) and returns whatever the store returns. Two
        # assertions together prove the contract: passthrough on input
        # (assert_called_once_with) AND on output (return-value match).
        # Parametrized to cover AWS / GCP / opaque shapes so the
        # contract holds across provider conventions.
        from engine.secrets import get_rdp_password

        fake_store = Mock()
        fake_store.get_secret = Mock(return_value=expected_value)
        with patch("engine.secrets.get_secrets_store", return_value=fake_store):
            assert get_rdp_password(secret_ref) == expected_value
        fake_store.get_secret.assert_called_once_with(secret_ref)

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
