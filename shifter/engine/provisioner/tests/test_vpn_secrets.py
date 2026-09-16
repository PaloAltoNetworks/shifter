"""Provider secret-store adapter tests for OpenVPN generations."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError

from gcp_dynamic_secrets import DynamicSecretClass, DynamicSecretPublicationPending, canonical_secret_id
from gcp_vpn_identity import gcp_vpn_gateway_pool_service_account_email
from vpn_secrets import AWSVpnSecretOps, GCPVpnSecretOps, openvpn_access_enabled


@pytest.fixture(autouse=True)
def _explicit_dynamic_secret_project(monkeypatch):
    """Exercise the supported same-project migration posture explicitly."""
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("GCP_DYNAMIC_SECRET_PROJECT_ID", "range-project")


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, "test")


def test_aws_adapter_creates_and_reuses_generation_material(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "test")
    generation = uuid4()
    client = MagicMock()
    client.get_secret_value.side_effect = [
        _client_error("ResourceNotFoundException"),
        {"SecretString": "issuer-material"},
        {"SecretString": "issuer-material"},
    ]
    client.create_secret.return_value = {"ARN": "arn:issuer"}
    adapter = AWSVpnSecretOps(client)
    factory = MagicMock(return_value="issuer-material")

    assert adapter.read_or_create_issuer(42, generation, factory) == "issuer-material"
    assert adapter.read_or_create_issuer(42, generation, factory) == "issuer-material"

    factory.assert_called_once_with()
    client.create_secret.assert_called_once()
    create_kwargs = client.create_secret.call_args.kwargs
    assert create_kwargs["Name"].endswith(f"vpn-issuer/range-42/{generation}")
    assert create_kwargs["SecretString"] == "issuer-material"


def test_aws_adapter_deletes_all_generation_secrets_idempotently(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "test")
    generation = uuid4()
    client = MagicMock()
    client.delete_secret.side_effect = [None, _client_error("ResourceNotFoundException"), None]

    AWSVpnSecretOps(client).delete_generation(42, generation)

    assert client.delete_secret.call_count == 3
    assert all(call.kwargs["ForceDeleteWithoutRecovery"] is True for call in client.delete_secret.call_args_list)


class _NotFound(Exception):
    pass


class _AlreadyExists(Exception):
    pass


class _InvalidArgument(Exception):
    pass


def _mock_slot_read(monkeypatch, slot: int | None) -> None:
    """Stub the reserved gateway pool-slot DB read used by GCPVpnSecretOps."""
    cursor = MagicMock()
    cursor.fetchone.return_value = None if slot is None else (slot,)
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr("vpn_secrets.get_db_connection", MagicMock(return_value=conn))


def _gcp_adapter(client, *, project_id: str = "range-project") -> GCPVpnSecretOps:
    client.get_iam_policy.return_value = {"bindings": []}
    return GCPVpnSecretOps(
        client=client,
        exceptions=SimpleNamespace(NotFound=_NotFound, AlreadyExists=_AlreadyExists, InvalidArgument=_InvalidArgument),
        project_id=project_id,
    )


@pytest.mark.parametrize(
    ("kind", "credential_class", "audience"),
    [
        ("issuer", DynamicSecretClass.VPN_ISSUER, "workload"),
        ("server", DynamicSecretClass.VPN_SERVER, "workload"),
        ("profile", DynamicSecretClass.VPN_PROFILE, "participant"),
    ],
)
def test_gcp_vpn_kinds_map_to_the_expected_canonical_audience(
    monkeypatch,
    kind: str,
    credential_class: DynamicSecretClass,
    audience: str,
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "gcp-dev")
    monkeypatch.setenv("GCP_DYNAMIC_SECRET_PROJECT_ID", "range-secrets")
    generation = uuid4()
    locations = _gcp_adapter(MagicMock(), project_id="compute-project")._locations(42, generation, kind)
    expected_id = canonical_secret_id(
        credential_class=credential_class,
        scope=f"range-42-{str(generation).replace('-', '')}",
    )

    assert locations.create_ref == f"projects/range-secrets/secrets/{expected_id}"
    assert f"-{audience}-vpn-" in locations.create_ref


def test_gcp_server_secret_grants_the_reserved_pool_identity(monkeypatch):
    client = MagicMock()
    client.access_secret_version.side_effect = _NotFound()
    client.get_secret.side_effect = _NotFound()
    _mock_slot_read(monkeypatch, 7)
    adapter = _gcp_adapter(client)

    adapter.put_server(42, uuid4(), "server-material")

    client.create_secret.assert_called_once()
    client.add_secret_version.assert_called_once()
    gateway_email = gcp_vpn_gateway_pool_service_account_email("range-project", 7)
    policy = client.set_iam_policy.call_args.kwargs["request"]["policy"]
    assert policy == {
        "bindings": [
            {
                "role": "roles/secretmanager.secretAccessor",
                "members": [f"serviceAccount:{gateway_email}"],
            }
        ]
    }


def test_gcp_adapter_never_creates_or_binds_service_accounts(monkeypatch):
    # ADR-008-R7: the pool model removes runtime SA administration entirely. The
    # adapter holds no IAM-admin client; the only set_iam_policy call is the
    # Secret Manager grant on the server secret (not a service-account resource).
    client = MagicMock()
    client.access_secret_version.side_effect = _NotFound()
    client.get_secret.side_effect = _NotFound()
    _mock_slot_read(monkeypatch, 3)
    adapter = _gcp_adapter(client)

    adapter.put_server(42, uuid4(), "server-material")

    assert not hasattr(adapter, "_iam_client")
    assert client.set_iam_policy.call_count == 1
    assert "/secrets/" in client.set_iam_policy.call_args.kwargs["request"]["resource"]


def test_gcp_put_server_raises_when_no_pool_slot_reserved(monkeypatch):
    client = MagicMock()
    client.access_secret_version.side_effect = _NotFound()
    client.get_secret.side_effect = _NotFound()
    _mock_slot_read(monkeypatch, None)
    adapter = _gcp_adapter(client)
    generation = uuid4()

    with pytest.raises(RuntimeError, match="gateway pool slot"):
        adapter.put_server(42, generation, "server-material")


def test_gcp_delete_generation_removes_secrets_without_touching_identities():
    client = MagicMock()
    adapter = _gcp_adapter(client)

    adapter.delete_generation(42, uuid4())

    # All three per-generation secrets are deleted; the pooled identity is
    # permanent, so there is no service-account lifecycle to invoke.
    assert client.delete_secret.call_count == 3
    assert not hasattr(adapter, "_iam_client")


def test_gcp_dedicated_project_separates_secret_storage_from_gateway_identity(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "gcp-dev")
    monkeypatch.setenv("GCP_DYNAMIC_SECRET_PROJECT_ID", "range-secrets")
    client = MagicMock()
    client.access_secret_version.side_effect = _NotFound()
    client.get_secret.side_effect = _NotFound()
    _mock_slot_read(monkeypatch, 7)
    adapter = _gcp_adapter(client, project_id="compute-project")

    adapter.put_server(42, uuid4(), "server-material")

    assert client.create_secret.call_args.kwargs["request"]["parent"] == "projects/range-secrets"
    gateway_email = gcp_vpn_gateway_pool_service_account_email("compute-project", 7)
    policy = client.set_iam_policy.call_args.kwargs["request"]["policy"]
    assert policy["bindings"][0]["members"] == [f"serviceAccount:{gateway_email}"]


def test_gcp_concurrent_creator_reuses_winner_without_publishing_competing_profile(monkeypatch):
    monkeypatch.setenv("GCP_DYNAMIC_SECRET_PROJECT_ID", "range-secrets")
    client = MagicMock()
    winner = SimpleNamespace(payload=SimpleNamespace(data=b"winner-profile"))
    client.access_secret_version.side_effect = [_NotFound(), _NotFound(), winner]
    client.get_secret.side_effect = _NotFound()
    client.create_secret.side_effect = _AlreadyExists()
    adapter = _gcp_adapter(client)

    ref = adapter.put_profile(42, uuid4(), "competing-profile")

    assert ref.startswith("projects/range-secrets/secrets/")
    client.add_secret_version.assert_not_called()


def test_gcp_existing_profile_is_authoritative_over_repeated_payload(monkeypatch):
    monkeypatch.setenv("GCP_DYNAMIC_SECRET_PROJECT_ID", "range-secrets")
    client = MagicMock()
    client.access_secret_version.return_value = SimpleNamespace(payload=SimpleNamespace(data=b"published-profile"))
    adapter = _gcp_adapter(client)

    ref = adapter.put_profile(42, uuid4(), "competing-profile")

    assert ref.startswith("projects/range-project/secrets/")
    client.create_secret.assert_not_called()
    client.add_secret_version.assert_not_called()


def test_gcp_concurrent_server_creator_reuses_winner_and_grants_gateway(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "gcp-dev")
    monkeypatch.setenv("GCP_DYNAMIC_SECRET_PROJECT_ID", "range-secrets")
    client = MagicMock()
    winner = SimpleNamespace(payload=SimpleNamespace(data=b"winner-server"))
    client.access_secret_version.side_effect = [_NotFound(), _NotFound(), winner]
    client.get_secret.side_effect = _NotFound()
    client.create_secret.side_effect = _AlreadyExists()
    _mock_slot_read(monkeypatch, 7)
    adapter = _gcp_adapter(client, project_id="compute-project")

    adapter.put_server(42, uuid4(), "competing-server")

    client.add_secret_version.assert_not_called()
    gateway_email = gcp_vpn_gateway_pool_service_account_email("compute-project", 7)
    policy_request = client.set_iam_policy.call_args.kwargs["request"]
    assert policy_request["resource"].startswith("projects/range-secrets/secrets/")
    assert policy_request["policy"]["bindings"][0]["members"] == [f"serviceAccount:{gateway_email}"]


def test_gcp_existing_server_is_authoritative_and_gateway_grant_is_reconciled(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "gcp-dev")
    monkeypatch.setenv("GCP_DYNAMIC_SECRET_PROJECT_ID", "range-secrets")
    client = MagicMock()
    client.access_secret_version.return_value = SimpleNamespace(payload=SimpleNamespace(data=b"published-server"))
    _mock_slot_read(monkeypatch, 7)
    adapter = _gcp_adapter(client, project_id="compute-project")

    adapter.put_server(42, uuid4(), "competing-server")

    client.create_secret.assert_not_called()
    client.add_secret_version.assert_not_called()
    client.set_iam_policy.assert_called_once()


def test_gcp_vpn_waits_for_empty_legacy_container_before_canonical_create(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "gcp-dev")
    monkeypatch.setenv("GCP_DYNAMIC_SECRET_PROJECT_ID", "range-secrets")
    monkeypatch.setattr("gcp_dynamic_secrets.time.sleep", lambda _seconds: None)
    client = MagicMock()
    client.access_secret_version.side_effect = _NotFound()
    client.get_secret.return_value = object()
    adapter = _gcp_adapter(client, project_id="compute-project")

    with pytest.raises(DynamicSecretPublicationPending):
        adapter.put_profile(42, uuid4(), "competing-profile")

    assert client.get_secret.call_args.kwargs["request"]["name"].startswith(
        "projects/compute-project/secrets/shifter-range-42-vpn-"
    )
    client.create_secret.assert_not_called()
    client.add_secret_version.assert_not_called()


def test_gcp_existing_empty_container_fails_without_publishing_competing_profile(monkeypatch):
    monkeypatch.setenv("GCP_DYNAMIC_SECRET_PROJECT_ID", "range-secrets")
    monkeypatch.setattr("gcp_dynamic_secrets.time.sleep", lambda _seconds: None)
    client = MagicMock()
    client.access_secret_version.side_effect = _NotFound()
    client.get_secret.side_effect = _NotFound()
    client.create_secret.side_effect = _AlreadyExists()
    adapter = _gcp_adapter(client)

    with pytest.raises(DynamicSecretPublicationPending):
        adapter.put_profile(42, uuid4(), "competing-profile")

    client.add_secret_version.assert_not_called()


def test_capability_gate_requires_selected_provider_prerequisites(monkeypatch):
    monkeypatch.setenv("CLOUD_PROVIDER", "aws")
    monkeypatch.delenv("RANGE_VPN_EDGE_SUBNET_ID", raising=False)
    monkeypatch.delenv("RANGE_VPN_GATEWAY_PERMISSIONS_BOUNDARY_ARN", raising=False)
    monkeypatch.delenv("RANGE_VPN_PROVIDER_ENDPOINT_SECURITY_GROUP_ID", raising=False)
    assert openvpn_access_enabled() is False

    monkeypatch.setenv("RANGE_VPN_EDGE_SUBNET_ID", "subnet-edge")
    monkeypatch.setenv("RANGE_VPN_GATEWAY_PERMISSIONS_BOUNDARY_ARN", "arn:boundary")
    monkeypatch.setenv("RANGE_VPN_PROVIDER_ENDPOINT_SECURITY_GROUP_ID", "sg-endpoints")
    assert openvpn_access_enabled() is False

    monkeypatch.setenv("PORTAL_VPC_CIDR", "10.40.0.0/20")
    assert openvpn_access_enabled() is True

    monkeypatch.setenv("CLOUD_PROVIDER", "gcp")
    monkeypatch.setenv("GCP_RANGE_BACKEND", "gce")
    monkeypatch.setenv("GCP_RANGE_CELL_NETWORK_MODE", "shared-vpc")
    monkeypatch.setenv("GCP_RANGE_PRIVATE_GOOGLE_ACCESS", "true")
    monkeypatch.setenv("GCP_RANGE_HOST_SERVICE_ACCOUNT_EMAIL", "range-host@example.test")
    monkeypatch.setenv("GCP_PROVISIONER_SERVICE_ACCOUNT_EMAIL", "provisioner@example.test")
    monkeypatch.setenv("GCP_RANGE_LINUX_IMAGE", "projects/test/global/images/ubuntu")
    assert openvpn_access_enabled() is True

    monkeypatch.setenv("GCP_RANGE_HOST_SERVICE_ACCOUNT_SCOPES", "https://www.googleapis.com/auth/logging.write")
    assert openvpn_access_enabled() is False
    monkeypatch.setenv("GCP_RANGE_HOST_SERVICE_ACCOUNT_SCOPES", "https://www.googleapis.com/auth/cloud-platform")

    monkeypatch.setenv("GCP_RANGE_CELL_NETWORK_MODE", "vpc-per-range")
    assert openvpn_access_enabled() is False

    monkeypatch.setenv("GCP_RANGE_BACKEND", "gdc")
    assert openvpn_access_enabled() is False
