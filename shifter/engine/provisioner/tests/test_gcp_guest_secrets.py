"""Tests for deterministic ACES authored-account credential secrets (#1560)."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import gcp_guest_secrets


def test_participant_ssh_secret_is_distinct_from_host_management_secret(monkeypatch):
    secret_ids: list[str] = []

    def read_or_create(secret_id, _payload_factory):
        secret_ids.append(secret_id)
        return f"projects/p/secrets/{secret_id}", "PRIVATE"

    monkeypatch.setattr(gcp_guest_secrets, "_read_or_create_secret", read_or_create)
    monkeypatch.setattr(gcp_guest_secrets, "derive_ssh_public_key", lambda private: f"public:{private}")
    instance = {"uuid": "member-a"}

    host_ref, _ = gcp_guest_secrets.ensure_ssh_secret(7, instance)
    participant_ref, _ = gcp_guest_secrets.ensure_participant_ssh_secret(7, instance)

    assert host_ref != participant_ref
    assert secret_ids[0].endswith("-ssh")
    assert secret_ids[1].endswith("-participant-ssh")


@pytest.mark.parametrize(("strength", "expected_length"), [("weak", 12), ("medium", 18), ("strong", 24)])
def test_aces_account_password_strength_drives_generation(monkeypatch, strength: str, expected_length: int):
    generated_lengths: list[int] = []

    def generate(length: int) -> str:
        generated_lengths.append(length)
        return "x" * length

    monkeypatch.setattr(gcp_guest_secrets, "generate_rdp_password", generate)
    monkeypatch.setattr(
        gcp_guest_secrets,
        "_read_or_create_secret",
        lambda secret_id, payload_factory: (f"projects/p/secrets/{secret_id}", payload_factory()),
    )

    secret_ref, password = gcp_guest_secrets.ensure_aces_account_password_secret(7, "node.web#1", "Alice", strength)

    assert generated_lengths == [expected_length]
    assert password == "x" * expected_length
    assert secret_ref.endswith("-account-password")
    assert "node-web-1" in secret_ref


def test_aces_account_password_rejects_unknown_strength_before_secret_access(monkeypatch):
    read_or_create = MagicMock()
    monkeypatch.setattr(gcp_guest_secrets, "_read_or_create_secret", read_or_create)

    with pytest.raises(ValueError, match="unsupported password strength"):
        gcp_guest_secrets.ensure_aces_account_password_secret(7, "node.web#1", "alice", "none")

    read_or_create.assert_not_called()


def test_aces_account_public_key_stores_private_half_and_returns_public(monkeypatch):
    captured: dict[str, str] = {}

    def read_or_create(secret_id, payload_factory):
        captured["secret_id"] = secret_id
        captured["payload"] = payload_factory()
        return f"projects/p/secrets/{secret_id}", captured["payload"]

    monkeypatch.setattr(gcp_guest_secrets, "generate_ssh_keypair", lambda: ("PRIVATE", "PUBLIC"))
    monkeypatch.setattr(gcp_guest_secrets, "derive_ssh_public_key", lambda private: f"derived:{private}")
    monkeypatch.setattr(gcp_guest_secrets, "_read_or_create_secret", read_or_create)

    secret_ref, public_key = gcp_guest_secrets.ensure_aces_account_public_key_secret(9, "node.web#0", "alice")

    assert captured["payload"] == "PRIVATE"
    assert public_key == "derived:PRIVATE"
    assert secret_ref.endswith("-account-publickey")
    assert "PRIVATE" not in secret_ref


def test_account_secret_identity_distinguishes_case_sensitive_usernames():
    lower = gcp_guest_secrets._aces_account_secret_id(7, "node.web#0", "alice", "account-password")
    upper = gcp_guest_secrets._aces_account_secret_id(7, "node.web#0", "Alice", "account-password")

    assert lower != upper


def test_domain_secret_identity_is_deterministic_opaque_and_purpose_scoped():
    first = gcp_guest_secrets._aces_directory_secret_id(
        7, "corp.example", "provision.account.web-service", "account-password"
    )
    again = gcp_guest_secrets._aces_directory_secret_id(
        7, "corp.example", "provision.account.web-service", "account-password"
    )
    authority = gcp_guest_secrets._aces_directory_secret_id(7, "corp.example", "authority", "authority-password")

    assert first == again
    assert first != authority
    assert "corp" not in first
    assert "web-service" not in first
    assert "account-password" in first


@pytest.mark.parametrize(
    ("ensure_name", "args", "expected_length"),
    [
        ("ensure_aces_domain_dsrm_secret", (7, "corp"), 24),
        ("ensure_aces_domain_authority_secret", (7, "corp", "medium"), 18),
        (
            "ensure_aces_domain_account_password_secret",
            (7, "corp", "provision.account.web-service", "strong"),
            24,
        ),
    ],
)
def test_domain_password_secrets_reuse_read_or_create(
    monkeypatch, ensure_name: str, args: tuple[object, ...], expected_length: int
) -> None:
    captured: dict[str, object] = {}

    def read_or_create(secret_id, payload_factory):
        captured["secret_id"] = secret_id
        captured["value"] = payload_factory()
        return f"projects/p/secrets/{secret_id}", captured["value"]

    monkeypatch.setattr(gcp_guest_secrets, "generate_rdp_password", lambda length: "x" * length)
    monkeypatch.setattr(gcp_guest_secrets, "_read_or_create_secret", read_or_create)

    _secret_ref, value = getattr(gcp_guest_secrets, ensure_name)(*args)

    assert value == "x" * expected_length
    assert "corp" not in str(captured["secret_id"])


def test_delete_aces_account_secret_is_idempotent(monkeypatch):
    client = SimpleNamespace(delete_secret=MagicMock())
    exceptions = SimpleNamespace(NotFound=type("NotFound", (Exception,), {}))
    monkeypatch.setattr(gcp_guest_secrets, "_secret_client", lambda: (client, exceptions, "project-1"))

    gcp_guest_secrets.delete_aces_account_secret(7, "node.web#0", "alice", "publickey")

    deleted_name = client.delete_secret.call_args.kwargs["request"]["name"]
    assert deleted_name.endswith("-account-publickey")
    assert "alice" in deleted_name


def test_read_or_create_uses_concurrent_winner_instead_of_rotating_secret(monkeypatch):
    class NotFound(Exception):
        pass

    class AlreadyExists(Exception):
        pass

    client = SimpleNamespace(
        access_secret_version=MagicMock(
            side_effect=[NotFound(), SimpleNamespace(payload=SimpleNamespace(data=b"WINNER"))]
        ),
        create_secret=MagicMock(side_effect=AlreadyExists()),
        add_secret_version=MagicMock(),
    )
    exceptions = SimpleNamespace(NotFound=NotFound, AlreadyExists=AlreadyExists)
    monkeypatch.setattr(gcp_guest_secrets, "_secret_client", lambda: (client, exceptions, "project-1"))

    secret_ref, value = gcp_guest_secrets._read_or_create_secret("secret-id", lambda: "LOSER")

    assert secret_ref == "projects/project-1/secrets/secret-id"
    assert value == "WINNER"
    client.add_secret_version.assert_not_called()


def test_read_or_create_waits_for_concurrent_winner_version(monkeypatch):
    class NotFound(Exception):
        pass

    class AlreadyExists(Exception):
        pass

    client = SimpleNamespace(
        access_secret_version=MagicMock(
            side_effect=[
                NotFound(),
                NotFound(),
                SimpleNamespace(payload=SimpleNamespace(data=b"WINNER")),
            ]
        ),
        create_secret=MagicMock(side_effect=AlreadyExists()),
        add_secret_version=MagicMock(),
    )
    exceptions = SimpleNamespace(NotFound=NotFound, AlreadyExists=AlreadyExists)
    sleep = MagicMock()
    monkeypatch.setattr(gcp_guest_secrets, "_secret_client", lambda: (client, exceptions, "project-1"))
    monkeypatch.setattr(gcp_guest_secrets.time, "sleep", sleep)

    _secret_ref, value = gcp_guest_secrets._read_or_create_secret("secret-id", lambda: "LOSER")

    assert value == "WINNER"
    sleep.assert_called_once_with(0.1)
    client.add_secret_version.assert_not_called()
