"""Tests for get_rdp_connection_info() in engine/services.py.

Contract (issue #762): RDP passwords for non-DC range guests come from
per-instance secret references resolved through the active provider
secret store. No shared static literals (``kali``, ``ubuntu``,
``CortexSavesTheDay!``) and no shared environment variables
(``GDC_*_PASSWORD``). The DC role keeps its deployment-scoped
``DC_DOMAIN_PASSWORD`` lookup (separate concern — domain admin) with the
existing cross-provider isolation.
"""

import os
from unittest.mock import Mock, patch

import pytest


class TestGetRdpConnectionInfo:
    """Provider-aware, per-instance RDP credential resolution."""

    # ---------------------------------------------------------------
    # Per-instance secret-ref happy paths (kali, ubuntu, windows-victim)
    # ---------------------------------------------------------------

    @pytest.mark.parametrize(
        ("os_type", "expected_username"),
        [
            ("kali", "kali"),
            ("ubuntu", "ubuntu"),
            ("windows", "Administrator"),
        ],
    )
    def test_non_dc_resolves_from_per_instance_secret_ref(self, os_type, expected_username):
        from engine.models import Range
        from engine.services import get_rdp_connection_info

        mock_user = Mock(id=1)
        instance_data = {
            "uuid": f"per-instance-{os_type}",
            "role": "victim",
            "os_type": os_type,
            "cloud_provider": "aws",
            "private_ip": "10.0.0.10",
            "rdp_password_secret_arn": (
                "arn:aws:secretsmanager:us-east-2:1:secret:shifter/dev/range/1/victim-abc-rdp-password"
            ),
        }
        mock_range = Mock(spec=Range, id=1, user=mock_user, status=Range.Status.READY)
        mock_range.get_instance_by_uuid = Mock(return_value=instance_data)

        with (
            patch.object(Range, "get_active_for_user", return_value=mock_range),
            patch("engine.services.get_rdp_password", return_value="UniquePerInstanceP4ss!"),
            patch("engine.services.get_ssh_key", return_value="fake-ssh-key"),
        ):
            result = get_rdp_connection_info(mock_user, instance_data["uuid"])

        assert result["rdp_username"] == expected_username
        assert result["rdp_password"] == "UniquePerInstanceP4ss!"

    def test_non_dc_reads_secret_ref_from_provider_metadata(self):
        # Existing provider_metadata shapes — the resolver looks under the
        # provider-specific nested dict using the same convention as
        # ``_resolve_instance_ssh_key_secret_ref``.
        from engine.models import Range
        from engine.services import get_rdp_connection_info

        mock_user = Mock(id=1)
        instance_data = {
            "uuid": "gdc-ubuntu-uuid",
            "role": "victim",
            "os_type": "ubuntu",
            "cloud_provider": "gcp",
            "provider_metadata": {
                "gdc": {
                    "private_ip": "10.200.0.50",
                    "rdp_password_secret_ref": "projects/p/secrets/range-1-victim-rdp",
                }
            },
        }
        mock_range = Mock(spec=Range, id=1, user=mock_user, status=Range.Status.READY)
        mock_range.get_instance_by_uuid = Mock(return_value=instance_data)

        with (
            patch.object(Range, "get_active_for_user", return_value=mock_range),
            patch("engine.services.get_rdp_password", return_value="GdcUniqueP4ss!") as get_pw,
            patch("engine.services.get_ssh_key", return_value="fake"),
        ):
            result = get_rdp_connection_info(mock_user, instance_data["uuid"])

        get_pw.assert_called_once_with("projects/p/secrets/range-1-victim-rdp")
        assert result["rdp_password"] == "GdcUniqueP4ss!"

    # ---------------------------------------------------------------
    # Fail-closed: no secret ref, no literal fallback
    # ---------------------------------------------------------------

    def test_secret_fetch_failure_is_converted_to_value_error(self):
        # Per codex cycle 1: a SecretsError (deleted version, IAM regression,
        # transient cloud error) must surface as ValueError so the
        # mission_control RDP view's ValueError -> 400 envelope handles
        # it consistently with a missing reference. An uncaught
        # SecretsError would otherwise yield a 500.
        from engine.models import Range
        from engine.secrets import SecretsError
        from engine.services import get_rdp_connection_info

        mock_user = Mock(id=1)
        instance_data = {
            "uuid": "fetch-fail",
            "role": "victim",
            "os_type": "kali",
            "cloud_provider": "aws",
            "private_ip": "10.0.0.10",
            "rdp_password_secret_arn": ("arn:aws:secretsmanager:us-east-2:1:secret:shifter/dev/range/1/victim-rdp"),
        }
        mock_range = Mock(spec=Range, id=1, user=mock_user, status=Range.Status.READY)
        mock_range.get_instance_by_uuid = Mock(return_value=instance_data)

        with (
            patch.object(Range, "get_active_for_user", return_value=mock_range),
            patch("engine.services.get_rdp_password", side_effect=SecretsError("boom")),
            pytest.raises(ValueError, match="RDP credentials are not available"),
        ):
            get_rdp_connection_info(mock_user, "fetch-fail")

    def test_non_dc_without_secret_ref_raises_value_error(self):
        from engine.models import Range
        from engine.services import get_rdp_connection_info

        mock_user = Mock(id=1)
        instance_data = {
            "uuid": "u",
            "role": "victim",
            "os_type": "kali",
            "cloud_provider": "aws",
            "private_ip": "10.0.0.10",
        }
        mock_range = Mock(spec=Range, id=1, user=mock_user, status=Range.Status.READY)
        mock_range.get_instance_by_uuid = Mock(return_value=instance_data)

        with (
            patch.object(Range, "get_active_for_user", return_value=mock_range),
            patch.dict(os.environ, {}, clear=True),
            pytest.raises(ValueError, match="RDP credentials are not available"),
        ):
            get_rdp_connection_info(mock_user, "u")

    @pytest.mark.parametrize(
        ("os_type",),
        [("kali",), ("ubuntu",), ("windows",)],
    )
    def test_non_dc_does_not_return_static_literal_fallback(self, os_type):
        # Even when env vars that previously carried shared passwords
        # are set, the response must not contain any of the legacy
        # literal values. This guards against regression: someone
        # re-introducing a fallback during a future refactor.
        from engine.models import Range
        from engine.services import get_rdp_connection_info

        mock_user = Mock(id=1)
        instance_data = {
            "uuid": f"no-ref-{os_type}",
            "role": "victim",
            "os_type": os_type,
            "cloud_provider": "gcp",
            "private_ip": "10.0.0.20",
        }
        mock_range = Mock(spec=Range, id=1, user=mock_user, status=Range.Status.READY)
        mock_range.get_instance_by_uuid = Mock(return_value=instance_data)

        legacy_env = {
            "GDC_KALI_PASSWORD": "kali",
            "GDC_UBUNTU_PASSWORD": "ubuntu",
            "GDC_WINDOWS_ADMIN_PASSWORD": "CortexSavesTheDay!",
        }
        # Without a secret ref the call MUST fail closed regardless of
        # what legacy env vars are present — no payload returned, nothing
        # to leak.
        with (
            patch.object(Range, "get_active_for_user", return_value=mock_range),
            patch.dict(os.environ, legacy_env, clear=True),
            pytest.raises(ValueError),
        ):
            get_rdp_connection_info(mock_user, instance_data["uuid"])

    # ---------------------------------------------------------------
    # DC role (separate concern, unchanged behavior preserved)
    # ---------------------------------------------------------------

    def test_aws_dc_uses_dc_domain_password_env(self):
        from engine.models import Range
        from engine.services import get_rdp_connection_info

        mock_user = Mock(id=1)
        instance_data = {
            "uuid": "aws-dc-uuid",
            "role": "dc",
            "os_type": "windows",
            "cloud_provider": "aws",
            "private_ip": "10.100.0.130",
        }
        mock_range = Mock(spec=Range, id=1, user=mock_user, status=Range.Status.READY)
        mock_range.get_instance_by_uuid = Mock(return_value=instance_data)

        with (
            patch.object(Range, "get_active_for_user", return_value=mock_range),
            patch.dict(
                os.environ,
                {"CLOUD_PROVIDER": "aws", "DC_DOMAIN_PASSWORD": "AwsDcPass123!"},
                clear=True,
            ),
        ):
            result = get_rdp_connection_info(mock_user, instance_data["uuid"])

        assert result["rdp_username"] == "Administrator"
        assert result["rdp_password"] == "AwsDcPass123!"

    def test_aws_dc_unset_raises_value_error(self):
        from engine.models import Range
        from engine.services import get_rdp_connection_info

        mock_user = Mock(id=1)
        instance_data = {
            "uuid": "aws-dc-no-secret",
            "role": "dc",
            "os_type": "windows",
            "cloud_provider": "aws",
            "private_ip": "10.100.0.131",
        }
        mock_range = Mock(spec=Range, id=1, user=mock_user, status=Range.Status.READY)
        mock_range.get_instance_by_uuid = Mock(return_value=instance_data)

        with (
            patch.object(Range, "get_active_for_user", return_value=mock_range),
            patch.dict(os.environ, {"CLOUD_PROVIDER": "aws"}, clear=True),
            pytest.raises(ValueError, match="DC_DOMAIN_PASSWORD is not configured"),
        ):
            get_rdp_connection_info(mock_user, "aws-dc-no-secret")

    def test_gcp_dc_cross_provider_raises_value_error(self):
        from engine.models import Range
        from engine.services import get_rdp_connection_info

        mock_user = Mock(id=1)
        instance_data = {
            "uuid": "gdc-dc-cross-provider",
            "role": "dc",
            "os_type": "windows",
            "cloud_provider": "gcp",
            "private_ip": "10.200.0.132",
        }
        mock_range = Mock(spec=Range, id=1, user=mock_user, status=Range.Status.READY)
        mock_range.get_instance_by_uuid = Mock(return_value=instance_data)

        env_aws_portal = {"CLOUD_PROVIDER": "aws", "DC_DOMAIN_PASSWORD": "AwsLeak"}
        with (
            patch.object(Range, "get_active_for_user", return_value=mock_range),
            patch.dict(os.environ, env_aws_portal, clear=True),
            pytest.raises(ValueError, match="does not match portal deployment provider"),
        ):
            get_rdp_connection_info(mock_user, "gdc-dc-cross-provider")
