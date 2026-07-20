"""State-to-portal endpoint mapping across GCP scenario compositions + revocation (#1349).

Issue #1349 requires tests that cover the state-to-portal endpoint mapping for
more than one scenario composition and that access revokes when the range is
destroyed. These drive the provider-agnostic portal resolvers
(``get_ssh_connection_info`` / ``get_rdp_connection_info``) against real GCP
``Range.provisioned_instances`` -- the same top-level shape
``engine/provisioner/state_helpers.py`` writes (``private_ip``,
``ssh_key_secret_arn``, ``rdp_password_secret_arn``, ``ssh_username``,
``os_type``, ``cloud_provider="gcp"``) -- so GCP user range access reaches
parity with AWS. The network path itself (portal/guacd -> range guests) is
authorized by the ``allow-platform-range-access-egress`` NetworkPolicy.
"""

import pytest
from django.contrib.auth import get_user_model

from engine.models import Range

from .conftest import SSH_KEY_PEM, boto3_secrets, make_secrets_client

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="range-1349@example.com", email="range-1349@example.com")


def _gcp_instance(
    uuid: str,
    os_type: str,
    ip: str,
    username: str,
    channels: list[str],
    *,
    rdp_secret: str | None = None,
) -> dict:
    """A GCP provisioned-instance record in the shape state_helpers writes.

    ``channels`` is the scenario-declared participant access binding the portal
    authorizes against (issue #1349) -- the closed realized target/channel
    binding, not mere credential presence.
    """
    instance = {
        "uuid": uuid,
        "role": "attacker" if os_type == "kali" else "victim",
        "os_type": os_type,
        "cloud_provider": "gcp",
        "private_ip": ip,
        "participant_access_channels": channels,
        "ssh_key_secret_arn": f"projects/test/secrets/{uuid}-ssh",
        "ssh_username": username,
    }
    if rdp_secret is not None:
        instance["rdp_password_secret_arn"] = rdp_secret
    return instance


def _range(user, instances: list[dict], *, status=Range.Status.READY) -> Range:
    return Range.objects.create(user=user, status=status, provisioned_instances=instances)


class TestLinuxOnlyComposition:
    """Composition A: kali attacker + ubuntu victim (SSH only; no Windows/RDP)."""

    def test_ssh_resolves_for_every_linux_member(self, settings, user):
        from engine.services import get_ssh_connection_info

        settings.CLOUD_PROVIDER = "aws"  # portal's active secrets store
        _range(
            user,
            [
                _gcp_instance("comp-a-kali", "kali", "10.50.1.10", "kali", ["ssh"]),
                _gcp_instance("comp-a-ubuntu", "ubuntu", "10.50.1.11", "ubuntu", ["ssh"]),
            ],
        )
        with boto3_secrets(make_secrets_client()):
            kali = get_ssh_connection_info(user, "comp-a-kali")
            ubuntu = get_ssh_connection_info(user, "comp-a-ubuntu")

        assert (kali["host"], kali["username"], kali["cloud_provider"]) == ("10.50.1.10", "kali", "gcp")
        assert kali["private_key"] == SSH_KEY_PEM
        assert (ubuntu["host"], ubuntu["username"]) == ("10.50.1.11", "ubuntu")

    def test_rdp_not_offered_for_linux_members(self, settings, user):
        # The Linux member declares only the ssh channel, so RDP is refused by the
        # closed realized access binding -- not merely because a credential is
        # absent.
        from engine.services import get_rdp_connection_info

        settings.CLOUD_PROVIDER = "aws"
        _range(user, [_gcp_instance("comp-a-ubuntu", "ubuntu", "10.50.1.11", "ubuntu", ["ssh"])])
        with pytest.raises(ValueError, match="rdp access is not a declared participant endpoint"):
            get_rdp_connection_info(user, "comp-a-ubuntu")


class TestWindowsMixedComposition:
    """Composition B: kali attacker + windows victim (SSH for Linux, RDP for Windows)."""

    def test_ssh_for_kali_and_rdp_for_windows(self, settings, user):
        from engine.services import get_rdp_connection_info, get_ssh_connection_info

        settings.CLOUD_PROVIDER = "aws"
        _range(
            user,
            [
                _gcp_instance("comp-b-kali", "kali", "10.50.2.10", "kali", ["ssh"]),
                _gcp_instance(
                    "comp-b-win",
                    "windows",
                    "10.50.2.20",
                    "Administrator",
                    ["ssh", "rdp"],
                    rdp_secret="projects/test/secrets/comp-b-win-rdp",
                ),
            ],
        )
        with boto3_secrets(make_secrets_client()):
            kali = get_ssh_connection_info(user, "comp-b-kali")
        assert kali["host"] == "10.50.2.10"

        with boto3_secrets(make_secrets_client(value="WIN-RDP-PW")):
            win = get_rdp_connection_info(user, "comp-b-win")
        assert (win["host"], win["rdp_username"], win["rdp_password"]) == ("10.50.2.20", "Administrator", "WIN-RDP-PW")


class TestDestroyRevocation:
    """Access revokes once the range leaves READY (destroy / participant removal)."""

    @pytest.mark.parametrize("status", [Range.Status.DESTROYING, Range.Status.DESTROYED, Range.Status.FAILED])
    def test_ssh_refused_when_range_not_ready(self, settings, user, status):
        from engine.services import get_ssh_connection_info

        settings.CLOUD_PROVIDER = "aws"
        _range(user, [_gcp_instance("revoked-kali", "kali", "10.50.3.10", "kali", ["ssh"])], status=status)
        with boto3_secrets(make_secrets_client()), pytest.raises(ValueError):
            get_ssh_connection_info(user, "revoked-kali")

    def test_rdp_refused_when_range_destroyed(self, settings, user):
        from engine.services import get_rdp_connection_info

        settings.CLOUD_PROVIDER = "aws"
        _range(
            user,
            [
                _gcp_instance(
                    "revoked-win",
                    "windows",
                    "10.50.3.20",
                    "Administrator",
                    ["ssh", "rdp"],
                    rdp_secret="projects/test/secrets/revoked-win-rdp",
                )
            ],
            status=Range.Status.DESTROYED,
        )
        with boto3_secrets(make_secrets_client(value="X")), pytest.raises(ValueError):
            get_rdp_connection_info(user, "revoked-win")


class TestClosedBindingIsTheAuthorizationSource:
    """Authorization derives from the closed realized target/channel binding,
    not credential presence (issue #1349 / codex review)."""

    def test_undeclared_channel_refused_despite_present_credential(self, settings, user):
        # The instance has an RDP password secret, but the scenario declared only
        # the ssh channel. RDP must be refused: credential presence is not
        # authorization.
        from engine.services import get_rdp_connection_info

        settings.CLOUD_PROVIDER = "aws"
        _range(
            user,
            [
                _gcp_instance(
                    "bind-win",
                    "windows",
                    "10.50.4.20",
                    "Administrator",
                    ["ssh"],  # rdp deliberately NOT declared
                    rdp_secret="projects/test/secrets/bind-win-rdp",
                )
            ],
        )
        with (
            boto3_secrets(make_secrets_client(value="PW")),
            pytest.raises(ValueError, match="rdp access is not a declared participant endpoint"),
        ):
            get_rdp_connection_info(user, "bind-win")

    def test_empty_binding_refuses_all_channels(self, settings, user):
        # A member the scenario exposed to no participant channel is unreachable,
        # even though it has an SSH key secret.
        from engine.services import get_ssh_connection_info

        settings.CLOUD_PROVIDER = "aws"
        _range(user, [_gcp_instance("bind-none", "ubuntu", "10.50.4.30", "ubuntu", [])])
        with (
            boto3_secrets(make_secrets_client()),
            pytest.raises(ValueError, match="ssh access is not a declared participant endpoint"),
        ):
            get_ssh_connection_info(user, "bind-none")

    def test_absent_binding_preserves_aws_credential_presence_gate(self, settings, user):
        # AWS/legacy instances carry no closed binding (no participant_access_channels
        # key); their existing ownership/READY/credential gate is unchanged.
        from engine.services import get_ssh_connection_info

        settings.CLOUD_PROVIDER = "aws"
        aws_instance = {
            "uuid": "aws-legacy",
            "role": "attacker",
            "os_type": "kali",
            "cloud_provider": "aws",
            "private_ip": "10.90.0.10",
            "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:1:secret:shifter/range/aws-legacy-ssh",
            "ssh_username": "kali",
        }
        _range(user, [aws_instance])
        with boto3_secrets(make_secrets_client()):
            result = get_ssh_connection_info(user, "aws-legacy")
        assert result["host"] == "10.90.0.10"
        assert result["username"] == "kali"
