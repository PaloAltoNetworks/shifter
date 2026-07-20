"""Mission Control OpenVPN delivery security and response-contract tests (#1696)."""

from datetime import timedelta
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import caches
from django.utils import timezone
from rest_framework.test import APIClient

from cms.models import RangeInstance
from cms.models import Request as CmsRequest
from engine.models import Instance, Range
from engine.models import Request as EngineRequest
from risk_register.models import AuditLog
from shared.api_tokens import scopes
from shared.api_tokens.models import ApiToken
from shared.audit import AuditAction, AuditEntityType
from shared.enums import RangeSource, RequestType, ResourceStatus
from tests.engine.services.conftest import boto3_secrets, make_secrets_client

pytestmark = pytest.mark.django_db
User = get_user_model()

URL = "/api/v1/mission-control/range/vpn-profile/"
PROFILE = (
    "client\ndev tun\nproto udp\nremote vpn.example.test 1194\nnobind\npersist-key\npersist-tun\n"
    "remote-cert-tls server\nauth-nocache\nverb 3\n<ca>\nCA\n</ca>\n<cert>\nCERT\n</cert>\n"
    "<key>\nKEY\n</key>\n<tls-crypt>\nTLS\n</tls-crypt>\n"
)


@pytest.fixture(autouse=True)
def _clear_vpn_rate_limit_cache():
    cache = caches["launch_rate_limit"]
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def standard_user():
    return User.objects.create_user(username="mc-vpn-user@example.com", email="mc-vpn-user@example.com")


def _token(user, *granted_scopes: str) -> str:
    _token_obj, raw = ApiToken.create_token(name="mc-vpn", created_by=user, scopes=list(granted_scopes))
    return raw


def _ready_range(user, *, source=RangeSource.MISSION_CONTROL, secret_ref=None):
    request_id = uuid4()
    cms_request = CmsRequest.objects.create(
        request_id=request_id,
        request_type=RequestType.RANGE.value,
        user=user,
    )
    cms_range = RangeInstance.objects.create(
        request=cms_request,
        scenario_id="basic",
        user_id=user.id,
        status=ResourceStatus.READY.value,
        range_source=source.value,
        expires_at=timezone.now() + timedelta(days=30),
        maximum_expires_at=timezone.now() + timedelta(days=365),
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
    Range.objects.create(
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
            "secret_ref": secret_ref or f"arn:aws:secretsmanager:eu-central-1:123:secret:mc-vpn-{request_id}",
            "ready": True,
        },
    )
    return cms_range


def test_exact_scope_downloads_owned_mission_control_profile(settings, standard_user):
    settings.CLOUD_PROVIDER = "aws"
    cms_range = _ready_range(standard_user)
    raw = _token(standard_user, scopes.MISSION_CONTROL_VPN_PROFILE_READ)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")

    with boto3_secrets(make_secrets_client(PROFILE)):
        response = client.post(URL)

    assert response.status_code == 200
    assert response.content == PROFILE.encode()
    assert response["Content-Type"] == "application/x-openvpn-profile"
    assert response["Content-Disposition"] == 'attachment; filename="shifter-range.ovpn"'
    assert response["Cache-Control"] == "private, no-store"
    assert "ETag" not in response
    audit = AuditLog.objects.get(
        entity_type=AuditEntityType.CREDENTIAL,
        entity_id=cms_range.pk,
        action=AuditAction.DOWNLOAD,
    )
    assert audit.actor_id == standard_user.id
    assert audit.new_state["product"] == "mission_control"
    assert audit.new_state["channel"] == "openvpn"


def test_range_read_scope_does_not_grant_private_key_delivery(standard_user):
    _ready_range(standard_user)
    raw = _token(standard_user, scopes.MISSION_CONTROL_RANGE_READ)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")

    assert client.post(URL).status_code == 403


def test_session_post_requires_csrf(standard_user):
    _ready_range(standard_user)
    client = APIClient(enforce_csrf_checks=True)
    client.force_login(standard_user)

    assert client.post(URL).status_code == 403


def test_endpoint_selects_mission_control_source_not_same_users_ctf_range(settings, standard_user):
    settings.CLOUD_PROVIDER = "aws"
    _ready_range(standard_user, source=RangeSource.CTF, secret_ref="ctf-secret")
    _ready_range(standard_user, source=RangeSource.MISSION_CONTROL, secret_ref="mission-control-secret")
    raw = _token(standard_user, scopes.MISSION_CONTROL_VPN_PROFILE_READ)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    secrets = make_secrets_client(PROFILE)

    with boto3_secrets(secrets):
        response = client.post(URL)

    assert response.status_code == 200
    assert secrets.get_secret_value.call_args.kwargs["SecretId"] == "mission-control-secret"


def test_endpoint_is_bodyless_and_non_enumerating(standard_user):
    raw = _token(standard_user, scopes.MISSION_CONTROL_VPN_PROFILE_READ)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")

    assert client.post(URL, {"range_id": 42}, format="json").status_code == 400
    assert client.post(URL).status_code == 404


def test_rate_limit_blocks_before_secret_resolution(settings, standard_user):
    settings.CLOUD_PROVIDER = "aws"
    _ready_range(standard_user)
    raw = _token(standard_user, scopes.MISSION_CONTROL_VPN_PROFILE_READ)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    caches["launch_rate_limit"].set(f"credential-delivery:{standard_user.pk}", 50, 3600)
    secrets = make_secrets_client(PROFILE)

    with boto3_secrets(secrets):
        response = client.post(URL)

    assert response.status_code == 429
    assert response["Retry-After"] == "3600"
    secrets.get_secret_value.assert_not_called()


def test_rate_limit_backend_failure_fails_closed(monkeypatch, standard_user):
    _ready_range(standard_user)
    raw = _token(standard_user, scopes.MISSION_CONTROL_VPN_PROFILE_READ)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")

    def fail_add(*args, **kwargs):
        raise RuntimeError("cache unavailable")

    monkeypatch.setattr(caches["launch_rate_limit"], "add", fail_add)

    response = client.post(URL)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "vpn_profile_unavailable"


def test_profile_conflict_is_reported_without_provider_resolution(settings, standard_user):
    settings.CLOUD_PROVIDER = "aws"
    _ready_range(standard_user)
    Range.objects.filter(user=standard_user).update(status=Range.Status.PROVISIONING)
    raw = _token(standard_user, scopes.MISSION_CONTROL_VPN_PROFILE_READ)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    secrets = make_secrets_client(PROFILE)

    with boto3_secrets(secrets):
        response = client.post(URL)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "vpn_not_ready"
    secrets.get_secret_value.assert_not_called()


def test_invalid_profile_binding_is_unavailable_without_secret_resolution(settings, standard_user):
    settings.CLOUD_PROVIDER = "aws"
    _ready_range(standard_user)
    Range.objects.filter(user=standard_user).update(vpn_access_binding={})
    raw = _token(standard_user, scopes.MISSION_CONTROL_VPN_PROFILE_READ)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    secrets = make_secrets_client(PROFILE)

    with boto3_secrets(secrets):
        response = client.post(URL)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "vpn_profile_unavailable"
    secrets.get_secret_value.assert_not_called()
