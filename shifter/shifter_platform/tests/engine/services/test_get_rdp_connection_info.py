"""Behavior tests for get_rdp_connection_info() in engine/services.

Contract (issue #762): RDP passwords for non-DC range guests come from
per-instance secret references resolved through the active provider secret store.
No shared static literals and no shared ``GDC_*_PASSWORD`` environment variables.
The DC role keeps its deployment-scoped ``DC_DOMAIN_PASSWORD`` lookup.

Driven against a real active ``Range`` (resolved via ``get_active_for_user``)
with the Secrets Manager client mocked only at the ``boto3`` boundary, instead of
patching ``Range.get_active_for_user`` / ``get_rdp_password`` / ``get_ssh_key``.
"""

import os

import pytest
from botocore.exceptions import ClientError
from django.contrib.auth import get_user_model

from engine.models import Range

from .conftest import boto3_secrets, make_secrets_client

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="engine-rdp@example.com", email="engine-rdp@example.com")


def _active_range(user, instance):
    return Range.objects.create(user=user, status=Range.Status.READY, provisioned_instances=[instance])


class TestGetRdpConnectionInfo:
    @pytest.mark.parametrize(
        ("os_type", "expected_username"),
        [("kali", "kali"), ("ubuntu", "ubuntu"), ("windows", "Administrator")],
    )
    def test_non_dc_resolves_from_per_instance_secret_ref(self, settings, user, os_type, expected_username):
        from engine.services import get_rdp_connection_info

        settings.CLOUD_PROVIDER = "aws"
        instance = {
            "uuid": f"per-instance-{os_type}",
            "role": "victim",
            "os_type": os_type,
            "cloud_provider": "aws",
            "private_ip": "10.0.0.10",
            "rdp_password_secret_arn": "arn:aws:secretsmanager:us-east-2:1:secret:shifter/dev/range/1/victim-rdp",
        }
        _active_range(user, instance)
        client = make_secrets_client(value="UniquePerInstanceP4ss!")
        with boto3_secrets(client):
            result = get_rdp_connection_info(user, instance["uuid"])

        assert result["rdp_username"] == expected_username
        assert result["rdp_password"] == "UniquePerInstanceP4ss!"

    def test_non_dc_reads_secret_ref_from_provider_metadata(self, settings, user):
        from engine.services import get_rdp_connection_info

        # The active secrets store is the portal's AWS store (boto3 boundary);
        # the instance's gcp provider_metadata only drives which ref is read.
        settings.CLOUD_PROVIDER = "aws"
        ref = "projects/p/secrets/range-1-victim-rdp"
        instance = {
            "uuid": "gdc-ubuntu-uuid",
            "role": "victim",
            "os_type": "ubuntu",
            "cloud_provider": "gcp",
            "provider_metadata": {"gdc": {"private_ip": "10.200.0.50", "rdp_password_secret_ref": ref}},
        }
        _active_range(user, instance)
        client = make_secrets_client(value="GdcUniqueP4ss!")
        with boto3_secrets(client):
            result = get_rdp_connection_info(user, instance["uuid"])

        # The per-instance ref is forwarded verbatim to the secrets store.
        client.get_secret_value.assert_called_once_with(SecretId=ref)
        assert result["rdp_password"] == "GdcUniqueP4ss!"

    def test_secret_fetch_failure_is_converted_to_value_error(self, settings, user):
        # A SecretsError (deleted version, IAM regression, transient cloud error)
        # must surface as ValueError so the RDP view's 400 envelope handles it.
        from engine.services import get_rdp_connection_info

        settings.CLOUD_PROVIDER = "aws"
        instance = {
            "uuid": "fetch-fail",
            "role": "victim",
            "os_type": "kali",
            "cloud_provider": "aws",
            "private_ip": "10.0.0.10",
            "rdp_password_secret_arn": "arn:aws:secretsmanager:us-east-2:1:secret:shifter/dev/range/1/victim-rdp",
        }
        _active_range(user, instance)
        client = make_secrets_client()
        client.get_secret_value.side_effect = ClientError(
            {"Error": {"Code": "ResourceNotFoundException", "Message": "boom"}}, "GetSecretValue"
        )
        with boto3_secrets(client), pytest.raises(ValueError, match="RDP credentials are not available"):
            get_rdp_connection_info(user, "fetch-fail")

    def test_non_dc_without_secret_ref_raises_value_error(self, settings, user):
        from engine.services import get_rdp_connection_info

        settings.CLOUD_PROVIDER = "aws"
        instance = {
            "uuid": "u",
            "role": "victim",
            "os_type": "kali",
            "cloud_provider": "aws",
            "private_ip": "10.0.0.10",
        }
        _active_range(user, instance)
        with patch_env({}), pytest.raises(ValueError, match="RDP credentials are not available"):
            get_rdp_connection_info(user, "u")

    @pytest.mark.parametrize("os_type", ["kali", "ubuntu", "windows"])
    def test_non_dc_does_not_return_static_literal_fallback(self, settings, user, os_type):
        # Even with legacy shared-password env vars set, a missing secret ref must
        # fail closed — no payload to leak.
        from engine.services import get_rdp_connection_info

        settings.CLOUD_PROVIDER = "gcp"
        instance = {
            "uuid": f"no-ref-{os_type}",
            "role": "victim",
            "os_type": os_type,
            "cloud_provider": "gcp",
            "private_ip": "10.0.0.20",
        }
        _active_range(user, instance)
        legacy_env = {
            "GDC_KALI_PASSWORD": "kali",
            "GDC_UBUNTU_PASSWORD": "ubuntu",
            "GDC_WINDOWS_ADMIN_PASSWORD": "CortexSavesTheDay!",
        }
        with patch_env(legacy_env), pytest.raises(ValueError):
            get_rdp_connection_info(user, instance["uuid"])

    def test_aws_dc_uses_dc_domain_password_env(self, settings, user):
        from engine.services import get_rdp_connection_info

        settings.CLOUD_PROVIDER = "aws"
        instance = {
            "uuid": "aws-dc-uuid",
            "role": "dc",
            "os_type": "windows",
            "cloud_provider": "aws",
            "private_ip": "10.100.0.130",
        }
        _active_range(user, instance)
        with patch_env({"CLOUD_PROVIDER": "aws", "DC_DOMAIN_PASSWORD": "AwsDcPass123!"}):
            result = get_rdp_connection_info(user, instance["uuid"])

        assert result["rdp_username"] == "Administrator"
        assert result["rdp_password"] == "AwsDcPass123!"

    def test_aws_dc_unset_raises_value_error(self, settings, user):
        from engine.services import get_rdp_connection_info

        settings.CLOUD_PROVIDER = "aws"
        instance = {
            "uuid": "aws-dc-no-secret",
            "role": "dc",
            "os_type": "windows",
            "cloud_provider": "aws",
            "private_ip": "10.100.0.131",
        }
        _active_range(user, instance)
        with (
            patch_env({"CLOUD_PROVIDER": "aws"}),
            pytest.raises(ValueError, match="DC_DOMAIN_PASSWORD is not configured"),
        ):
            get_rdp_connection_info(user, "aws-dc-no-secret")

    def test_gcp_dc_cross_provider_raises_value_error(self, settings, user):
        from engine.services import get_rdp_connection_info

        settings.CLOUD_PROVIDER = "aws"
        instance = {
            "uuid": "gdc-dc-cross-provider",
            "role": "dc",
            "os_type": "windows",
            "cloud_provider": "gcp",
            "private_ip": "10.200.0.132",
        }
        _active_range(user, instance)
        with (
            patch_env({"CLOUD_PROVIDER": "aws", "DC_DOMAIN_PASSWORD": "AwsLeak"}),
            pytest.raises(ValueError, match="does not match portal deployment provider"),
        ):
            get_rdp_connection_info(user, "gdc-dc-cross-provider")


def patch_env(env):
    from unittest.mock import patch

    return patch.dict(os.environ, env, clear=True)


class TestGetRdpConnectionInfoMultiRange:
    """get_rdp_connection_info resolves the correct range when a user holds two (#450)."""

    def test_resolves_correct_range_with_two_active_ranges(self, settings, user):
        """With MC and CTF ranges active, the UUID selects the right range."""
        from engine.services import get_rdp_connection_info

        settings.CLOUD_PROVIDER = "aws"
        mc_instance = {
            "uuid": "mc-rdp-uuid",
            "role": "victim",
            "os_type": "kali",
            "cloud_provider": "aws",
            "private_ip": "10.0.0.10",
            "rdp_password_secret_arn": "arn:aws:secretsmanager:us-east-2:1:secret:mc-victim-rdp",
        }
        ctf_instance = {
            "uuid": "ctf-rdp-uuid",
            "role": "victim",
            "os_type": "kali",
            "cloud_provider": "aws",
            "private_ip": "10.0.0.20",
            "rdp_password_secret_arn": "arn:aws:secretsmanager:us-east-2:1:secret:ctf-victim-rdp",
        }
        # Two simultaneous active ranges for the same user.
        Range.objects.create(user=user, status=Range.Status.READY, provisioned_instances=[mc_instance])
        Range.objects.create(user=user, status=Range.Status.READY, provisioned_instances=[ctf_instance])

        client = make_secrets_client(value="CorrectPass!")
        with boto3_secrets(client):
            result = get_rdp_connection_info(user, "ctf-rdp-uuid")

        assert result["private_ip"] == "10.0.0.20"

    def test_raises_not_found_when_uuid_not_in_any_active_range(self, settings, user):
        """A UUID absent from the user's active range(s) raises 'not found in range' (#450).

        The user has an active range but it does not contain the UUID, so the
        authored message stays 'Instance ... not found in range' (distinct from
        'No active range found', which means no active range exists at all).
        """
        from engine.services import get_rdp_connection_info

        settings.CLOUD_PROVIDER = "aws"
        instance = {
            "uuid": "present-rdp-uuid",
            "role": "victim",
            "os_type": "kali",
            "cloud_provider": "aws",
            "private_ip": "10.0.0.10",
            "rdp_password_secret_arn": "arn:aws:secretsmanager:us-east-2:1:secret:victim-rdp",
        }
        Range.objects.create(user=user, status=Range.Status.READY, provisioned_instances=[instance])
        with pytest.raises(ValueError, match="not found in range"):
            get_rdp_connection_info(user, "absent-rdp-uuid")

    def test_raises_not_ready_for_non_ready_range_resolved_by_uuid(self, settings, user):
        """If the range resolved by UUID is not READY, raises 'Range is not ready'."""
        from engine.services import get_rdp_connection_info

        settings.CLOUD_PROVIDER = "aws"
        instance = {
            "uuid": "provisioning-rdp-uuid",
            "role": "victim",
            "os_type": "kali",
            "cloud_provider": "aws",
            "private_ip": "10.0.0.10",
        }
        Range.objects.create(user=user, status=Range.Status.PROVISIONING, provisioned_instances=[instance])
        with pytest.raises(ValueError, match="not ready"):
            get_rdp_connection_info(user, "provisioning-rdp-uuid")
