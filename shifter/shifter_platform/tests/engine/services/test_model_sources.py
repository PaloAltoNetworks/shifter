"""Tenant source registration and spending permission are separate authorities."""

import json
from dataclasses import asdict
from unittest.mock import Mock

import pytest
from django.contrib.auth.models import User

from shared.model_access import ContractError
from workspaces.models import Organization, OrganizationMembership, Workspace, WorkspaceMembership
from workspaces.services import OrganizationAuthorizationError

pytestmark = pytest.mark.django_db


@pytest.fixture
def source_tenant(monkeypatch):
    admin = User.objects.create_user(username="source-admin")
    member = User.objects.create_user(username="source-user")
    organization = Organization.objects.create(name="Source tenant")
    OrganizationMembership.objects.create(user=admin, organization=organization, role="admin")
    workspace = Workspace.objects.create(organization=organization, name="Workshop")
    WorkspaceMembership.objects.create(user=member, workspace=workspace, role="member")
    store = Mock()
    store.create_owned_secret.return_value = "projects/platform-example/secrets/server-owned/versions/1"
    monkeypatch.setattr("shared.cloud.get_secrets_store", lambda: store)
    return admin, member, organization, store


def configuration(**overrides):
    return {
        "name": "Workshop model",
        "provider": "anthropic-v1",
        "model": "claude-synthetic-20260901",
        "region": "provider-managed",
        "authentication": "stored-credential",
        "quota_identity": "account:workshop",
        "input_price_per_million": 1_000_000,
        "output_price_per_million": 3_000_000,
        "price_valid_until": "2027-10-01T00:00:00Z",
        "context_window_tokens": 200_000,
        "tokens_per_minute": 100_000,
        **overrides,
    }


def test_admin_registration_is_metadata_only_and_does_not_grant_spending(source_tenant):
    from cms.services import list_usable_model_sources
    from engine.services import create_model_source

    admin, member, org, store = source_tenant
    source = create_model_source(admin, org.uuid, configuration(), credential={"api_key": "synthetic-secret"})
    assert source.revision == 1
    assert source.state == "ready"
    rendered = json.dumps(asdict(source), default=str)
    assert "synthetic-secret" not in rendered and "server-owned" not in rendered
    assert list_usable_model_sources(member, org.uuid) == ()
    assert list_usable_model_sources(admin, org.uuid) == ()
    assert store.create_owned_secret.call_count == 1


def test_source_use_and_edit_recheck_tenant_and_revision(source_tenant):
    from cms.services import list_usable_model_sources
    from engine.services import create_model_source, update_model_source

    admin, member, org, store = source_tenant
    source = create_model_source(
        admin, org.uuid, configuration(allow_organization_members=True), credential={"api_key": "synthetic-secret"}
    )
    assert [item.id for item in list_usable_model_sources(member, org.uuid)] == [source.id]
    outsider = User.objects.create_user(username="foreign-admin", is_staff=True)
    with pytest.raises(OrganizationAuthorizationError):
        update_model_source(outsider, org.uuid, source.id, expected_revision=1, configuration=configuration())
    with pytest.raises(ContractError, match=r"source\.revision_conflict"):
        update_model_source(admin, org.uuid, source.id, expected_revision=0, configuration=configuration())
    assert store.create_owned_secret.call_count == 1
    updated = update_model_source(admin, org.uuid, source.id, expected_revision=1, configuration=configuration())
    assert updated.revision == 2
    assert list_usable_model_sources(member, org.uuid) == ()
    assert store.create_owned_secret.call_count == 1  # metadata edits retain the pinned credential


def test_failed_credential_write_leaves_a_reconcilable_unavailable_revision(source_tenant):
    from cms.services import list_usable_model_sources
    from engine.models import ModelSourceRevision
    from engine.services import create_model_source
    from shared.cloud.exceptions import CloudSecretsError

    admin, member, org, store = source_tenant
    store.create_owned_secret.side_effect = CloudSecretsError("provider detail must not escape")
    with pytest.raises(ContractError, match=r"source\.credential_unavailable"):
        create_model_source(
            admin, org.uuid, configuration(allow_organization_members=True), credential={"api_key": "synthetic-secret"}
        )
    revision = ModelSourceRevision.objects.get()
    assert revision.state == "failed"
    assert revision.credential_version is not None
    assert list_usable_model_sources(member, org.uuid) == ()


def test_source_revision_change_fences_existing_grants_without_erasing_liability(source_tenant):
    from engine.models import ModelAllocationAuthority, SharingAuthorityFence
    from engine.services import create_model_source, update_model_source

    from .test_model_request_accounting import make_reservable_allocation

    admin, _, org, _ = source_tenant
    source = create_model_source(admin, org.uuid, configuration(), credential={"api_key": "synthetic-secret"})
    allocation = make_reservable_allocation()
    fence = SharingAuthorityFence.objects.create(
        deployment_id=allocation.deployment_id,
        authority_owner="engine",
        authority_reference=f"model-source:{source.id}",
        authority_revision=1,
        state="allowed",
    )
    ModelAllocationAuthority.objects.create(allocation=allocation, fence=fence, revision=1)
    allocation.unresolved_liabilities = 1
    allocation.save(update_fields=["unresolved_liabilities"])
    update_model_source(admin, org.uuid, source.id, expected_revision=1, configuration=configuration(), enabled=False)
    allocation.grant.refresh_from_db()
    assert allocation.grant.state == "revoked"
    allocation.refresh_from_db()
    assert allocation.unresolved_liabilities == 1


def test_launch_selection_requires_current_source_use_permission(source_tenant):
    from uuid import uuid4

    from cms.services import resolve_model_source_selection
    from engine.services import create_model_source
    from shared.model_access.sources import ModelSourceSelection

    admin, member, org, _ = source_tenant
    base = direct_source_catalog(uuid4())
    source = create_model_source(
        admin,
        org.uuid,
        configuration(region="provider-managed", allow_organization_members=True),
        credential={"api_key": "synthetic-secret"},
    )
    selection = ModelSourceSelection.model_validate(
        {"aliases": [{"logical_alias": "coding-main", "sources": [{"source_id": str(source.id), "revision": 1}]}]}
    )
    compiled, revisions = resolve_model_source_selection(member, org.uuid, selection, catalog=base)
    assert compiled.digest != base.digest
    assert any(item.authority_ref.reference == f"model-source:{source.id}" for item in revisions)
    stale = selection.model_dump(mode="json")
    stale["aliases"][0]["sources"][0]["revision"] = 2
    with pytest.raises(ContractError):
        resolve_model_source_selection(member, org.uuid, ModelSourceSelection.model_validate(stale), catalog=base)
    WorkspaceMembership.objects.filter(user=member).delete()
    with pytest.raises(OrganizationAuthorizationError):
        resolve_model_source_selection(member, org.uuid, selection, catalog=base)


def direct_source_catalog(deployment_id):
    """Synthetic policy explicitly approves provider-managed routing."""
    from shared.model_access import seal_catalog

    from .test_model_request_accounting import seal_v3_catalog

    payload = seal_v3_catalog(deployment_id).model_dump(mode="json")
    for profile in payload["profiles"]:
        profile["data_regions"].append("provider-managed")
    return seal_catalog(payload)


def test_obsolete_owned_credentials_retire_without_removing_current_version(source_tenant):
    from datetime import timedelta

    from django.utils import timezone

    from engine.models import ModelSourceRevision
    from engine.services import create_model_source, retire_unused_model_source_credentials, update_model_source
    from shared.cloud.exceptions import CloudSecretsError

    admin, _, org, store = source_tenant
    source = create_model_source(admin, org.uuid, configuration(), credential={"api_key": "synthetic-old"})
    old = ModelSourceRevision.objects.get(source_id=source.id)
    ModelSourceRevision.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(minutes=20))
    update_model_source(
        admin,
        org.uuid,
        source.id,
        expected_revision=1,
        configuration=configuration(),
        credential={"api_key": "synthetic-new"},
    )
    store.retire_owned_secret.side_effect = CloudSecretsError("bounded failure")
    with pytest.raises(ContractError, match="credential_cleanup_pending"):
        retire_unused_model_source_credentials(admin, org.uuid, source.id)
    old.refresh_from_db()
    assert old.state == "retired" and old.retired_at is None
    store.retire_owned_secret.side_effect = None
    assert retire_unused_model_source_credentials(admin, org.uuid, source.id) == 1
    store.retire_owned_secret.assert_called_with(source.id, old.credential_version)
    assert retire_unused_model_source_credentials(admin, org.uuid, source.id) == 0
    assert ModelSourceRevision.objects.get(source_id=source.id, revision=2).state == "ready"


@pytest.mark.parametrize("interruption", ["revision", "authorization"])
def test_credential_publication_failure_keeps_durable_retirement_reference(source_tenant, interruption):
    from engine.models import ModelSource, ModelSourceRevision
    from engine.services import create_model_source

    admin, _, org, store = source_tenant

    def interrupted_write(source_id, version, payload):
        if interruption == "revision":
            ModelSource.objects.filter(pk=source_id).update(revision=2)
        else:
            OrganizationMembership.objects.filter(user=admin, organization=org).delete()
        return "synthetic-owned-reference"

    store.create_owned_secret.side_effect = interrupted_write
    with pytest.raises((ContractError, OrganizationAuthorizationError)):
        create_model_source(admin, org.uuid, configuration(), credential={"api_key": "synthetic-secret"})
    revision = ModelSourceRevision.objects.get()
    assert revision.state == "failed"
    assert revision.credential_reference == "synthetic-owned-reference"


def test_source_observation_preserves_incumbent_usage_and_deadline():
    from datetime import timedelta
    from types import SimpleNamespace

    from django.utils import timezone

    from engine.services._model_source_observations import _source_observation
    from shared.model_access.reservation import ModelQuotaObservation
    from shared.model_access.sources import ModelSourceConfiguration

    now = timezone.now()
    catalog = SimpleNamespace(digest="sha256:" + "1" * 64)
    pool = SimpleNamespace(quota_pool_id="synthetic-quota", limit=100000)
    incumbent = ModelQuotaObservation(
        quota_pool_id=pool.quota_pool_id,
        catalog_digest=catalog.digest,
        source="application_cap",
        observed_at=now - timedelta(seconds=1),
        valid_until=now + timedelta(seconds=20),
        limit=80000,
        usage=70000,
        healthy_shard_ids=("legacy",),
    )
    observation = _source_observation(
        catalog, pool, [("selected", ModelSourceConfiguration.model_validate(configuration()))], incumbent, now
    )
    actual = ModelQuotaObservation.model_validate(observation)
    assert actual.usage == 70000 and actual.limit == 80000
    assert actual.valid_until == incumbent.valid_until
    assert set(actual.healthy_shard_ids) == {"selected", "legacy"}
    with pytest.raises(ContractError):
        _source_observation(
            catalog,
            pool,
            [("selected", ModelSourceConfiguration.model_validate(configuration()))],
            incumbent,
            incumbent.valid_until,
        )


def test_source_application_cap_bootstraps_matching_incumbent_pool_without_legacy_reading(source_tenant):
    """A first tenant source can safely cap the matching deployment pool."""
    from uuid import uuid4

    from cms.services import resolve_model_source_selection
    from engine.services import create_model_source
    from engine.services._model_source_observations import launch_model_observations
    from shared.model_access.reservation import ModelQuotaObservation
    from shared.model_access.sources import ModelSourceSelection

    admin, member, org, _ = source_tenant
    base = direct_source_catalog(uuid4())
    source = create_model_source(
        admin,
        org.uuid,
        configuration(
            name="Tenant Vertex source",
            provider="vertex-v1",
            authentication="workload-identity",
            model="publishers/anthropic/models/claude-sonnet",
            region="europe-west4",
            project="models-a",
            principal="model-invoke@models-a.iam.gserviceaccount.com",
            count_region="europe-west4",
            quota_identity="cloud-account-region",
            context_window_tokens=200_000,
            tokens_per_minute=750_000,
            allow_organization_members=True,
        ),
    )
    selection = ModelSourceSelection.model_validate(
        {
            "aliases": [
                {
                    "logical_alias": "coding-main",
                    "sources": [{"source_id": str(source.id), "revision": source.revision}],
                }
            ]
        }
    )
    compiled, _ = resolve_model_source_selection(member, org.uuid, selection, catalog=base)

    observations = tuple(ModelQuotaObservation.model_validate(value) for value in launch_model_observations(compiled))

    assert {item.quota_pool_id for item in observations} >= {"vertex-tokens-eu"}
    incumbent = next(item for item in observations if item.quota_pool_id == "vertex-tokens-eu")
    assert incumbent.source == "application_cap"
    assert incumbent.limit == 750_000
    assert any(shard.startswith(f"source-{source.id.hex}-v1-") for shard in incumbent.healthy_shard_ids)
