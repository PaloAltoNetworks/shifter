"""Only the authenticated broker may resolve a guest's pinned source credential."""

import json

import httpx
import pytest

from cms.services import resolve_model_source_selection
from engine.model_access_control.server import ControlApplication
from engine.models import ModelAllocationAuthority, SharingAuthorityFence
from engine.services import create_model_source
from shared.model_access import ContractError
from shared.model_access.sources import ModelSourceSelection

from .test_model_credentials import _PEER, enrolled_allocation, exchange, issue
from .test_model_sources import configuration, direct_source_catalog, source_tenant

__all__ = ["enrolled_allocation", "source_tenant"]
pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


@pytest.fixture
def source_control(source_tenant, enrolled_allocation):
    admin, _, org, store = source_tenant
    source = create_model_source(
        admin,
        org.uuid,
        configuration(region="provider-managed", allow_organization_members=True),
        credential={"api_key": "synthetic-secret"},
    )
    store.get_secret.return_value = json.dumps({"api_key": "synthetic-secret"})
    selection = ModelSourceSelection.model_validate(
        {"aliases": [{"logical_alias": "coding-main", "sources": [{"source_id": str(source.id), "revision": 1}]}]}
    )
    allocation = enrolled_allocation
    catalog, _ = resolve_model_source_selection(
        admin, org.uuid, selection, catalog=direct_source_catalog(allocation.deployment_id)
    )
    shard = next(item for item in catalog.shards if item.shard_id == catalog.aliases[0].eligible_shard_ids[0])
    allocation.alias_shards = {"coding-main": shard.shard_id}
    allocation.snapshot.update(
        catalog=catalog.model_dump(mode="json"), shards={"coding-main": shard.model_dump(mode="json")}
    )
    allocation.save(update_fields=["alias_shards", "snapshot"])
    fence = SharingAuthorityFence.objects.get(authority_reference=f"model-source:{source.id}")
    ModelAllocationAuthority.objects.create(allocation=allocation, fence=fence, revision=1)
    pair = exchange(issue(allocation))

    def verify(assertion, *, operation_id):
        if assertion != "broker" or operation_id is not None:
            raise ContractError("control.unauthorized")

    return ControlApplication(verify_identity=verify, ready=lambda: True), pair.access_token.get_secret_value(), store


async def test_source_projection_is_broker_only_and_bound_to_enrolled_alias(source_control):
    app, token, store = source_control
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://control.invalid") as client:
        body = {"token": token, "transport_peer": _PEER, "logical_alias": "coding-main"}
        denied = await client.post("/control/v1/source", json=body)
        assert denied.status_code == 401
        assert "synthetic-secret" not in denied.text
        assert store.get_secret.call_count == 0
        accepted = await client.post("/control/v1/source", json=body, headers={"authorization": "broker"})
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["target"]["provider"] == "anthropic-v1"
        assert json.loads(accepted.json()["credential"])["api_key"] == "synthetic-secret"
        foreign = await client.post(
            "/control/v1/source", json={**body, "logical_alias": "foreign"}, headers={"authorization": "broker"}
        )
        assert foreign.status_code != 200
        assert store.get_secret.call_count == 1
