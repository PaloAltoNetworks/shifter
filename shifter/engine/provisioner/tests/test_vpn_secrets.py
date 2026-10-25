"""Secret-store adapter tests for the tenant OpenVPN issuer and participant profiles (#2480)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from gcp_dynamic_secrets import DynamicSecretClass, DynamicSecretPublicationPending, canonical_secret_id
from vpn_secrets import GCPVpnSecretOps, get_vpn_secret_ops, openvpn_access_enabled

_ISSUER = "projects/platform-project/secrets/shifter-test-vpn-issuer"


@pytest.fixture(autouse=True)
def _explicit_dynamic_secret_project(monkeypatch):
    """Exercise the supported same-project migration posture explicitly."""
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("GCP_DYNAMIC_SECRET_PROJECT_ID", "range-project")


class _NotFound(Exception):
    pass


class _AlreadyExists(Exception):
    pass


class _InvalidArgument(Exception):
    pass


def _gcp_adapter(client, *, project_id: str = "range-project", issuer_secret: str = _ISSUER) -> GCPVpnSecretOps:
    return GCPVpnSecretOps(
        client=client,
        exceptions=SimpleNamespace(NotFound=_NotFound, AlreadyExists=_AlreadyExists, InvalidArgument=_InvalidArgument),
        project_id=project_id,
        issuer_secret=issuer_secret,
    )


def test_profile_lives_in_the_participant_audience(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "gcp-dev")
    monkeypatch.setenv("GCP_DYNAMIC_SECRET_PROJECT_ID", "range-secrets")
    generation = uuid4()
    locations = _gcp_adapter(MagicMock(), project_id="compute-project")._profile_locations(42, generation)
    expected_id = canonical_secret_id(
        credential_class=DynamicSecretClass.VPN_PROFILE, scope=f"range-42-{str(generation).replace('-', '')}"
    )

    assert locations.create_ref == f"projects/range-secrets/secrets/{expected_id}"
    assert "-participant-vpn-" in locations.create_ref


def test_issuer_is_read_from_the_configured_tenant_secret_only():
    client = MagicMock()
    client.access_secret_version.return_value = SimpleNamespace(payload=SimpleNamespace(data=b"issuer"))

    assert _gcp_adapter(client).read_issuer() == "issuer"
    assert client.access_secret_version.call_args.kwargs["request"] == {"name": f"{_ISSUER}/versions/latest"}
    client.create_secret.assert_not_called()

    with pytest.raises(RuntimeError, match="RANGE_OPENVPN_ISSUER_SECRET_ID"):
        _gcp_adapter(MagicMock(), issuer_secret="").read_issuer()


def test_delete_and_presence_cover_both_profile_locations(monkeypatch):
    monkeypatch.setenv("GCP_DYNAMIC_SECRET_PROJECT_ID", "range-secrets")
    client = MagicMock()
    client.access_secret_version.side_effect = _NotFound()
    adapter = _gcp_adapter(client)
    generation = uuid4()

    assert adapter.profile_present(42, generation) is False
    adapter.delete_profile(42, generation)

    deleted = [call.kwargs["request"]["name"] for call in client.delete_secret.call_args_list]
    assert any(name.startswith("projects/range-secrets/secrets/") for name in deleted)
    client.set_iam_policy.assert_not_called()


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


def test_pool_is_enabled_only_with_a_deployed_pool_on_shared_vpc_gce(monkeypatch):
    monkeypatch.setenv("CLOUD_PROVIDER", "gcp")
    monkeypatch.setenv("GCP_RANGE_BACKEND", "gce")
    monkeypatch.setenv("GCP_RANGE_CELL_NETWORK_MODE", "shared-vpc")
    monkeypatch.delenv("RANGE_OPENVPN_ENDPOINT", raising=False)
    monkeypatch.delenv("RANGE_OPENVPN_ISSUER_SECRET_ID", raising=False)
    monkeypatch.delenv("RANGE_OPENVPN_POOL_CIDRS", raising=False)
    assert openvpn_access_enabled() is False

    monkeypatch.setenv("RANGE_OPENVPN_ENDPOINT", "203.0.113.7")
    monkeypatch.setenv("RANGE_OPENVPN_ISSUER_SECRET_ID", _ISSUER)
    assert openvpn_access_enabled() is False
    monkeypatch.setenv("RANGE_OPENVPN_POOL_CIDRS", "10.49.0.0/24")
    assert openvpn_access_enabled() is True

    monkeypatch.setenv("GCP_RANGE_CELL_NETWORK_MODE", "vpc-per-range")
    assert openvpn_access_enabled() is False
    monkeypatch.setenv("GCP_RANGE_CELL_NETWORK_MODE", "shared-vpc")
    monkeypatch.setenv("GCP_RANGE_BACKEND", "gdc")
    assert openvpn_access_enabled() is False

    monkeypatch.setenv("CLOUD_PROVIDER", "aws")
    assert openvpn_access_enabled() is False
    with pytest.raises(RuntimeError, match="shared OpenVPN pool"):
        get_vpn_secret_ops()
