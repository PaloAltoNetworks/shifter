"""Behavior tests for ``cms.services.reassign_range_owner`` (issue #1018).

DB-backed per ADR-019's boundary-mock policy: no patching of first-party
``cms.*`` / ``engine.*`` service seams. The engine-side reassignment is driven
for real (``engine.services.reassign_range_owner_by_request``), including the
"no engine range for this request" branch, which is triggered by simply not
creating an ``engine.Range`` row rather than mocking the facade to return
``False``.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model

from cms import services
from cms.exceptions import CMSError
from cms.models import RangeInstance
from cms.models import Request as CmsRequest
from engine.models import Range as EngineRange
from engine.models import Request as EngineRequest
from shared.enums import RangeSource, RequestType, ResourceStatus
from tests.conftest import INVALID_USERS

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def user_a(db):
    return User.objects.create_user(username="reassign-a@example.com", email="reassign-a@example.com")


@pytest.fixture
def user_b(db):
    return User.objects.create_user(username="reassign-b@example.com", email="reassign-b@example.com")


def _make_owned_range(*, owner, scenario_id: str = "basic") -> RangeInstance:
    """A real cms ``RangeInstance`` + cms ``Request`` + engine ``Range``/``Request``, all owned by ``owner``.

    Mirrors ``tests.ctf.test_services.test_range_recovery._make_spare_range``
    so both cms/request/engine sides genuinely exist and can be checked after
    reassignment, instead of mocking the engine facade.
    """
    request_id = uuid4()
    cms_request = CmsRequest.objects.create(request_id=request_id, request_type=RequestType.RANGE.value, user=owner)
    engine_request = EngineRequest.objects.create(
        request_id=request_id, request_type=RequestType.RANGE.value, user=owner
    )
    engine_range = EngineRange.objects.create(
        uuid=uuid4(),
        user=owner,
        request=engine_request,
        cms_user_id=owner.id,
        status=EngineRange.Status.READY,
        subnet_index=EngineRange.allocate_subnet_index(),
    )
    range_instance = RangeInstance.objects.create(
        request=cms_request,
        scenario_id=scenario_id,
        user_id=owner.id,
        range_source=RangeSource.CTF.value,
        status=ResourceStatus.READY.value,
    )
    range_instance.engine_range = engine_range
    return range_instance


def _make_range_without_engine_range(*, owner, scenario_id: str = "basic") -> RangeInstance:
    """A cms ``RangeInstance`` + cms ``Request`` owned by ``owner`` with no matching engine ``Range``.

    Drives the real "engine has no range for this request" branch of
    ``engine.services.reassign_range_owner_by_request`` (it filters
    ``engine.Range`` by ``request__request_id`` and finds nothing), instead of
    mocking the facade to return ``False``.
    """
    cms_request = CmsRequest.objects.create(request_id=uuid4(), request_type=RequestType.RANGE.value, user=owner)
    return RangeInstance.objects.create(
        request=cms_request,
        scenario_id=scenario_id,
        user_id=owner.id,
        range_source=RangeSource.CTF.value,
        status=ResourceStatus.READY.value,
    )


def _make_range_no_request(*, owner, scenario_id: str = "basic") -> RangeInstance:
    """A real ``RangeInstance`` with no associated ``Request``."""
    return RangeInstance.objects.create(
        request=None,
        scenario_id=scenario_id,
        user_id=owner.id,
        range_source=RangeSource.CTF.value,
        status=ResourceStatus.READY.value,
    )


class TestReassignRangeOwnerValidation:
    def test_requires_range_instance_pk_argument(self, user_b):
        with pytest.raises(TypeError):
            services.reassign_range_owner(new_user=user_b)

    def test_requires_new_user_argument(self):
        with pytest.raises(TypeError):
            services.reassign_range_owner(42)

    @pytest.mark.parametrize("invalid_user", INVALID_USERS)
    def test_raises_on_invalid_new_user(self, invalid_user):
        with pytest.raises((TypeError, ValueError, AttributeError)):
            services.reassign_range_owner(42, invalid_user)

    def test_raises_typeerror_for_none_range_instance_pk(self, user_b):
        with pytest.raises(TypeError, match="range_instance_pk cannot be None"):
            services.reassign_range_owner(None, user_b)

    def test_raises_typeerror_for_non_int_range_instance_pk(self, user_b):
        with pytest.raises(TypeError, match="range_instance_pk must be an int"):
            services.reassign_range_owner("5", user_b)

    def test_raises_valueerror_for_negative_range_instance_pk(self, user_b):
        with pytest.raises(ValueError, match="non-negative"):
            services.reassign_range_owner(-1, user_b)


class TestReassignRangeOwnerHappyPath:
    def test_reassigns_ownership_across_cms_and_engine(self, user_a, user_b):
        ri = _make_owned_range(owner=user_a)
        request_id = ri.request.request_id

        result = services.reassign_range_owner(ri.pk, user_b)

        assert result is None
        assert RangeInstance.objects.get(pk=ri.pk).user_id == user_b.id
        assert CmsRequest.objects.get(request_id=request_id).user_id == user_b.id
        engine_range = EngineRange.objects.get(request__request_id=request_id)
        assert engine_range.user_id == user_b.id
        assert engine_range.cms_user_id == user_b.id
        assert EngineRequest.objects.get(request_id=request_id).user_id == user_b.id


class TestReassignRangeOwnerNoOp:
    def test_noop_when_already_owned_by_new_user(self, user_b):
        # Deliberately no engine Range for this request: if the no-op branch
        # did not short-circuit before dispatching to the engine facade, this
        # would raise CMSError instead of returning cleanly.
        ri = _make_range_without_engine_range(owner=user_b)
        request_id = ri.request.request_id

        result = services.reassign_range_owner(ri.pk, user_b)

        assert result is None
        assert RangeInstance.objects.get(pk=ri.pk).user_id == user_b.id
        assert CmsRequest.objects.get(request_id=request_id).user_id == user_b.id


class TestReassignRangeOwnerErrors:
    def test_raises_cms_error_when_range_not_found(self, user_b):
        with pytest.raises(CMSError, match="not found"):
            services.reassign_range_owner(999999, user_b)

    def test_raises_cms_error_when_no_associated_request(self, user_a, user_b):
        ri = _make_range_no_request(owner=user_a)
        with pytest.raises(CMSError, match="no associated request"):
            services.reassign_range_owner(ri.pk, user_b)

    def test_raises_cms_error_and_rolls_back_when_no_engine_range(self, user_a, user_b):
        ri = _make_range_without_engine_range(owner=user_a)
        request_id = ri.request.request_id

        with pytest.raises(CMSError, match="no engine range for request"):
            services.reassign_range_owner(ri.pk, user_b)

        # Transactional: the CMS-side field updates made before the engine
        # dispatch failed must have rolled back.
        assert RangeInstance.objects.get(pk=ri.pk).user_id == user_a.id
        assert CmsRequest.objects.get(request_id=request_id).user_id == user_a.id
