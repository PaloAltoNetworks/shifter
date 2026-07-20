"""Behavior tests for generation-bound OpenVPN profile resolution."""

from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model

from engine.models import Instance, Range, Request
from shared.enums import RequestType

from .conftest import boto3_secrets, make_secrets_client

pytestmark = pytest.mark.django_db

User = get_user_model()
PROFILE = (
    "client\n"
    "dev tun\n"
    "proto udp\n"
    "remote vpn.example.test 1194\n"
    "nobind\n"
    "persist-key\n"
    "persist-tun\n"
    "remote-cert-tls server\n"
    "auth-nocache\n"
    "verb 3\n"
    "<ca>\nTEST-CA\n</ca>\n"
    "<cert>\nTEST-CERT\n</cert>\n"
    "<key>\nTEST-CLIENT-KEY\n</key>\n"
    "<tls-crypt>\nTEST-TLS-CRYPT\n</tls-crypt>\n"
)


def _range(user, *, status=Range.Status.READY, owner_user_id=None, ready=True):
    request = Request.objects.create(request_id=uuid4(), request_type=RequestType.RANGE.value, user=user)
    target_ref = uuid4()
    Instance.objects.create(
        uuid=target_ref,
        request=request,
        role=Instance.Role.ATTACKER,
        os_type=Instance.OSType.KALI,
        status=Range.Status.READY,
    )
    binding = {
        "version": "openvpn-binding-v1",
        "channel": "openvpn",
        "generation": str(request.request_id),
        "owner_user_id": owner_user_id or user.id,
        "target_ref": str(target_ref),
        "endpoint": "vpn.example.test",
        "port": 1194,
        "profile_version": "openvpn-profile-v1",
        "secret_ref": "arn:aws:secretsmanager:eu-central-1:123:secret:range-vpn",
        "ready": ready,
    }
    return Range.objects.create(user=user, request=request, status=status, vpn_access_binding=binding)


def test_resolves_and_validates_the_profile_after_ready_owner_checks(settings):
    from engine.services import get_openvpn_profile

    settings.CLOUD_PROVIDER = "aws"
    user = User.objects.create_user(username="vpn-owner@example.test")
    range_obj = _range(user)
    client = make_secrets_client(PROFILE)

    with boto3_secrets(client):
        result = get_openvpn_profile(user, range_obj.request.request_id)

    assert result.content == PROFILE.encode()
    assert result.profile_version == "openvpn-profile-v1"
    client.get_secret_value.assert_called_once_with(SecretId=range_obj.vpn_access_binding["secret_ref"])


def test_rejects_a_binding_owned_by_a_previous_participant(settings):
    from engine.services import VpnProfileConflict, get_openvpn_profile

    settings.CLOUD_PROVIDER = "aws"
    user = User.objects.create_user(username="vpn-new-owner@example.test")
    range_obj = _range(user, owner_user_id=user.id + 100)

    with pytest.raises(VpnProfileConflict, match="current owner"):
        get_openvpn_profile(user, range_obj.request.request_id)


def test_rejects_a_different_authenticated_user_before_secret_access(settings):
    """The Engine ownership query is an independent cross-tenant boundary."""
    from engine.services import VpnProfileNotFound, get_openvpn_profile, has_openvpn_profile

    settings.CLOUD_PROVIDER = "aws"
    owner = User.objects.create_user(username="vpn-owner-boundary@example.test")
    other_user = User.objects.create_user(username="vpn-other-boundary@example.test")
    range_obj = _range(owner)
    client = make_secrets_client(PROFILE)

    with boto3_secrets(client):
        assert has_openvpn_profile(other_user, range_obj.request.request_id) is False
        with pytest.raises(VpnProfileNotFound, match="No owned range"):
            get_openvpn_profile(other_user, range_obj.request.request_id)

    client.get_secret_value.assert_not_called()


@pytest.mark.parametrize("status", [Range.Status.PROVISIONING, Range.Status.PAUSED, Range.Status.DESTROYING])
def test_rejects_profile_delivery_when_the_range_is_not_ready(settings, status):
    from engine.services import VpnProfileConflict, get_openvpn_profile

    settings.CLOUD_PROVIDER = "aws"
    user = User.objects.create_user(username=f"vpn-{status}@example.test")
    range_obj = _range(user, status=status)

    with pytest.raises(VpnProfileConflict, match="not ready"):
        get_openvpn_profile(user, range_obj.request.request_id)


def test_capability_projection_is_false_for_a_missing_or_stale_binding():
    from engine.services import has_openvpn_profile

    user = User.objects.create_user(username="vpn-capability@example.test")
    no_binding_request = Request.objects.create(request_id=uuid4(), request_type=RequestType.RANGE.value, user=user)
    no_binding = Range.objects.create(user=user, request=no_binding_request, status=Range.Status.READY)
    stale = _range(user, owner_user_id=user.id + 1)

    assert has_openvpn_profile(user, no_binding.request.request_id) is False
    assert has_openvpn_profile(user, stale.request.request_id) is False


def test_rejects_a_binding_from_a_superseded_request_generation(settings):
    from engine.services import VpnProfileConflict, get_openvpn_profile

    settings.CLOUD_PROVIDER = "aws"
    user = User.objects.create_user(username="vpn-generation@example.test")
    range_obj = _range(user)
    range_obj.vpn_access_binding["generation"] = str(uuid4())
    range_obj.save(update_fields=["vpn_access_binding"])

    with pytest.raises(VpnProfileConflict, match="generation"):
        get_openvpn_profile(user, range_obj.request.request_id)


def test_rejects_a_binding_for_a_non_member_target(settings):
    from engine.services import VpnProfileConflict, get_openvpn_profile

    settings.CLOUD_PROVIDER = "aws"
    user = User.objects.create_user(username="vpn-target@example.test")
    range_obj = _range(user)
    range_obj.vpn_access_binding["target_ref"] = str(uuid4())
    range_obj.save(update_fields=["vpn_access_binding"])

    with pytest.raises(VpnProfileConflict, match="target"):
        get_openvpn_profile(user, range_obj.request.request_id)
