"""Portal endpoint mapping for RAES-native ranges (#1710).

The #1349 portal resolvers are provenance-agnostic: they authorize on the closed
``participant_access_channels`` binding. What RAES-native ranges add is the
per-channel login (``participant_access_usernames``), because a scenario may
broker SSH and RDP as *different* authored accounts and the instance-wide
``ssh_username`` on that path is the reserved provisioner-management user, which
must never be handed to a participant.
"""

import pytest
from django.contrib.auth import get_user_model

from engine.models import Range

from .conftest import SSH_KEY_PEM, boto3_secrets, make_secrets_client

_WORKSPACE_ID = 1

pytestmark = pytest.mark.django_db

User = get_user_model()

#: The reserved guest login the RAES provisioner injects for its own management
#: reachability (``raes_gcp_plan._DEFAULT_SSH_USERNAME``). It is never brokered.
_MANAGEMENT_USER = "raes"


@pytest.fixture
def user(db):
    return User.objects.create_user(username="range-1710@example.com", email="range-1710@example.com")


def _raes_instance(uuid, os_type, ip, channels, usernames, *, rdp_secret=None):
    """A RAES-native provisioned-instance record as the applier writes it."""
    instance = {
        "uuid": uuid,
        "role": "raes-node",
        "os_type": os_type,
        "cloud_provider": "gcp",
        "private_ip": ip,
        "participant_access_channels": channels,
        "participant_access_usernames": usernames,
        "ssh_key_secret_arn": f"projects/test/secrets/{uuid}-ssh",
        # The management seat the provisioner injected; not a participant login.
        "ssh_username": _MANAGEMENT_USER,
    }
    if rdp_secret is not None:
        instance["rdp_password_secret_arn"] = rdp_secret
    return instance


def _range(user, instances, *, status=Range.Status.READY) -> Range:
    return Range.objects.create(workspace_id=_WORKSPACE_ID, user=user, status=status, provisioned_instances=instances)


class TestPerChannelLogin:
    def test_ssh_uses_the_declared_account_not_the_management_user(self, settings, user):
        from engine.services import get_ssh_connection_info

        settings.CLOUD_PROVIDER = "aws"
        _range(user, [_raes_instance("raes-web", "linux", "10.60.0.10", ["ssh"], {"ssh": "analyst"})])
        with boto3_secrets(make_secrets_client()):
            info = get_ssh_connection_info(user, "raes-web")

        assert info["username"] == "analyst"
        assert info["username"] != _MANAGEMENT_USER
        assert info["private_key"] == SSH_KEY_PEM

    def test_ssh_and_rdp_resolve_their_own_accounts(self, settings, user):
        """A shared ssh_username would conflate two different authored accounts."""
        from engine.services import get_rdp_connection_info, get_ssh_connection_info

        settings.CLOUD_PROVIDER = "aws"
        _range(
            user,
            [
                _raes_instance(
                    "raes-win",
                    "windows",
                    "10.60.0.20",
                    ["ssh", "rdp"],
                    {"ssh": "sshuser", "rdp": "rdpuser"},
                    rdp_secret="projects/test/secrets/raes-win-rdp",
                )
            ],
        )
        with boto3_secrets(make_secrets_client()):
            ssh = get_ssh_connection_info(user, "raes-win")
        with boto3_secrets(make_secrets_client(value="WIN-RDP-PW")):
            rdp = get_rdp_connection_info(user, "raes-win")

        assert ssh["username"] == "sshuser"
        assert rdp["rdp_username"] == "rdpuser"


class TestClosedBindingStillGoverns:
    def test_undeclared_channel_is_refused(self, settings, user):
        from engine.services import get_rdp_connection_info

        settings.CLOUD_PROVIDER = "aws"
        _range(user, [_raes_instance("raes-lin", "windows", "10.60.0.30", ["ssh"], {"ssh": "analyst"})])
        with pytest.raises(ValueError, match="rdp access is not a declared participant endpoint"):
            get_rdp_connection_info(user, "raes-lin")

    def test_a_member_with_no_declared_access_is_refused(self, settings, user):
        """Provisioned is not participant-reachable; the binding is the gate."""
        from engine.services import get_ssh_connection_info

        settings.CLOUD_PROVIDER = "aws"
        _range(user, [_raes_instance("raes-quiet", "linux", "10.60.0.40", [], {})])
        with pytest.raises(ValueError, match="ssh access is not a declared participant endpoint"):
            get_ssh_connection_info(user, "raes-quiet")

    def test_a_non_ready_range_is_refused(self, settings, user):
        from engine.services import get_ssh_connection_info

        settings.CLOUD_PROVIDER = "aws"
        _range(
            user,
            [_raes_instance("raes-web", "linux", "10.60.0.10", ["ssh"], {"ssh": "analyst"})],
            status=Range.Status.PROVISIONING,
        )
        with pytest.raises(ValueError, match="not ready"):
            get_ssh_connection_info(user, "raes-web")


class TestCyberscriptPathUnchanged:
    def test_an_instance_without_per_channel_logins_keeps_its_seat_user(self, settings, user):
        """The cyberscript/AWS single-seat behaviour must not regress."""
        from engine.services import get_ssh_connection_info

        settings.CLOUD_PROVIDER = "aws"
        legacy = {
            "uuid": "legacy-kali",
            "role": "attacker",
            "os_type": "kali",
            "cloud_provider": "gcp",
            "private_ip": "10.50.9.10",
            "participant_access_channels": ["ssh"],
            "ssh_key_secret_arn": "projects/test/secrets/legacy-kali-ssh",
            "ssh_username": "kali",
        }
        _range(user, [legacy])
        with boto3_secrets(make_secrets_client()):
            info = get_ssh_connection_info(user, "legacy-kali")

        assert info["username"] == "kali"
