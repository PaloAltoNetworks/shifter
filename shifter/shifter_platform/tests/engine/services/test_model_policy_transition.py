"""Live source edits change model policy without inventing a range generation."""

import pytest

from tests.engine.services.test_model_credentials import enrolled_allocation

__all__ = ["enrolled_allocation"]
from shared.model_access import ContractError

pytestmark = pytest.mark.django_db(transaction=True)


def test_policy_transition_revokes_old_grant_and_compares_revision(django_user_model):
    from engine.models import Range
    from engine.services import begin_range_model_policy_change
    from tests.engine.services.test_model_allocation import allocate, allocation_inputs

    inputs = allocation_inputs(django_user_model)
    old = allocate(inputs)
    range_obj = Range.objects.get(uuid=old.range_id)
    range_obj.status = Range.Status.READY
    range_obj.save(update_fields=["status"])
    before = old.snapshot
    revision = begin_range_model_policy_change(
        request_id=old.request_id, expected_revision=0, actor_id=range_obj.user_id
    )
    old.refresh_from_db()
    range_obj.refresh_from_db()
    assert revision == 1
    assert old.grant.state == "revoked"
    assert old.snapshot == before
    assert range_obj.provisioner_operation_id == old.operation_id
    with pytest.raises(ContractError, match=r"source\.revision_conflict"):
        begin_range_model_policy_change(request_id=old.request_id, expected_revision=0, actor_id=range_obj.user_id)


def test_guest_refresh_moves_to_explicit_successor_once_without_extending_deadline(enrolled_allocation):
    from engine.models import ModelAccessCredential, ModelAllocation, ModelPendingGrant, Range
    from engine.services import authenticate_model_access, begin_range_model_policy_change, refresh_model_access
    from tests.engine.services.test_model_credentials import _PEER, exchange, issue

    old = enrolled_allocation
    row = Range.objects.get(uuid=old.range_id)
    old.snapshot["request"] = {"owner_ref": {"owner": "management", "reference": f"user:{row.user_id}"}}
    old.save(update_fields=["snapshot"])
    pair = exchange(issue(old))
    row.status = Range.Status.READY
    row.save(update_fields=["status"])
    begin_range_model_policy_change(request_id=old.request_id, expected_revision=0, actor_id=row.user_id)
    fields = {
        field.name: getattr(old, field.name)
        for field in ModelAllocation._meta.fields
        if field.name not in {"id", "created_at"}
    }
    successor = ModelAllocation.objects.create(**{**fields, "source_policy_revision": 1})
    grant = ModelPendingGrant.objects.create(allocation=successor, grant_epoch=3)
    ModelAccessCredential.objects.filter(grant=old.grant).update(replacement_grant=grant)
    with pytest.raises(ContractError):
        refresh_model_access(token=pair.refresh_token.get_secret_value(), transport_peer="10.99.0.1")
    replaced = refresh_model_access(token=pair.refresh_token.get_secret_value(), transport_peer=_PEER)
    assert replaced.hard_expires_at == pair.hard_expires_at
    authorized = authenticate_model_access(token=replaced.access_token.get_secret_value(), transport_peer=_PEER)
    assert authorized.allocation_id == successor.pk
    assert authorized.operation_id == old.operation_id
    with pytest.raises(ContractError):
        refresh_model_access(token=pair.refresh_token.get_secret_value(), transport_peer=_PEER)
    with pytest.raises(ContractError):
        authenticate_model_access(token=pair.access_token.get_secret_value(), transport_peer=_PEER)
