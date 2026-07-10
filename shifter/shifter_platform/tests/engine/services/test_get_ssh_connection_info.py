"""Behavior tests for get_ssh_connection_info() in engine/services.

Driven against a real active ``Range`` (resolved via ``get_active_for_user``,
consistent with ``get_rdp_connection_info``) with the SSH key fetched over the
``boto3`` Secrets Manager boundary, instead of patching ``Range.objects`` /
``get_ssh_key``.
"""

import pytest
from django.contrib.auth import get_user_model

from engine.models import Range

from .conftest import SSH_KEY_PEM, boto3_secrets, make_secrets_client

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="engine-sshinfo@example.com", email="engine-sshinfo@example.com")


def _active_range(user, instance, *, status=Range.Status.READY):
    return Range.objects.create(user=user, status=status, provisioned_instances=[instance])


class TestGetSSHConnectionInfo:
    def test_returns_gcp_connection_info_from_provider_metadata_fallbacks(self, settings, user):
        from engine.services import get_ssh_connection_info

        settings.CLOUD_PROVIDER = "aws"  # active secrets store is the portal's AWS store
        instance = {
            "uuid": "gcp-instance-uuid-123",
            "role": "attacker",
            "os_type": "kali",
            "cloud_provider": "gcp",
            "provider_metadata": {
                "gcp": {
                    "instance_name": "shifter-range-vm-1",
                    "private_ip": "10.50.1.10",
                    "ssh_key_secret_id": "projects/test/secrets/range-ssh-key",
                    "ssh_username": "kali",
                }
            },
        }
        _active_range(user, instance)
        with boto3_secrets(make_secrets_client()):
            result = get_ssh_connection_info(user, "gcp-instance-uuid-123")

        assert result["host"] == "10.50.1.10"
        assert result["private_ip"] == "10.50.1.10"
        assert result["username"] == "kali"
        assert result["connection_name"] == "shifter-range-vm-1"
        assert result["cloud_provider"] == "gcp"
        assert result["private_key"] == SSH_KEY_PEM

    def test_returns_connection_info_from_gdc_style_provider_metadata(self, settings, user):
        from engine.services import get_ssh_connection_info

        settings.CLOUD_PROVIDER = "aws"
        ref = "projects/test/secrets/vmrt-ssh-key"
        instance = {
            "uuid": "gdc-instance-uuid-123",
            "role": "victim",
            "os_type": "windows",
            "cloud_provider": "gcp",
            "provider_metadata": {
                "gdc": {
                    "vm_name": "range-42-win-target",
                    "ip": "10.200.0.110",
                    "ssh_secret_ref": ref,
                    "username": "Administrator",
                }
            },
        }
        _active_range(user, instance)
        client = make_secrets_client()
        with boto3_secrets(client):
            result = get_ssh_connection_info(user, "gdc-instance-uuid-123")

        client.get_secret_value.assert_called_once_with(SecretId=ref)
        assert result["host"] == "10.200.0.110"
        assert result["private_ip"] == "10.200.0.110"
        assert result["username"] == "Administrator"
        assert result["connection_name"] == "range-42-win-target"
        assert result["cloud_provider"] == "gcp"

    def test_raises_when_instance_has_no_resolvable_secret_reference(self, user):
        from engine.services import get_ssh_connection_info

        instance = {
            "uuid": "missing-secret-uuid",
            "role": "victim",
            "os_type": "ubuntu",
            "private_ip": "10.50.1.20",
            "cloud_provider": "gcp",
            "provider_metadata": {"gcp": {"instance_name": "victim-01"}},
        }
        _active_range(user, instance)
        with pytest.raises(ValueError, match="SSH key"):
            get_ssh_connection_info(user, "missing-secret-uuid")

    def test_raises_when_no_active_range(self, user):
        from engine.services import get_ssh_connection_info

        # No active range exists for the user.
        with pytest.raises(ValueError, match="No active range"):
            get_ssh_connection_info(user, "any-uuid")

    def test_raises_when_range_not_ready(self, user):
        from engine.services import get_ssh_connection_info

        instance = {"uuid": "u-1", "role": "attacker", "os_type": "kali", "private_ip": "10.0.0.1"}
        _active_range(user, instance, status=Range.Status.PROVISIONING)
        with pytest.raises(ValueError, match="not ready"):
            get_ssh_connection_info(user, "u-1")

    def test_raises_when_instance_uuid_not_in_any_active_range(self, user):
        """A UUID absent from the user's active range(s) raises 'not found in range' (#450).

        resolve_active_for_instance resolves the range from the UUID. When the user
        has an active range but none contains the UUID, the authored message stays
        'Instance ... not found in range' (distinct from 'No active range found',
        which means the user has no active range at all).
        """
        from engine.services import get_ssh_connection_info

        instance = {"uuid": "present", "role": "attacker", "os_type": "kali", "private_ip": "10.0.0.1"}
        _active_range(user, instance)
        with pytest.raises(ValueError, match="not found in range"):
            get_ssh_connection_info(user, "absent-uuid")


class TestGetSSHConnectionInfoMultiRange:
    """get_ssh_connection_info resolves the correct range when a user holds two (#450)."""

    def test_resolves_correct_range_with_two_active_ranges(self, settings, user):
        """With MC and CTF ranges active, the UUID selects the right range."""
        from engine.services import get_ssh_connection_info

        settings.CLOUD_PROVIDER = "aws"
        ssh_secret_ref = "projects/test/secrets/range-ssh-key"
        mc_instance = {
            "uuid": "mc-ssh-uuid",
            "role": "attacker",
            "os_type": "kali",
            "cloud_provider": "gcp",
            "provider_metadata": {
                "gcp": {
                    "instance_name": "mc-attacker",
                    "private_ip": "10.0.0.1",
                    "ssh_key_secret_id": ssh_secret_ref,
                    "ssh_username": "kali",
                }
            },
        }
        ctf_instance = {
            "uuid": "ctf-ssh-uuid",
            "role": "attacker",
            "os_type": "kali",
            "cloud_provider": "gcp",
            "provider_metadata": {
                "gcp": {
                    "instance_name": "ctf-attacker",
                    "private_ip": "10.0.0.2",
                    "ssh_key_secret_id": ssh_secret_ref,
                    "ssh_username": "kali",
                }
            },
        }
        Range.objects.create(user=user, status=Range.Status.READY, provisioned_instances=[mc_instance])
        Range.objects.create(user=user, status=Range.Status.READY, provisioned_instances=[ctf_instance])

        with boto3_secrets(make_secrets_client()):
            result = get_ssh_connection_info(user, "ctf-ssh-uuid")

        assert result["host"] == "10.0.0.2"
        assert result["connection_name"] == "ctf-attacker"

    def test_raises_not_ready_for_non_ready_range_resolved_by_uuid(self, user):
        """If the range resolved by UUID is not READY, raises 'Range is not ready'."""
        from engine.services import get_ssh_connection_info

        instance = {
            "uuid": "prov-ssh-uuid",
            "role": "attacker",
            "os_type": "kali",
            "private_ip": "10.0.0.1",
        }
        _active_range(user, instance, status=Range.Status.PROVISIONING)
        with pytest.raises(ValueError, match="not ready"):
            get_ssh_connection_info(user, "prov-ssh-uuid")
