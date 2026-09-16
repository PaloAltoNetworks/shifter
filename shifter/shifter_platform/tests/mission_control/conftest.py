"""Shared fixtures for mission_control behavior tests.

These tests drive the real Django views/URLs with a real database and assert
observable behavior (HTTP responses + persisted ORM state) instead of patching
first-party service/view internals. The only boundaries that would need mocking
are process/network/cloud SDKs; in the test settings ECS/local-provisioner are
unconfigured, so range provisioning is a no-op and no cloud mock is required.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from django.contrib.auth import get_user_model
from django.urls import reverse

from cms.models import AgentConfig, OperatingSystem, RaesPackageSource

User = get_user_model()


# ---------------------------------------------------------------------------
# Cloud / network boundary helpers (SSH-key secret store + Guacamole HTTP)
#
# MC SSH/NGFW/Guacamole views drive the real engine.services + mission_control
# .guacamole code; the only things mocked are the real boundaries underneath:
# the boto3 Secrets Manager client (engine.secrets.get_ssh_key) and the urllib
# token-exchange POST to the Guacamole API.
# ---------------------------------------------------------------------------

# Opaque stand-in for SSH key material; tests assert it round-trips from the
# secrets store, never that it is a valid key (a real PEM block would trip the
# detect-private-key pre-commit hook).
SSH_KEY_PEM = "TEST-SSH-PRIVATE-KEY-MATERIAL"  # nosec B105  # NOSONAR

# 32 hex chars = 16-byte AES-128 key used by the Guacamole JSON-auth tests.
SECRET_KEY_128 = "0123456789abcdef0123456789abcdef"  # nosec B105  # NOSONAR


def make_secrets_client(value: str = SSH_KEY_PEM) -> MagicMock:
    """Build a MagicMock standing in for the boto3 Secrets Manager client."""
    client = MagicMock()
    client.get_secret_value.return_value = {"SecretString": value}
    return client


@contextmanager
def _secrets_boundary_cm(value: str = SSH_KEY_PEM, *, client: MagicMock | None = None):
    """Bind a Secrets Manager client at the boto3 boundary; yield the client.

    Pass ``client`` to inject a pre-built mock (e.g. one whose
    ``get_secret_value`` raises) for failure-path tests.
    """
    client = client or make_secrets_client(value)
    with patch("boto3.client", return_value=client):
        yield client


def decrypt_guac_data(encrypted_b64: str, secret_key_hex: str) -> dict[str, Any]:
    """Reverse ``mission_control.guacamole.sign_and_encrypt_payload``.

    AES-CBC (zero IV) decrypt, strip PKCS-style padding and the 32-byte
    HMAC-SHA256 prefix, then JSON-decode — so tests can assert on the payload
    that was actually signed, encrypted, and POSTed to the Guacamole API.
    """
    key = bytes.fromhex(secret_key_hex)
    blob = base64.b64decode(encrypted_b64)
    decryptor = Cipher(algorithms.AES(key), modes.CBC(b"\x00" * 16)).decryptor()
    padded = decryptor.update(blob) + decryptor.finalize()
    signed = padded[: -padded[-1]]
    return json.loads(signed[32:])


class GuacExchange:
    """Captured Guacamole token-exchange POSTs for assertions."""

    def __init__(self, token: str) -> None:
        self.token = token
        self.requests: list[Any] = []

    def posted_payload(self, secret_key_hex: str, index: int = 0) -> dict[str, Any]:
        """Decrypt the ``data`` form field of the captured request at ``index``."""
        encrypted = parse_qs(self.requests[index].data.decode())["data"][0]
        return decrypt_guac_data(encrypted, secret_key_hex)


@contextmanager
def _guac_exchange_cm(token: str = "token123"):  # noqa: S107 # nosec B107
    """Mock the urllib Guacamole ``/api/tokens`` POST; capture the requests."""
    exchange = GuacExchange(token)
    body = json.dumps({"authToken": token}).encode("utf-8")

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return body

    def _fake_urlopen(req, timeout=None):
        exchange.requests.append(req)
        return _Resp()

    with patch("urllib.request.urlopen", side_effect=_fake_urlopen):
        yield exchange


# These helpers are exposed as fixtures because ``tests/mission_control`` is not
# an importable package (no ``__init__.py`` — it would shadow the real
# ``mission_control`` app), so ``from .conftest import ...`` is unavailable.


@pytest.fixture
def secret_key_128() -> str:
    return SECRET_KEY_128


@pytest.fixture
def ssh_key_pem() -> str:
    return SSH_KEY_PEM


@pytest.fixture
def secrets_boundary():
    """Return the boto3 Secrets Manager boundary context-manager factory."""
    return _secrets_boundary_cm


@pytest.fixture
def secrets_client_factory():
    """Return the boto3 Secrets Manager client factory (for custom side effects)."""
    return make_secrets_client


@pytest.fixture
def guac_exchange():
    """Return the Guacamole token-exchange context-manager factory."""
    return _guac_exchange_cm


@pytest.fixture
def range_ssh_instance(db):
    """Factory: a real READY ``Range`` for ``user`` with one SSH-capable instance.

    The instance carries gcp ``provider_metadata`` with an SSH-key secret ref so
    the real ``engine.services.get_ssh_connection_info`` fetches the key over the
    boto3 Secrets Manager boundary (see ``secrets_boundary``). Returns
    ``(range, instance_dict)``.
    """

    def _make(
        user,
        *,
        uuid: str = "550e8400-e29b-41d4-a716-446655440000",
        os_type: str = "ubuntu",
        connection_name: str = "target-ubuntu",
        host: str = "10.50.1.10",
        username: str = "ubuntu",
        cloud_provider: str = "gcp",
        status=None,
    ):
        from uuid import UUID, uuid4

        from cms.models import Instance as CMSInstance
        from cms.models import InstanceType
        from cms.models import Request as CMSRequest
        from engine.models import Range
        from shared.enums import RequestType
        from workspaces.services import resolve_personal_workspace

        workspace_id = resolve_personal_workspace(user).workspace_id
        instance_type, _ = InstanceType.objects.get_or_create(
            slug="test-range-instance",
            defaults={"name": "Test Range Instance", "spec_slug": "instance.panw-ngfw"},
        )
        cms_request = CMSRequest.objects.create(
            workspace_id=workspace_id,
            request_id=uuid4(),
            request_type=RequestType.RANGE.value,
            user=user,
        )
        try:
            cms_instance_id = UUID(uuid)
        except ValueError:
            cms_instance_id = None
        if cms_instance_id is not None:
            CMSInstance.objects.create(
                id=cms_instance_id,
                request=cms_request,
                name=connection_name,
                instance_type=instance_type,
            )

        instance = {
            "uuid": uuid,
            "role": "attacker",
            "os_type": os_type,
            "cloud_provider": cloud_provider,
            "provider_metadata": {
                "gcp": {
                    "instance_name": connection_name,
                    "private_ip": host,
                    "ssh_key_secret_id": "projects/test/secrets/range-ssh-key",
                    "ssh_username": username,
                }
            },
        }
        rng = Range.objects.create(
            workspace_id=workspace_id,
            user=user,
            status=status or Range.Status.READY,
            provisioned_instances=[instance],
        )
        return rng, instance

    return _make


@pytest.fixture
def range_rdp_instance(db):
    """Factory: a real READY ``Range`` with one RDP-capable victim instance.

    The instance carries an RDP-password secret ref so the real
    ``engine.services.get_rdp_connection_info`` resolves the password over the
    boto3 Secrets Manager boundary. Returns ``(range, instance_dict)``.
    """

    def _make(
        user,
        *,
        uuid: str = "7d484828-06f1-4df8-a6e2-9d6bbb5e2d7b",
        os_type: str = "kali",
        connection_name: str = "kali-1",
        host: str = "10.0.0.2",
        sftp_root_directory: str | None = None,
        status=None,
    ):
        from uuid import UUID, uuid4

        from cms.models import Instance as CMSInstance
        from cms.models import InstanceType
        from cms.models import Request as CMSRequest
        from engine.models import Range
        from shared.enums import RequestType
        from workspaces.services import resolve_personal_workspace

        workspace_id = resolve_personal_workspace(user).workspace_id
        instance_type, _ = InstanceType.objects.get_or_create(
            slug="test-range-instance",
            defaults={"name": "Test Range Instance", "spec_slug": "instance.panw-ngfw"},
        )
        cms_request = CMSRequest.objects.create(
            workspace_id=workspace_id,
            request_id=uuid4(),
            request_type=RequestType.RANGE.value,
            user=user,
        )
        CMSInstance.objects.create(
            id=UUID(uuid),
            request=cms_request,
            name=connection_name,
            instance_type=instance_type,
        )

        instance = {
            "uuid": uuid,
            "name": connection_name,
            "role": "victim",
            "os_type": os_type,
            "cloud_provider": "aws",
            "private_ip": host,
            "rdp_password_secret_arn": "arn:aws:secretsmanager:us-east-2:1:secret:rdp",
        }
        if sftp_root_directory is not None:
            instance["sftp_root_directory"] = sftp_root_directory
        rng = Range.objects.create(
            workspace_id=workspace_id,
            user=user,
            status=status or Range.Status.READY,
            provisioned_instances=[instance],
        )
        return rng, instance

    return _make


def _ensure_ngfw_catalog():
    """Ensure the ``panw-ngfw`` InstanceType/AppType catalog rows exist.

    They are migration-seeded, but a ``TransactionTestCase`` elsewhere can flush
    them from a worker DB under xdist, so create defensively.
    """
    from cms.models import AppType, InstanceType

    InstanceType.objects.get_or_create(
        slug="panw-ngfw",
        defaults={"name": "PAN-OS NGFW", "spec_slug": "instance.panw-ngfw"},
    )
    AppType.objects.get_or_create(
        slug="panw-ngfw",
        defaults={"name": "PANW NGFW", "spec_slug": "app.panw-ngfw"},
    )


@pytest.fixture
def cms_ngfw_app(db):
    """Factory: a real CMS NGFW ``App`` (Request + Instance + App, panw-ngfw types).

    This is what ``cms.services.get_ngfw`` / ``list_ngfws`` resolve and project
    into the ``NGFWAppContext`` the MC NGFW pages render. Returns the ``App``.
    """

    def _make(user, *, name="DevNGFW", status=None, serial="X-1"):
        from uuid import uuid4

        from cms.models import App, AppType, Instance, InstanceType, Request
        from shared.enums import RequestType, ResourceStatus
        from workspaces.services import resolve_personal_workspace

        _ensure_ngfw_catalog()
        resolved_status = status or ResourceStatus.READY.value
        request = Request.objects.create(
            workspace_id=resolve_personal_workspace(user).workspace_id,
            request_id=uuid4(),
            request_type=RequestType.NGFW.value,
            user=user,
        )
        instance = Instance.objects.create(
            request=request,
            name=name,
            instance_type=InstanceType.objects.get(slug="panw-ngfw"),
            status=resolved_status,
        )
        return App.objects.create(
            name=name,
            app_type=AppType.objects.get(slug="panw-ngfw"),
            instance=instance,
            status=resolved_status,
            data={"serial_number": serial},
        )

    return _make


@pytest.fixture
def ngfw_catalog(db):
    """Ensure the panw-ngfw catalog exists (for the real create_ngfw path)."""
    _ensure_ngfw_catalog()


@pytest.fixture
def ngfw_credentials(db):
    """Factory: real deployment_profile + scm ``Credential`` rows for ``user``.

    Returns ``(deployment_profile, scm_credential)`` so create_ngfw can resolve
    them by id.
    """

    def _make(user):
        from cms.models import Credential, CredentialType

        dp_ct, _ = CredentialType.objects.get_or_create(
            slug="deployment_profile",
            defaults={"name": "deployment_profile", "spec_slug": "credential.deployment_profile"},
        )
        scm_ct, _ = CredentialType.objects.get_or_create(
            slug="scm", defaults={"name": "scm", "spec_slug": "credential.scm"}
        )
        deployment_profile = Credential.objects.create(
            user=user, credential_type=dp_ct, name="dp-cred", data={"name": "dp", "authcode": "AUTH-XYZ"}
        )
        scm_credential = Credential.objects.create(
            user=user,
            credential_type=scm_ct,
            name="scm-cred",
            data={
                "name": "scm",
                "scm_pin_id": "PIN1",
                "scm_pin_value": "VAL1",
                "scm_folder_name": "folder",
                "sls_region": "us",
            },
        )
        return deployment_profile, scm_credential

    return _make


@pytest.fixture
def make_ngfw(db):
    """Factory: a real NGFW ``Instance`` (READY, AWS mgmt state) owned by ``user``.

    The state carries a management IP + SSH-key secret ARN so the real
    ``engine.services.connect_ngfw_terminal`` fetches the key over the boto3
    Secrets Manager boundary (see ``secrets_boundary``).
    """

    def _make(user, *, status=None, state=None, owner=None, with_request=True):
        from uuid import uuid4

        from engine.models import Instance, Request
        from shared.enums import RequestType, ResourceStatus

        request = None
        if with_request:
            # engine.models.Request (imported above) carries no workspace scope;
            # tenancy lives on the CMS request and the engine Range.
            request = Request.objects.create(
                request_id=uuid4(),
                request_type=RequestType.NGFW.value,
                user=owner or user,
            )
        default_state = {
            "management_ip": "10.1.5.10",
            "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
        }
        return Instance.objects.create(
            uuid=uuid4(),
            request=request,
            role=Instance.Role.NGFW,
            os_type=Instance.OSType.PANOS,
            status=status or ResourceStatus.READY.value,
            state=default_state if state is None else state,
        )

    return _make


@pytest.fixture
def windows_os(db) -> OperatingSystem:
    """The seeded (or created) Windows operating system row."""
    os_obj, _ = OperatingSystem.objects.get_or_create(
        slug="windows", defaults={"name": "Windows", "extensions": [".msi"]}
    )
    return os_obj


@pytest.fixture
def linux_os(db) -> OperatingSystem:
    """A Linux operating system row for agent-OS variations."""
    os_obj, _ = OperatingSystem.objects.get_or_create(
        slug="linux-debian", defaults={"name": "Linux (Debian/Ubuntu)", "extensions": [".deb"]}
    )
    return os_obj


@pytest.fixture
def make_agent(db, windows_os) -> Callable[..., AgentConfig]:
    """Factory creating a real AgentConfig owned by ``user``."""

    def _make(user, *, os=None, name="Test XDR Agent", **overrides) -> AgentConfig:
        fields: dict[str, Any] = {
            "name": name,
            "s3_key": "agents/test/agent.msi",
            "original_filename": "agent.msi",
            "file_size_bytes": 50_000_000,
            "sha256_hash": "abc123",
            "user": user,
            "os": os or windows_os,
        }
        fields.update(overrides)
        return AgentConfig.objects.create(**fields)

    return _make


@pytest.fixture
def hydratable_scenario(db, monkeypatch) -> RaesPackageSource:
    """A conformance-passed RAES source with dispatch held at the cloud seam."""
    staff = User.objects.create_user(
        username="scenario-author@example.com",
        email="scenario-author@example.com",
        is_staff=True,
    )
    monkeypatch.setattr("engine.services._raes_range.start_raes_range_provisioning", lambda *_a, **_kw: None)

    def dispatch(request_id, user, _source, backend_admission, workspace_id, egress_mode):
        from engine.services import create_raes_range

        create_raes_range(
            request_id=request_id,
            user_id=user.id,
            compiled_plan={"kind": "raes_provisioning_plan", "raes_version": "2.0", "resources": []},
            backend_admission=backend_admission,
            workspace_id=workspace_id,
            egress_mode=egress_mode,
        )

    monkeypatch.setattr("cms.services._raes_range_create._dispatch_raes_package", dispatch)
    return RaesPackageSource.objects.create(
        scenario_id="behavior-test",
        contract_kind="raes",
        contract_profile="shifter",
        package_ref="tests/packs/behavior-test",
        package_version="1.0.0",
        package_digest="sha256:" + "a" * 64,
        conformance_status="passed",
        registered_by=staff,
    )


@pytest.fixture
def launch_range_via_api(make_agent, hydratable_scenario) -> Callable[..., tuple[Any, AgentConfig, str]]:
    """Launch a real range for ``(client, user)`` and return (response, agent, scenario_id).

    Drives the real launch endpoint so downstream get/cancel/destroy tests
    operate on genuinely-persisted range state.
    """

    def _launch(client, user, *, scenario_id: str | None = None) -> tuple[Any, AgentConfig, str]:
        agent = make_agent(user)
        scenario = scenario_id or hydratable_scenario.scenario_id
        response = client.post(
            reverse("v1:mission_control:range-launch"),
            data=json.dumps({"agent_id": agent.id, "scenario": scenario}),
            content_type="application/json",
        )
        return response, agent, scenario

    return _launch
