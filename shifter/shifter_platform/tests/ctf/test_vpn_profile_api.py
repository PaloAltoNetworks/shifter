"""DRF security and response-contract tests for participant VPN delivery."""

from uuid import uuid4

import pytest
from django.core.cache import caches
from rest_framework.test import APIClient

from cms.models import RangeInstance
from cms.models import Request as CmsRequest
from engine.models import Instance, Range
from engine.models import Request as EngineRequest
from management.services import set_active_ctf_event
from shared.api_tokens import scopes
from shared.api_tokens.models import ApiToken
from shared.audit import AuditAction, AuditEntityType
from shared.enums import RangeSource, RequestType, ResourceStatus
from shared.models import AuditLog
from tests.engine.services.conftest import boto3_secrets, make_secrets_client

pytestmark = pytest.mark.django_db

URL = "/api/v1/ctf/range/vpn-profile/"
STATUS_URL = "/api/v1/ctf/range/status/"
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


@pytest.fixture(autouse=True)
def _clear_vpn_rate_limit_cache():
    cache = caches["launch_rate_limit"]
    cache.clear()
    yield
    cache.clear()


def _token(user, *granted_scopes: str) -> str:
    _token_obj, raw = ApiToken.create_token(name="ctf-vpn", created_by=user, scopes=list(granted_scopes))
    return raw


def _active_range_participant(participant_user, ctf_participant):
    from workspaces.services import resolve_personal_workspace

    workspace_id = resolve_personal_workspace(participant_user).workspace_id
    set_active_ctf_event(participant_user, ctf_participant.event_id)
    request_id = uuid4()
    cms_request = CmsRequest.objects.create(
        workspace_id=workspace_id,
        request_id=request_id,
        request_type=RequestType.RANGE.value,
        user=participant_user,
    )
    cms_range = RangeInstance.objects.create(
        workspace_id=workspace_id,
        request=cms_request,
        scenario_id="basic",
        user_id=participant_user.id,
        status=ResourceStatus.READY.value,
        range_source=RangeSource.CTF.value,
    )
    engine_request = EngineRequest.objects.create(
        request_id=request_id,
        request_type=RequestType.RANGE.value,
        user=participant_user,
    )
    target_ref = uuid4()
    Instance.objects.create(
        uuid=target_ref,
        request=engine_request,
        role=Instance.Role.ATTACKER,
        os_type=Instance.OSType.KALI,
        status=Range.Status.READY,
    )
    Range.objects.create(
        workspace_id=workspace_id,
        request=engine_request,
        user=participant_user,
        status=Range.Status.READY,
        vpn_access_binding={
            "version": "openvpn-binding-v1",
            "channel": "openvpn",
            "generation": str(request_id),
            "owner_user_id": participant_user.id,
            "target_ref": str(target_ref),
            "endpoint": "vpn.example.test",
            "port": 1194,
            "profile_version": "openvpn-profile-v1",
            "secret_ref": f"arn:aws:secretsmanager:eu-central-1:123:secret:range-vpn-{request_id}",
            "ready": True,
        },
    )
    ctf_participant.range_instance_id = cms_range.pk
    ctf_participant.range_status = "ready"
    ctf_participant.save(update_fields=["range_instance_id", "range_status", "updated_at"])
    return cms_range


def test_exact_scope_token_downloads_a_no_store_profile(settings, participant_user, ctf_participant):
    settings.CLOUD_PROVIDER = "aws"
    cms_range = _active_range_participant(participant_user, ctf_participant)
    raw = _token(participant_user, scopes.CTF_VPN_PROFILE_READ)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")

    with boto3_secrets(make_secrets_client(PROFILE)):
        response = client.post(URL)

    assert response.status_code == 200
    assert response.content == PROFILE.encode()
    assert response["Content-Type"] == "application/x-openvpn-profile"
    assert response["Content-Disposition"] == 'attachment; filename="shifter-ctf-range.ovpn"'
    assert response["Cache-Control"] == "private, no-store"
    assert "ETag" not in response
    assert "Cookie" in response["Vary"]
    audit = AuditLog.objects.get(
        entity_type=AuditEntityType.CREDENTIAL,
        entity_id=cms_range.pk,
        action=AuditAction.DOWNLOAD,
    )
    assert audit.actor_id == participant_user.id
    assert audit.new_state["participant_id"] == str(ctf_participant.pk)
    assert audit.new_state["channel"] == "openvpn"


def test_existing_play_scope_does_not_grant_private_key_delivery(participant_user, ctf_participant):
    _active_range_participant(participant_user, ctf_participant)
    raw = _token(participant_user, scopes.CTF_PLAY_READ)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")

    response = client.post(URL)

    assert response.status_code == 403


def test_participant_without_an_active_range_gets_non_enumerating_not_found(participant_user, ctf_participant):
    set_active_ctf_event(participant_user, ctf_participant.event_id)
    raw = _token(participant_user, scopes.CTF_VPN_PROFILE_READ)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")

    response = client.post(URL)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_non_ctf_user_is_rejected(standard_user):
    raw = _token(standard_user, scopes.CTF_VPN_PROFILE_READ)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")

    response = client.post(URL)

    assert response.status_code == 403


def test_session_post_requires_csrf(participant_user, ctf_participant):
    _active_range_participant(participant_user, ctf_participant)
    client = APIClient(enforce_csrf_checks=True)
    client.force_login(participant_user)

    response = client.post(URL)

    assert response.status_code == 403


def test_endpoint_rejects_a_request_body(participant_user, ctf_participant):
    _active_range_participant(participant_user, ctf_participant)
    raw = _token(participant_user, scopes.CTF_VPN_PROFILE_READ)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")

    response = client.post(URL, {"range_id": 42}, format="json")

    assert response.status_code == 400


def test_rate_limit_failure_returns_retry_after_without_resolving_profile(settings, participant_user, ctf_participant):
    settings.CLOUD_PROVIDER = "aws"
    _active_range_participant(participant_user, ctf_participant)
    raw = _token(participant_user, scopes.CTF_VPN_PROFILE_READ)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    caches["launch_rate_limit"].set(f"credential-delivery:{participant_user.pk}", 50, 3600)
    secrets_client = make_secrets_client(PROFILE)

    with boto3_secrets(secrets_client):
        response = client.post(URL)

    assert response.status_code == 429
    assert response["Retry-After"] == "3600"
    secrets_client.get_secret_value.assert_not_called()


def test_rate_limit_backend_failure_fails_closed(monkeypatch, participant_user, ctf_participant):
    _active_range_participant(participant_user, ctf_participant)
    raw = _token(participant_user, scopes.CTF_VPN_PROFILE_READ)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")

    def fail_add(*args, **kwargs):
        raise RuntimeError("cache unavailable")

    monkeypatch.setattr(caches["launch_rate_limit"], "add", fail_add)

    response = client.post(URL)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "vpn_profile_unavailable"


def test_range_status_projects_vpn_availability_without_delivering_a_secret(participant_user, ctf_participant):
    _active_range_participant(participant_user, ctf_participant)
    raw = _token(participant_user, scopes.CTF_PLAY_READ)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")

    response = client.get(STATUS_URL)

    assert response.status_code == 200
    assert response.json()["status"] == ResourceStatus.READY.value
    assert response.json()["vpn_profile_available"] is True


def test_ctf_bridge_reads_the_persisted_range_spec_without_crossing_layers(participant_user, ctf_participant):
    from ctf.bridges import cms_get_range_spec

    cms_range = _active_range_participant(participant_user, ctf_participant)
    expected = {"instances": [{"uuid": "participant-seat", "role": "attacker"}]}
    cms_range.range_spec = expected
    cms_range.save(update_fields=["range_spec"])

    assert cms_get_range_spec(cms_range.pk) == expected


def test_missing_engine_range_is_non_enumerating(participant_user, ctf_participant):
    _active_range_participant(participant_user, ctf_participant)
    Range.objects.filter(user=participant_user).delete()
    raw = _token(participant_user, scopes.CTF_VPN_PROFILE_READ)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")

    response = client.post(URL)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_non_ready_engine_range_returns_conflict(participant_user, ctf_participant):
    _active_range_participant(participant_user, ctf_participant)
    Range.objects.filter(user=participant_user).update(status=Range.Status.PROVISIONING)
    raw = _token(participant_user, scopes.CTF_VPN_PROFILE_READ)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")

    response = client.post(URL)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "vpn_not_ready"


def test_invalid_engine_binding_returns_unavailable(participant_user, ctf_participant):
    _active_range_participant(participant_user, ctf_participant)
    Range.objects.filter(user=participant_user).update(vpn_access_binding={})
    raw = _token(participant_user, scopes.CTF_VPN_PROFILE_READ)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")

    response = client.post(URL)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "vpn_profile_unavailable"
