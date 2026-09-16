"""Tests for the deployment-scoped GCP dynamic-secret contract."""

from __future__ import annotations

import inspect

import pytest

import gcp_dynamic_secrets
from _gdc_vm_secrets import _instance_secret_locations
from gdc_vmseries_assets import _ssh_secret_locations


class _NotFound(Exception):
    pass


class _AlreadyExists(Exception):
    pass


class _Unavailable(Exception):
    pass


def test_canonical_secret_id_encodes_centrally_classified_name(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "gcp-dev")

    secret_id = gcp_dynamic_secrets.canonical_secret_id(
        credential_class=gcp_dynamic_secrets.DynamicSecretClass.GCE_PARTICIPANT_SSH,
        scope="range-42-node-web-0",
    )

    assert secret_id == "shifter-gcp-dev-dynamic-participant-gce-range-42-node-web-0-ssh"


def test_canonical_secret_id_rejects_unknown_credential_class():
    with pytest.raises(ValueError, match="credential class"):
        gcp_dynamic_secrets.canonical_secret_id(
            credential_class="future-participant-secret",
            scope="range-42-node-web-0",
        )


def test_canonical_secret_id_does_not_accept_caller_selected_audience():
    parameters = inspect.signature(gcp_dynamic_secrets.canonical_secret_id).parameters

    assert "credential_class" in parameters
    assert "audience" not in parameters
    assert "family" not in parameters
    assert "purpose" not in parameters


def test_every_declared_credential_class_is_centrally_mapped():
    assert set(gcp_dynamic_secrets._DYNAMIC_SECRET_NAME_CLASSES) == set(gcp_dynamic_secrets.DynamicSecretClass)
    assert set(gcp_dynamic_secrets.DynamicSecretClass) >= gcp_dynamic_secrets._PARTICIPANT_SECRET_CLASSES


@pytest.mark.parametrize(
    ("credential_class", "expected_name"),
    [
        (gcp_dynamic_secrets.DynamicSecretClass.GCE_HOST_SSH, "workload-gce-scope-ssh"),
        (gcp_dynamic_secrets.DynamicSecretClass.GCE_PARTICIPANT_SSH, "participant-gce-scope-ssh"),
        (gcp_dynamic_secrets.DynamicSecretClass.GCE_RDP_PASSWORD, "participant-gce-scope-rdp-password"),
        (gcp_dynamic_secrets.DynamicSecretClass.RAES_HOST_SSH, "workload-raes-scope-ssh"),
        (
            gcp_dynamic_secrets.DynamicSecretClass.RAES_ACCOUNT_PASSWORD,
            "participant-raes-scope-account-password",
        ),
        (
            gcp_dynamic_secrets.DynamicSecretClass.RAES_ACCOUNT_PUBLIC_KEY,
            "participant-raes-scope-account-publickey",
        ),
        (
            gcp_dynamic_secrets.DynamicSecretClass.RAES_DOMAIN_DSRM_PASSWORD,
            "workload-raes-scope-dsrm-password",
        ),
        (
            gcp_dynamic_secrets.DynamicSecretClass.RAES_DOMAIN_AUTHORITY_PASSWORD,
            "workload-raes-scope-authority-password",
        ),
        (
            gcp_dynamic_secrets.DynamicSecretClass.RAES_DOMAIN_ACCOUNT_PASSWORD,
            "workload-raes-scope-account-password",
        ),
        (gcp_dynamic_secrets.DynamicSecretClass.GDC_VM_SSH, "participant-gdc-vm-scope-ssh"),
        (
            gcp_dynamic_secrets.DynamicSecretClass.GDC_VM_RDP_PASSWORD,
            "participant-gdc-vm-scope-rdp-password",
        ),
        (gcp_dynamic_secrets.DynamicSecretClass.VMSERIES_SSH, "participant-vmseries-scope-ssh"),
        (
            gcp_dynamic_secrets.DynamicSecretClass.VERTEX_SERVICE_ACCOUNT_KEY,
            "workload-vertex-scope-service-account-key",
        ),
        (gcp_dynamic_secrets.DynamicSecretClass.VPN_ISSUER, "workload-vpn-scope-issuer"),
        (gcp_dynamic_secrets.DynamicSecretClass.VPN_SERVER, "workload-vpn-scope-server"),
        (gcp_dynamic_secrets.DynamicSecretClass.VPN_PROFILE, "participant-vpn-scope-profile"),
    ],
)
def test_every_credential_class_has_one_closed_name_and_audience(monkeypatch, credential_class, expected_name):
    monkeypatch.setenv("ENVIRONMENT", "gcp-dev")

    secret_id = gcp_dynamic_secrets.canonical_secret_id(
        credential_class=credential_class,
        scope="scope",
    )

    assert secret_id == f"shifter-gcp-dev-dynamic-{expected_name}"


def test_canonical_secret_id_requires_explicit_environment(monkeypatch):
    monkeypatch.delenv("ENVIRONMENT", raising=False)

    with pytest.raises(RuntimeError, match="ENVIRONMENT"):
        gcp_dynamic_secrets.canonical_secret_id(
            credential_class=gcp_dynamic_secrets.DynamicSecretClass.GCE_HOST_SSH,
            scope="range-42-node-web-0",
        )


@pytest.mark.parametrize("environment", ["", " ", " gcp-dev ", "GCP Dev", "gcp--dev"])
def test_canonical_secret_id_rejects_invalid_environment(environment):
    with pytest.raises(ValueError, match="environment"):
        gcp_dynamic_secrets.canonical_secret_id(
            environment=environment,
            credential_class=gcp_dynamic_secrets.DynamicSecretClass.GCE_HOST_SSH,
            scope="range-42-node-web-0",
        )


def test_canonical_secret_id_hashes_full_identity_when_truncated(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "gcp-dev")
    common = "node-" + "x" * 300

    first = gcp_dynamic_secrets.canonical_secret_id(
        credential_class=gcp_dynamic_secrets.DynamicSecretClass.RAES_DOMAIN_ACCOUNT_PASSWORD,
        scope=common + "-first",
    )
    second = gcp_dynamic_secrets.canonical_secret_id(
        credential_class=gcp_dynamic_secrets.DynamicSecretClass.RAES_DOMAIN_ACCOUNT_PASSWORD,
        scope=common + "-second",
    )

    assert len(first) <= 255
    assert len(second) <= 255
    assert first != second


def test_locations_keep_legacy_name_while_projects_are_the_same():
    locations = gcp_dynamic_secrets.secret_locations(
        platform_project_id="platform-project",
        dynamic_project_id="platform-project",
        legacy_secret_id="shifter-range-42-node-web-0-ssh",
        canonical_secret_id="shifter-dev-dynamic-workload-gce-range-42-node-web-0-ssh",
    )

    assert locations.read_refs == ("projects/platform-project/secrets/shifter-range-42-node-web-0-ssh",)
    assert locations.create_ref == locations.read_refs[0]
    assert locations.delete_refs == locations.read_refs


def test_locations_read_legacy_before_canonical_and_delete_both_after_project_split():
    locations = gcp_dynamic_secrets.secret_locations(
        platform_project_id="platform-project",
        dynamic_project_id="range-secrets-project",
        legacy_secret_id="shifter-range-42-node-web-0-ssh",
        canonical_secret_id="shifter-dev-dynamic-workload-gce-range-42-node-web-0-ssh",
    )

    assert locations.read_refs == (
        "projects/platform-project/secrets/shifter-range-42-node-web-0-ssh",
        "projects/range-secrets-project/secrets/shifter-dev-dynamic-workload-gce-range-42-node-web-0-ssh",
    )
    assert locations.create_ref == locations.read_refs[1]
    assert locations.delete_refs == locations.read_refs


def test_dynamic_project_must_be_explicit_even_when_platform_project_is_known(monkeypatch):
    monkeypatch.delenv("GCP_DYNAMIC_SECRET_PROJECT_ID", raising=False)

    with pytest.raises(RuntimeError, match="GCP_DYNAMIC_SECRET_PROJECT_ID"):
        gcp_dynamic_secrets.dynamic_secret_project_id()


def test_dynamic_project_allows_explicit_same_project_migration(monkeypatch):
    monkeypatch.setenv("GCP_DYNAMIC_SECRET_PROJECT_ID", "platform-project")

    assert gcp_dynamic_secrets.dynamic_secret_project_id() == "platform-project"


def test_read_or_create_refuses_to_publish_into_an_existing_empty_container(mocker):
    locations = gcp_dynamic_secrets.SecretLocations(
        read_refs=(
            "projects/platform/secrets/legacy",
            "projects/dynamic/secrets/canonical",
        ),
        create_ref="projects/dynamic/secrets/canonical",
        delete_refs=(
            "projects/platform/secrets/legacy",
            "projects/dynamic/secrets/canonical",
        ),
    )
    client = mocker.Mock()
    client.access_secret_version.side_effect = _NotFound()
    client.get_secret.side_effect = _NotFound()
    client.create_secret.side_effect = _AlreadyExists()
    factory = mocker.Mock(return_value="competing-value")
    exceptions = type("Exceptions", (), {"NotFound": _NotFound, "AlreadyExists": _AlreadyExists})
    retry_settings = gcp_dynamic_secrets.SecretRetrySettings(concurrent_read_attempts=1)

    with pytest.raises(gcp_dynamic_secrets.DynamicSecretPublicationPending):
        gcp_dynamic_secrets.read_or_create(
            client,
            exceptions,
            locations,
            factory,
            retry_settings=retry_settings,
        )

    factory.assert_not_called()
    assert client.create_secret.call_args.kwargs["request"]["parent"] == "projects/dynamic"
    client.add_secret_version.assert_not_called()


def test_read_or_create_waits_for_an_empty_legacy_container_before_canonical_create(mocker):
    legacy = "projects/platform/secrets/legacy"
    canonical = "projects/dynamic/secrets/canonical"
    locations = gcp_dynamic_secrets.SecretLocations(
        read_refs=(legacy, canonical),
        create_ref=canonical,
        delete_refs=(legacy, canonical),
    )
    client = mocker.Mock()
    client.access_secret_version.side_effect = _NotFound()
    client.get_secret.return_value = object()
    factory = mocker.Mock(return_value="competing-value")
    exceptions = type("Exceptions", (), {"NotFound": _NotFound, "AlreadyExists": _AlreadyExists})
    retry_settings = gcp_dynamic_secrets.SecretRetrySettings(concurrent_read_attempts=1)

    with pytest.raises(gcp_dynamic_secrets.DynamicSecretPublicationPending):
        gcp_dynamic_secrets.read_or_create(
            client,
            exceptions,
            locations,
            factory,
            retry_settings=retry_settings,
        )

    client.get_secret.assert_called_once_with(request={"name": legacy})
    client.create_secret.assert_not_called()
    client.add_secret_version.assert_not_called()
    factory.assert_not_called()


def test_concurrent_loser_reuses_winner_payload_without_minting_an_orphan(mocker):
    locations = gcp_dynamic_secrets.SecretLocations(
        read_refs=("projects/dynamic/secrets/canonical",),
        create_ref="projects/dynamic/secrets/canonical",
        delete_refs=("projects/dynamic/secrets/canonical",),
    )
    response = mocker.Mock()
    response.payload.data = b"winner-value"
    client = mocker.Mock()
    client.access_secret_version.side_effect = [_NotFound(), response]
    client.get_secret.side_effect = _NotFound()
    client.create_secret.side_effect = _AlreadyExists()
    factory = mocker.Mock(return_value="loser-value")

    ref, value = gcp_dynamic_secrets.read_or_create(
        client,
        type("Exceptions", (), {"NotFound": _NotFound, "AlreadyExists": _AlreadyExists}),
        locations,
        factory,
        retry_settings=gcp_dynamic_secrets.SecretRetrySettings(concurrent_read_attempts=1),
    )

    assert ref == locations.create_ref
    assert value == "winner-value"
    factory.assert_not_called()
    client.add_secret_version.assert_not_called()


def test_dynamic_project_unavailability_never_falls_back_to_platform(mocker):
    locations = gcp_dynamic_secrets.SecretLocations(
        read_refs=(
            "projects/platform/secrets/legacy",
            "projects/dynamic/secrets/canonical",
        ),
        create_ref="projects/dynamic/secrets/canonical",
        delete_refs=(
            "projects/platform/secrets/legacy",
            "projects/dynamic/secrets/canonical",
        ),
    )
    client = mocker.Mock()
    client.access_secret_version.side_effect = _NotFound()
    client.get_secret.side_effect = _NotFound()
    client.create_secret.side_effect = _Unavailable("dynamic project unavailable")
    factory = mocker.Mock(return_value="must-not-be-generated")

    try:
        gcp_dynamic_secrets.read_or_create(
            client,
            type("Exceptions", (), {"NotFound": _NotFound, "AlreadyExists": _AlreadyExists}),
            locations,
            factory,
        )
    except _Unavailable:
        pass
    else:
        raise AssertionError("dynamic-project failure must propagate")

    factory.assert_not_called()
    assert client.create_secret.call_args.kwargs["request"]["parent"] == "projects/dynamic"
    client.add_secret_version.assert_not_called()


def test_read_or_create_retries_transient_version_publication_with_one_payload(mocker):
    locations = gcp_dynamic_secrets.SecretLocations(
        read_refs=("projects/dynamic/secrets/canonical",),
        create_ref="projects/dynamic/secrets/canonical",
        delete_refs=("projects/dynamic/secrets/canonical",),
    )
    client = mocker.Mock()
    client.access_secret_version.side_effect = _NotFound()
    client.get_secret.side_effect = _NotFound()
    client.add_secret_version.side_effect = [_Unavailable(), None]
    factory = mocker.Mock(return_value="stable-value")

    ref, value = gcp_dynamic_secrets.read_or_create(
        client,
        type(
            "Exceptions",
            (),
            {
                "NotFound": _NotFound,
                "AlreadyExists": _AlreadyExists,
                "ServiceUnavailable": _Unavailable,
            },
        ),
        locations,
        factory,
        retry_settings=gcp_dynamic_secrets.SecretRetrySettings(version_add_delay_seconds=0),
    )

    assert ref == locations.create_ref
    assert value == "stable-value"
    factory.assert_called_once_with()
    assert client.add_secret_version.call_count == 2
    assert {call.kwargs["request"]["payload"]["data"] for call in client.add_secret_version.call_args_list} == {
        b"stable-value"
    }


def test_gdc_vm_and_vmseries_families_use_participant_names_in_dedicated_project(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "gcp-dev")
    monkeypatch.setenv("GCP_DYNAMIC_SECRET_PROJECT_ID", "range-secrets")

    gdc = _instance_secret_locations(
        "platform-project",
        42,
        {"uuid": "node-uuid", "role": "victim"},
        "rdp-password",
    )
    vmseries = _ssh_secret_locations("platform-project", 7, "firewall-uuid")

    assert gdc.create_ref == (
        "projects/range-secrets/secrets/shifter-gcp-dev-dynamic-participant-gdc-vm-range-42-node-uuid-rdp-password"
    )
    assert vmseries.create_ref == (
        "projects/range-secrets/secrets/shifter-gcp-dev-dynamic-participant-vmseries-user-7-firewall-uuid-ssh"
    )
    assert gdc.read_refs[0].startswith("projects/platform-project/secrets/")
    assert vmseries.read_refs[0].startswith("projects/platform-project/secrets/")
