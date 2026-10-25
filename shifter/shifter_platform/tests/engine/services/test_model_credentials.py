"""Real persistence tests for one-use, generation-bound guest credentials."""

from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone

from engine.models import ModelAccessCredential, ModelPendingGrant, Range, Request, SubnetAllocation
from engine.services import (
    authenticate_model_access,
    exchange_model_enrollment,
    issue_model_enrollment,
    refresh_model_access,
)
from shared.model_access import ContractError

from .test_model_request_accounting import make_reservable_allocation

pytestmark = pytest.mark.django_db
_PEER = "10.80.2.17"


@pytest.fixture
def enrolled_allocation(django_user_model):
    allocation = make_reservable_allocation()
    user = django_user_model.objects.create_user(username=f"guest-{uuid4()}")
    request = Request.objects.create(request_id=allocation.request_id, request_type="range", user=user)
    range_obj = Range.objects.create(
        uuid=allocation.range_id,
        user=user,
        request=request,
        workspace_id=1,
        provisioner_operation_id=allocation.operation_id,
        status=Range.Status.PROVISIONING,
    )
    SubnetAllocation.objects.create(
        vpc_id="synthetic-network",
        range_id=range_obj.pk,
        request_id=str(allocation.request_id),
        cidr="10.80.2.0/24",
        subnet_size=24,
    )
    return allocation


def issue(allocation):
    return issue_model_enrollment(allocation_id=allocation.pk, operation_id=allocation.operation_id)


def exchange(enrollment):
    return exchange_model_enrollment(token=enrollment.enrollment_token.get_secret_value(), transport_peer=_PEER)


def test_exchange_is_one_use_and_database_has_no_plaintext(enrolled_allocation):
    enrollment = issue(enrolled_allocation)
    pair = exchange(enrollment)
    stored = str(ModelAccessCredential.objects.values().get())
    assert enrollment.enrollment_token.get_secret_value() not in stored
    assert pair.access_token.get_secret_value() not in stored
    assert pair.refresh_token.get_secret_value() not in stored
    assert pair.access_token.get_secret_value() not in repr(pair)
    with pytest.raises(ContractError):
        exchange(enrollment)
    auth = authenticate_model_access(token=pair.access_token.get_secret_value(), transport_peer=_PEER)
    assert auth.allocation_id == enrolled_allocation.pk
    assert set(auth.aliases) == {"coding-main"}


def test_refresh_rotates_both_tokens_and_preserves_hard_deadline(enrolled_allocation):
    first = exchange(issue(enrolled_allocation))
    second = refresh_model_access(token=first.refresh_token.get_secret_value(), transport_peer=_PEER)
    assert second.hard_expires_at == first.hard_expires_at
    with pytest.raises(ContractError):
        refresh_model_access(token=first.refresh_token.get_secret_value(), transport_peer=_PEER)
    with pytest.raises(ContractError):
        authenticate_model_access(token=first.access_token.get_secret_value(), transport_peer=_PEER)
    authenticate_model_access(token=second.access_token.get_secret_value(), transport_peer=_PEER)


def test_authenticated_refresh_budget_preserves_current_pair_when_exhausted(enrolled_allocation):
    moment = timezone.now()
    pair = exchange(issue(enrolled_allocation))
    for _ in range(59):
        pair = refresh_model_access(token=pair.refresh_token.get_secret_value(), transport_peer=_PEER, now=moment)
    with pytest.raises(ContractError, match=r"credential\.rate_limited"):
        refresh_model_access(token=pair.refresh_token.get_secret_value(), transport_peer=_PEER, now=moment)
    authenticate_model_access(token=pair.access_token.get_secret_value(), transport_peer=_PEER)
    renewed = refresh_model_access(
        token=pair.refresh_token.get_secret_value(), transport_peer=_PEER, now=moment + timedelta(seconds=61)
    )
    assert renewed.hard_expires_at == pair.hard_expires_at


@pytest.mark.parametrize("peer", ["10.80.3.17", "127.0.0.1", "::ffff:10.80.2.17", "10.80.2.17, 10.80.3.17"])
def test_foreign_peer_cannot_consume_enrollment(enrolled_allocation, peer):
    enrollment = issue(enrolled_allocation)
    with pytest.raises(ContractError):
        exchange_model_enrollment(token=enrollment.enrollment_token.get_secret_value(), transport_peer=peer)
    exchange(enrollment)


def test_reenrollment_invalidates_existing_tokens(enrolled_allocation):
    first = exchange(issue(enrolled_allocation))
    enrollment = issue(enrolled_allocation)
    with pytest.raises(ContractError):
        authenticate_model_access(token=first.access_token.get_secret_value(), transport_peer=_PEER)
    with pytest.raises(ContractError):
        refresh_model_access(token=first.refresh_token.get_secret_value(), transport_peer=_PEER)
    exchange(enrollment)


@pytest.mark.parametrize("mutation", ["generation", "pause", "revoke", "subnet", "expiry"])
def test_current_authority_is_checked_on_every_request(enrolled_allocation, mutation):
    pair = exchange(issue(enrolled_allocation))
    if mutation == "generation":
        Range.objects.filter(uuid=enrolled_allocation.range_id).update(provisioner_operation_id=uuid4())
    elif mutation == "pause":
        Range.objects.filter(uuid=enrolled_allocation.range_id).update(status=Range.Status.PAUSING)
    elif mutation == "revoke":
        ModelPendingGrant.objects.filter(allocation=enrolled_allocation).update(state="revoked")
    elif mutation == "subnet":
        SubnetAllocation.objects.all().delete()
    else:
        enrolled_allocation.deadline = timezone.now() - timedelta(seconds=1)
        enrolled_allocation.save(update_fields=["deadline"])
    with pytest.raises(ContractError):
        authenticate_model_access(token=pair.access_token.get_secret_value(), transport_peer=_PEER)
    with pytest.raises(ContractError):
        refresh_model_access(token=pair.refresh_token.get_secret_value(), transport_peer=_PEER)


def test_expired_enrollment_and_access_are_denied(enrolled_allocation):
    enrollment = issue(enrolled_allocation)
    with pytest.raises(ContractError):
        exchange_model_enrollment(
            token=enrollment.enrollment_token.get_secret_value(),
            transport_peer=_PEER,
            now=timezone.now() + timedelta(seconds=121),
        )
    pair = exchange(enrollment)
    with pytest.raises(ContractError):
        authenticate_model_access(
            token=pair.access_token.get_secret_value(),
            transport_peer=_PEER,
            now=timezone.now() + timedelta(seconds=301),
        )


def test_wrong_operation_cannot_issue_credentials(enrolled_allocation):
    with pytest.raises(ContractError):
        issue_model_enrollment(allocation_id=enrolled_allocation.pk, operation_id=uuid4())
    assert not ModelAccessCredential.objects.exists()


def test_audit_failure_rolls_back_token_consumption(enrolled_allocation, monkeypatch):
    enrollment = issue(enrolled_allocation)
    import shared.audit

    original = shared.audit.audit_log

    def fail(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(shared.audit, "audit_log", fail)
    with pytest.raises(RuntimeError):
        exchange(enrollment)
    assert ModelPendingGrant.objects.get(allocation=enrolled_allocation).state == "pending"
    monkeypatch.setattr(shared.audit, "audit_log", original)
    exchange(enrollment)


def test_enrollment_activates_request_authority_only_after_token_exchange(enrolled_allocation):
    from engine.services import reserve_request
    from engine.services._model_broker_control import reserve_model_call

    from .test_model_request_accounting import _bound

    enrollment = issue(enrolled_allocation)
    grant = ModelPendingGrant.objects.get(allocation=enrolled_allocation)
    assert grant.state == "pending"
    with pytest.raises(ContractError, match=r"request\.grant_inactive"):
        reserve_request(
            allocation_id=enrolled_allocation.pk,
            request_uuid=uuid4(),
            logical_alias="coding-main",
            billing_bound=_bound(),
        )
    pair = exchange(enrollment)
    grant.refresh_from_db()
    assert grant.state == "active"
    request_id = uuid4()
    result = reserve_model_call(
        token=pair.access_token.get_secret_value(),
        transport_peer=_PEER,
        request_uuid=request_id,
        logical_alias="coding-main",
        billing_bound=_bound(),
    )
    assert result.request_uuid == request_id
    issue(enrolled_allocation)
    grant.refresh_from_db()
    assert grant.state == "pending"
    with pytest.raises(ContractError):
        reserve_model_call(
            token=pair.access_token.get_secret_value(),
            transport_peer=_PEER,
            request_uuid=uuid4(),
            logical_alias="coding-main",
            billing_bound=_bound(),
        )
