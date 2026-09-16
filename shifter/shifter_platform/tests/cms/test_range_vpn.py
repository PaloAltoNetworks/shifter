"""CMS ownership/provenance checks for CTF OpenVPN profile access."""

from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model

from cms.models import RangeInstance
from cms.models import Request as CMSRequest
from engine.models import Instance, Range
from engine.models import Request as EngineRequest
from shared.enums import RangeSource, RequestType, ResourceStatus
from tests.engine.services.conftest import boto3_secrets, make_secrets_client

pytestmark = pytest.mark.django_db

User = get_user_model()
PROFILE = (
    "client\ndev tun\nproto udp\nremote vpn.example.test 1194\nnobind\npersist-key\npersist-tun\n"
    "remote-cert-tls server\nauth-nocache\nverb 3\n<ca>\nCA\n</ca>\n<cert>\nCERT\n</cert>\n"
    "<key>\nKEY\n</key>\n<tls-crypt>\nTLS\n</tls-crypt>\n"
)


def _range_pair(user, *, source=RangeSource.CTF, cms_status=ResourceStatus.READY):
    from workspaces.services import resolve_personal_workspace

    workspace_id = resolve_personal_workspace(user).workspace_id
    request_id = uuid4()
    cms_request = CMSRequest.objects.create(
        workspace_id=workspace_id, request_id=request_id, request_type=RequestType.RANGE.value, user=user
    )
    cms_range = RangeInstance.objects.create(
        workspace_id=workspace_id,
        request=cms_request,
        scenario_id="basic",
        user_id=user.id,
        status=cms_status.value,
        range_source=source.value,
    )
    engine_request = EngineRequest.objects.create(
        request_id=request_id,
        request_type=RequestType.RANGE.value,
        user=user,
    )
    target_ref = uuid4()
    Instance.objects.create(
        uuid=target_ref,
        request=engine_request,
        role=Instance.Role.ATTACKER,
        os_type=Instance.OSType.KALI,
        status=Range.Status.READY,
    )
    engine_range = Range.objects.create(
        workspace_id=workspace_id,
        request=engine_request,
        user=user,
        status=Range.Status.READY,
        vpn_access_binding={
            "version": "openvpn-binding-v1",
            "channel": "openvpn",
            "generation": str(request_id),
            "owner_user_id": user.id,
            "target_ref": str(target_ref),
            "endpoint": "vpn.example.test",
            "port": 1194,
            "profile_version": "openvpn-profile-v1",
            "secret_ref": "arn:aws:secretsmanager:eu-central-1:123:secret:range-vpn",
            "ready": True,
        },
    )
    return cms_range, engine_range


def test_ctf_profile_access_validates_cms_ownership_and_delegates_to_engine(settings):
    from cms.services import get_ctf_openvpn_profile

    settings.CLOUD_PROVIDER = "aws"
    user = User.objects.create_user(username="cms-vpn-owner@example.test")
    cms_range, _engine_range = _range_pair(user)

    with boto3_secrets(make_secrets_client(PROFILE)):
        result = get_ctf_openvpn_profile(user, cms_range.pk)

    assert result.content == PROFILE.encode()


def test_membership_removal_revokes_vpn_before_secret_resolution(settings):
    from cms.services import OpenVpnProfileNotFound, get_ctf_openvpn_profile
    from workspaces.models import WorkspaceMembership

    settings.CLOUD_PROVIDER = "aws"
    user = User.objects.create_user(username="cms-vpn-revoked@example.test")
    cms_range, _engine_range = _range_pair(user)
    WorkspaceMembership.objects.filter(user=user).delete()

    with pytest.raises(OpenVpnProfileNotFound, match="not found"):
        get_ctf_openvpn_profile(user, cms_range.pk)


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong_owner",
        "wrong_source",
        "not_ready",
    ],
)
def test_ctf_profile_access_fails_closed_before_secret_resolution(settings, mutation):
    from cms.exceptions import CMSError
    from cms.services import get_ctf_openvpn_profile

    settings.CLOUD_PROVIDER = "aws"
    user = User.objects.create_user(username=f"cms-vpn-{mutation}@example.test")
    other = User.objects.create_user(username=f"cms-vpn-{mutation}-other@example.test")
    cms_range, _engine_range = _range_pair(user)
    actor = user
    if mutation == "wrong_owner":
        actor = other
    elif mutation == "wrong_source":
        cms_range.range_source = RangeSource.MISSION_CONTROL.value
        cms_range.save(update_fields=["range_source"])
    else:
        cms_range.status = ResourceStatus.PAUSED.value
        cms_range.save(update_fields=["status"])

    client = make_secrets_client(PROFILE)
    with boto3_secrets(client), pytest.raises(CMSError):
        get_ctf_openvpn_profile(actor, cms_range.pk)
    client.get_secret_value.assert_not_called()


def test_ctf_capability_projection_hides_non_ctf_and_stale_bindings():
    from cms.services import has_ctf_openvpn_profile

    user = User.objects.create_user(username="cms-vpn-capability@example.test")
    ctf_range, engine_range = _range_pair(user)
    mc_range, _mc_engine_range = _range_pair(user, source=RangeSource.MISSION_CONTROL)

    assert has_ctf_openvpn_profile(user, ctf_range.pk) is True
    assert has_ctf_openvpn_profile(user, mc_range.pk) is False
    engine_range.vpn_access_binding["owner_user_id"] = user.id + 1
    engine_range.save(update_fields=["vpn_access_binding"])
    assert has_ctf_openvpn_profile(user, ctf_range.pk) is False


def test_profile_access_rejects_unsaved_users_and_missing_requests():
    from cms.exceptions import CMSError
    from cms.services import get_mission_control_openvpn_profile

    unsaved_user = User()
    with pytest.raises(CMSError):
        get_mission_control_openvpn_profile(unsaved_user)

    user = User.objects.create_user(username="cms-vpn-missing-request@example.test")
    from workspaces.services import resolve_personal_workspace

    RangeInstance.objects.create(
        workspace_id=resolve_personal_workspace(user).workspace_id,
        request=None,
        scenario_id="basic",
        user_id=user.id,
        status=ResourceStatus.READY.value,
        range_source=RangeSource.MISSION_CONTROL.value,
    )
    with pytest.raises(CMSError):
        get_mission_control_openvpn_profile(user)


def test_profile_access_rejects_a_binding_that_is_not_ready():
    from cms.exceptions import CMSError
    from cms.services import get_ctf_openvpn_profile

    user = User.objects.create_user(username="cms-vpn-binding-not-ready@example.test")
    cms_range, engine_range = _range_pair(user)
    engine_range.vpn_access_binding["ready"] = False
    engine_range.save(update_fields=["vpn_access_binding"])

    with pytest.raises(CMSError):
        get_ctf_openvpn_profile(user, cms_range.pk)


def test_profile_access_rejects_invalid_secret_material(settings):
    from cms.exceptions import CMSError
    from cms.services import get_ctf_openvpn_profile

    settings.CLOUD_PROVIDER = "aws"
    user = User.objects.create_user(username="cms-vpn-invalid-profile@example.test")
    cms_range, _engine_range = _range_pair(user)

    with boto3_secrets(make_secrets_client("not-an-openvpn-profile")), pytest.raises(CMSError):
        get_ctf_openvpn_profile(user, cms_range.pk)


def test_profile_helpers_fail_closed_if_a_loaded_range_loses_its_request():
    from types import SimpleNamespace

    from cms.services._range_vpn import OpenVpnProfileUnavailable, _has_profile, _resolve_profile

    user = User.objects.create_user(username="cms-vpn-request-race@example.test")
    instance = SimpleNamespace(request=None)

    assert _has_profile(user, instance) is False
    with pytest.raises(OpenVpnProfileUnavailable):
        _resolve_profile(user, instance)
