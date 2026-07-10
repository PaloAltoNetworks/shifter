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

import cms.scenarios.hydrator as _hydrator
from cms.models import AgentConfig, OperatingSystem, Scenario
from cms.scenarios.registry import load_scenario_template as _GENUINE_LOAD_SCENARIO

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
        from engine.models import Range

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
        uuid: str = "rdp-instance-uuid",
        os_type: str = "kali",
        connection_name: str = "kali-1",
        host: str = "10.0.0.2",
        status=None,
    ):
        from engine.models import Range

        instance = {
            "uuid": uuid,
            "name": connection_name,
            "role": "victim",
            "os_type": os_type,
            "cloud_provider": "aws",
            "private_ip": host,
            "rdp_password_secret_arn": "arn:aws:secretsmanager:us-east-2:1:secret:rdp",
        }
        rng = Range.objects.create(
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

        _ensure_ngfw_catalog()
        resolved_status = status or ResourceStatus.READY.value
        request = Request.objects.create(request_id=uuid4(), request_type=RequestType.NGFW.value, user=user)
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


@pytest.fixture(autouse=True)
def _restore_real_scenario_loader():
    """Guard the scenario loader binding against cross-suite mock leakage.

    Legacy mock-coupled cms suites (``test_scenario_hydrator``,
    ``test_services_range*``) patch ``cms.scenarios.hydrator.load_scenario``.
    Under pytest-xdist that patched binding can leak into a worker that later
    runs these behavior tests, which drive real scenario hydration, leaving
    ``load_scenario`` a ``Mock``. Rebind it to the genuine loader (captured at
    import, before any patch is active) so each test starts from real state.
    Remove once those cms suites are rewritten to behavior tests (#957).
    """
    _hydrator.load_scenario = _GENUINE_LOAD_SCENARIO
    yield


# A scenario definition whose victim resolves to a Windows agent
# (xdr_agent=True), so create_range hydrates cleanly with a single
# Windows AgentConfig and no cloud configured.
HYDRATABLE_DEFINITION: dict[str, Any] = {
    "instances": [
        {"name": "Attacker", "role": "attacker", "os_type": "kali", "xdr_agent": False},
        {"name": "Target", "role": "victim", "os_type": "windows", "xdr_agent": True},
    ],
    "subnets": [{"name": "core", "instances": ["Attacker", "Target"]}],
    "ngfw": False,
}


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
def hydratable_scenario(db) -> Scenario:
    """A DB custom scenario that hydrates with a single Windows agent."""
    staff = User.objects.create_user(
        username="scenario-author@example.com",
        email="scenario-author@example.com",
        is_staff=True,
    )
    return Scenario.objects.create(
        scenario_id="behavior-test",
        name="Behavior Test Range",
        description="Hydratable scenario for behavior tests.",
        definition=HYDRATABLE_DEFINITION,
        created_by=staff,
        updated_by=staff,
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
            reverse("mission_control:launch_range"),
            data=json.dumps({"agent_id": agent.id, "scenario": scenario}),
            content_type="application/json",
        )
        return response, agent, scenario

    return _launch
