"""Tests for the per-range Vertex agent credential lifecycle."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from gcp_range_vertex_creds import delete_range_vertex_key, ensure_range_vertex_key


class NotFound(Exception):
    """Fake google.api_core NotFound."""


class AlreadyExists(Exception):
    """Fake google.api_core AlreadyExists."""


_EXCEPTIONS = SimpleNamespace(NotFound=NotFound, AlreadyExists=AlreadyExists)

_KEY_JSON = json.dumps(
    {
        "type": "service_account",
        "client_email": "range-vertex@proj.iam.gserviceaccount.com",
        "private_key_id": "abc123",
    }
)


def _secret_client(*, exists: bool):
    client = SimpleNamespace()
    if exists:
        client.access_secret_version = lambda *, request: SimpleNamespace(
            payload=SimpleNamespace(data=_KEY_JSON.encode("utf-8"))
        )
    else:

        def _raise(*, request):
            raise NotFound()

        client.access_secret_version = _raise
    client.create_secret = lambda *, request: None
    client.add_secret_version = lambda *, request: None
    client.set_iam_policy = lambda *, request: None
    client.delete_secret = lambda *, request: None
    return client


def test_ensure_mints_key_and_stores_secret_when_absent(mocker):
    iam = SimpleNamespace(
        create_service_account_key=mocker.Mock(
            return_value=SimpleNamespace(
                name="projects/-/serviceAccounts/x/keys/abc123", private_key_data=_KEY_JSON.encode()
            )
        )
    )
    secrets = _secret_client(exists=False)
    add_version = mocker.spy(secrets, "add_secret_version")

    ref = ensure_range_vertex_key(
        42,
        "range-vertex@proj.iam.gserviceaccount.com",
        iam_client=iam,
        secret_client=secrets,
        google_exceptions=_EXCEPTIONS,
        project_id="proj",
    )

    assert ref == "projects/proj/secrets/shifter-range-42-vertex-key"
    iam.create_service_account_key.assert_called_once()
    add_version.assert_called_once()


def test_ensure_grants_host_sa_scoped_secret_access(mocker):
    iam = SimpleNamespace(
        create_service_account_key=mocker.Mock(
            return_value=SimpleNamespace(
                name="projects/-/serviceAccounts/x/keys/abc123", private_key_data=_KEY_JSON.encode()
            )
        )
    )
    secrets = _secret_client(exists=False)
    set_policy = mocker.spy(secrets, "set_iam_policy")

    ensure_range_vertex_key(
        42,
        "range-vertex@proj.iam.gserviceaccount.com",
        iam_client=iam,
        secret_client=secrets,
        google_exceptions=_EXCEPTIONS,
        project_id="proj",
        host_service_account_email="range-host@proj.iam.gserviceaccount.com",
    )

    set_policy.assert_called_once()
    request = set_policy.call_args.kwargs["request"]
    assert request["resource"] == "projects/proj/secrets/shifter-range-42-vertex-key"
    binding = request["policy"]["bindings"][0]
    assert binding["role"] == "roles/secretmanager.secretAccessor"
    assert binding["members"] == ["serviceAccount:range-host@proj.iam.gserviceaccount.com"]


def test_ensure_skips_host_grant_when_no_host_sa(mocker):
    iam = SimpleNamespace(
        create_service_account_key=mocker.Mock(
            return_value=SimpleNamespace(
                name="projects/-/serviceAccounts/x/keys/abc123", private_key_data=_KEY_JSON.encode()
            )
        )
    )
    secrets = _secret_client(exists=False)
    set_policy = mocker.spy(secrets, "set_iam_policy")

    ensure_range_vertex_key(
        42,
        "range-vertex@proj.iam.gserviceaccount.com",
        iam_client=iam,
        secret_client=secrets,
        google_exceptions=_EXCEPTIONS,
        project_id="proj",
    )

    set_policy.assert_not_called()


def test_ensure_is_idempotent_when_secret_exists(mocker):
    iam = SimpleNamespace(create_service_account_key=mocker.Mock())
    secrets = _secret_client(exists=True)

    ref = ensure_range_vertex_key(
        42,
        "range-vertex@proj.iam.gserviceaccount.com",
        iam_client=iam,
        secret_client=secrets,
        google_exceptions=_EXCEPTIONS,
        project_id="proj",
    )

    assert ref == "projects/proj/secrets/shifter-range-42-vertex-key"
    iam.create_service_account_key.assert_not_called()


def test_ensure_requires_service_account_email():
    with pytest.raises(RuntimeError, match="Vertex service account"):
        ensure_range_vertex_key(42, "", google_exceptions=_EXCEPTIONS, project_id="proj")


def test_delete_removes_key_and_secret(mocker):
    iam = SimpleNamespace(delete_service_account_key=mocker.Mock())
    secrets = _secret_client(exists=True)
    delete_secret = mocker.spy(secrets, "delete_secret")

    delete_range_vertex_key(
        42,
        iam_client=iam,
        secret_client=secrets,
        google_exceptions=_EXCEPTIONS,
        project_id="proj",
    )

    iam.delete_service_account_key.assert_called_once_with(
        request={"name": "projects/-/serviceAccounts/range-vertex@proj.iam.gserviceaccount.com/keys/abc123"}
    )
    delete_secret.assert_called_once()


def test_delete_is_noop_when_secret_absent(mocker):
    iam = SimpleNamespace(delete_service_account_key=mocker.Mock())
    secrets = _secret_client(exists=False)

    delete_range_vertex_key(
        42,
        iam_client=iam,
        secret_client=secrets,
        google_exceptions=_EXCEPTIONS,
        project_id="proj",
    )

    iam.delete_service_account_key.assert_not_called()
