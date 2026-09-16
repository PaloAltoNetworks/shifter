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


@pytest.fixture(autouse=True)
def _explicit_dynamic_secret_project(monkeypatch):
    """Exercise the supported same-project migration posture explicitly."""
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("GCP_DYNAMIC_SECRET_PROJECT_ID", "proj")


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

    def _get_secret(*, request):
        raise NotFound()

    client.get_secret = _get_secret
    client.create_secret = lambda *, request: None
    client.add_secret_version = lambda *, request: None
    client.get_iam_policy = lambda *, request: {"bindings": []}
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


def test_ensure_repairs_host_grant_when_secret_version_already_exists(mocker):
    iam = SimpleNamespace(create_service_account_key=mocker.Mock())
    secrets = _secret_client(exists=True)
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

    iam.create_service_account_key.assert_not_called()
    set_policy.assert_called_once()


def test_ensure_uses_dedicated_storage_project_but_reads_shared_key_from_vertex_project(mocker, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "gcp-dev")
    monkeypatch.setenv("GCP_DYNAMIC_SECRET_PROJECT_ID", "range-secrets")
    monkeypatch.setenv("GCP_RANGE_VERTEX_SHARED_KEY_SECRET_ID", "shared-vertex-key")
    monkeypatch.setenv("GCP_RANGE_VERTEX_PROJECT_ID", "vertex-project")
    iam = SimpleNamespace(create_service_account_key=mocker.Mock())
    secrets = _secret_client(exists=False)
    accesses: list[str] = []

    def _access(*, request):
        accesses.append(request["name"])
        if request["name"] == "projects/vertex-project/secrets/shared-vertex-key/versions/latest":
            return SimpleNamespace(payload=SimpleNamespace(data=_KEY_JSON.encode("utf-8")))
        raise NotFound()

    secrets.access_secret_version = _access
    create = mocker.spy(secrets, "create_secret")

    ref = ensure_range_vertex_key(
        42,
        "range-vertex@vertex-project.iam.gserviceaccount.com",
        iam_client=iam,
        secret_client=secrets,
        google_exceptions=_EXCEPTIONS,
        project_id="compute-project",
    )

    assert ref == "projects/range-secrets/secrets/shifter-gcp-dev-dynamic-workload-vertex-range-42-service-account-key"
    assert "projects/vertex-project/secrets/shared-vertex-key/versions/latest" in accesses
    assert create.call_args.kwargs["request"]["parent"] == "projects/range-secrets"


def test_ensure_copies_shared_key_without_minting_service_account_key(mocker, monkeypatch):
    monkeypatch.setenv("GCP_RANGE_VERTEX_SHARED_KEY_SECRET_ID", "shared-vertex-key")
    iam = SimpleNamespace(create_service_account_key=mocker.Mock())
    secrets = _secret_client(exists=False)

    def _access(*, request):
        if request["name"] == "projects/proj/secrets/shared-vertex-key/versions/latest":
            return SimpleNamespace(payload=SimpleNamespace(data=_KEY_JSON.encode("utf-8")))
        raise NotFound()

    secrets.access_secret_version = _access
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
    iam.create_service_account_key.assert_not_called()
    assert add_version.call_args.kwargs["request"]["payload"]["data"] == _KEY_JSON.encode("utf-8")


def test_ensure_requires_service_account_email():
    with pytest.raises(RuntimeError, match="Vertex service account"):
        ensure_range_vertex_key(42, "", google_exceptions=_EXCEPTIONS, project_id="proj")


def test_ensure_revokes_new_key_when_version_publication_definitively_fails(mocker):
    iam = SimpleNamespace(
        create_service_account_key=mocker.Mock(
            return_value=SimpleNamespace(
                name="projects/-/serviceAccounts/x/keys/abc123",
                private_key_data=_KEY_JSON.encode(),
            )
        ),
        delete_service_account_key=mocker.Mock(),
    )
    secrets = _secret_client(exists=False)
    secrets.add_secret_version = mocker.Mock(side_effect=RuntimeError("publication failed"))

    with pytest.raises(RuntimeError, match="publication failed"):
        ensure_range_vertex_key(
            42,
            "range-vertex@proj.iam.gserviceaccount.com",
            iam_client=iam,
            secret_client=secrets,
            google_exceptions=_EXCEPTIONS,
            project_id="proj",
        )

    iam.delete_service_account_key.assert_called_once_with(request={"name": "projects/-/serviceAccounts/x/keys/abc123"})


def test_ensure_recovers_when_version_was_committed_before_error_response(mocker):
    iam = SimpleNamespace(
        create_service_account_key=mocker.Mock(
            return_value=SimpleNamespace(
                name="projects/-/serviceAccounts/x/keys/abc123",
                private_key_data=_KEY_JSON.encode(),
            )
        ),
        delete_service_account_key=mocker.Mock(),
    )
    secrets = _secret_client(exists=False)
    secrets.access_secret_version = mocker.Mock(
        side_effect=[
            NotFound(),
            SimpleNamespace(payload=SimpleNamespace(data=_KEY_JSON.encode())),
        ]
    )
    secrets.add_secret_version = mocker.Mock(side_effect=RuntimeError("response lost"))

    ref = ensure_range_vertex_key(
        42,
        "range-vertex@proj.iam.gserviceaccount.com",
        iam_client=iam,
        secret_client=secrets,
        google_exceptions=_EXCEPTIONS,
        project_id="proj",
    )

    assert ref == "projects/proj/secrets/shifter-range-42-vertex-key"
    iam.delete_service_account_key.assert_not_called()


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


def test_delete_revokes_keys_from_both_legacy_and_canonical_migration_locations(mocker, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "gcp-dev")
    monkeypatch.setenv("GCP_DYNAMIC_SECRET_PROJECT_ID", "range-secrets")
    legacy_key = _KEY_JSON.encode()
    canonical_key = json.dumps(
        {
            "type": "service_account",
            "client_email": "range-vertex@proj.iam.gserviceaccount.com",
            "private_key_id": "def456",
        }
    ).encode()
    iam = SimpleNamespace(delete_service_account_key=mocker.Mock())
    secrets = _secret_client(exists=True)
    secrets.access_secret_version = mocker.Mock(
        side_effect=[
            SimpleNamespace(payload=SimpleNamespace(data=legacy_key)),
            SimpleNamespace(payload=SimpleNamespace(data=canonical_key)),
        ]
    )
    delete_secret = mocker.spy(secrets, "delete_secret")

    delete_range_vertex_key(
        42,
        iam_client=iam,
        secret_client=secrets,
        google_exceptions=_EXCEPTIONS,
        project_id="proj",
    )

    assert {call.kwargs["request"]["name"] for call in iam.delete_service_account_key.call_args_list} == {
        "projects/-/serviceAccounts/range-vertex@proj.iam.gserviceaccount.com/keys/abc123",
        "projects/-/serviceAccounts/range-vertex@proj.iam.gserviceaccount.com/keys/def456",
    }
    assert {call.kwargs["request"]["name"] for call in delete_secret.call_args_list} == {
        "projects/proj/secrets/shifter-range-42-vertex-key",
        "projects/range-secrets/secrets/shifter-gcp-dev-dynamic-workload-vertex-range-42-service-account-key",
    }


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


def test_delete_shared_key_mode_removes_only_range_secret(mocker, monkeypatch):
    monkeypatch.setenv("GCP_RANGE_VERTEX_SHARED_KEY_SECRET_ID", "shared-vertex-key")
    iam = SimpleNamespace(delete_service_account_key=mocker.Mock())
    secrets = _secret_client(exists=True)
    access_secret = mocker.spy(secrets, "access_secret_version")
    delete_secret = mocker.spy(secrets, "delete_secret")

    delete_range_vertex_key(
        42,
        iam_client=iam,
        secret_client=secrets,
        google_exceptions=_EXCEPTIONS,
        project_id="proj",
    )

    access_secret.assert_not_called()
    iam.delete_service_account_key.assert_not_called()
    delete_secret.assert_called_once_with(request={"name": "projects/proj/secrets/shifter-range-42-vertex-key"})
