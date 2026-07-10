"""Behavior tests for cms.services.get_active_range / get_range_by_request_id.

Drives the range-projection services against real ``RangeInstance`` / ``Request``
rows and the real runtime-IP overlay, which reads a real engine ``Range``'s
``provisioned_instances`` through ``engine.services.get_instance_ips_by_uuid``,
instead of patching ``RangeInstance.objects`` / ``engine_get_instance_ips_by_uuid``.
"""

from datetime import timedelta
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from cms.models import RangeInstance, Request
from cms.services import get_active_range, get_range_by_request_id
from shared.constants import USER_CANNOT_BE_NONE
from shared.enums import RequestType, ResourceStatus
from shared.schemas import RangeContext

pytestmark = pytest.mark.django_db

User = get_user_model()

_NESTED_SPEC = {
    "subnets": [
        {
            "name": "core",
            "instances": [
                {"uuid": "att-uuid", "role": "attacker", "os_type": "kali", "join_domain": False},
                {"uuid": "vic-uuid", "role": "victim", "os_type": "windows", "join_domain": False},
            ],
        }
    ]
}
_FLAT_SPEC = {"instances": [{"uuid": "leg-att", "role": "attacker", "os_type": "kali", "join_domain": False}]}


@pytest.fixture
def user(db):
    return User.objects.create_user(username="svc@example.com", email="svc@example.com")


def _request(user) -> Request:
    return Request.objects.create(request_id=uuid4(), request_type=RequestType.RANGE.value, user=user)


def _range_instance(
    user, *, range_id, status=ResourceStatus.READY.value, scenario_id="basic", range_spec=None, request=None
):
    return RangeInstance.objects.create(
        user_id=user.id,
        range_id=range_id,
        status=status,
        scenario_id=scenario_id,
        range_spec=range_spec,
        request=request,
    )


def _engine_range(user, *, provisioned_instances):
    """Create a real engine Range whose provisioned_instances feed the IP overlay."""
    from engine.models import Range as EngineRange

    return EngineRange.objects.create(
        user=user, status=EngineRange.Status.READY, provisioned_instances=provisioned_instances
    )


class TestGetActiveRange:
    def test_returns_active_range(self, user):
        _range_instance(user, range_id=1, request=_request(user))
        result = get_active_range(user)
        assert isinstance(result, RangeContext)
        assert result.range_id == 1
        assert result.user_id == user.id
        assert result.status == ResourceStatus.READY

    def test_returns_provisioning_range(self, user):
        _range_instance(user, range_id=2, status=ResourceStatus.PROVISIONING.value, request=_request(user))
        result = get_active_range(user)
        assert result.range_id == 2
        assert result.status == ResourceStatus.PROVISIONING

    def test_returns_none_when_no_ranges(self, user):
        assert get_active_range(user) is None

    def test_excludes_destroying_ranges(self, user):
        _range_instance(user, range_id=3, status=ResourceStatus.DESTROYING.value, request=_request(user))
        assert get_active_range(user) is None

    def test_returns_most_recent_active_range(self, user):
        old = _range_instance(user, range_id=10, request=_request(user))
        RangeInstance.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(hours=1))
        _range_instance(user, range_id=11, scenario_id="new", request=_request(user))

        result = get_active_range(user)
        assert result.range_id == 11

    def test_raises_typeerror_for_none_user(self):
        with pytest.raises(TypeError, match=USER_CANNOT_BE_NONE):
            get_active_range(None)

    def test_raises_typeerror_for_invalid_user(self):
        with pytest.raises(TypeError, match="user must be a User instance"):
            get_active_range("not a user")

    def test_validates_range_context_on_creation(self, user):
        from pydantic import ValidationError

        _range_instance(user, range_id=0, request=_request(user))  # 0 is invalid for RangeContext
        with pytest.raises(ValidationError, match="range_id"):
            get_active_range(user)

    def test_extracts_instances_from_nested_subnets_format(self, user):
        _range_instance(user, range_id=100, range_spec=_NESTED_SPEC, request=_request(user))
        result = get_active_range(user)
        assert [i.uuid for i in result.instances] == ["att-uuid", "vic-uuid"]
        assert [i.role for i in result.instances] == ["attacker", "victim"]

    def test_extracts_instances_from_legacy_flat_format(self, user):
        _range_instance(user, range_id=101, range_spec=_FLAT_SPEC, request=_request(user))
        result = get_active_range(user)
        assert [i.uuid for i in result.instances] == ["leg-att"]


class TestActiveRangePrivateIpOverlay:
    def test_populates_private_ip_from_engine_range(self, user):
        rng = _engine_range(
            user,
            provisioned_instances=[
                {"uuid": "att-uuid", "private_ip": "10.0.1.5"},
                {"uuid": "vic-uuid", "private_ip": "10.0.1.6"},
            ],
        )
        _range_instance(user, range_id=rng.id, range_spec=_NESTED_SPEC, request=_request(user))

        result = get_active_range(user)
        assert {i.uuid: i.private_ip for i in result.instances} == {"att-uuid": "10.0.1.5", "vic-uuid": "10.0.1.6"}

    def test_leaves_private_ip_none_when_not_in_map(self, user):
        rng = _engine_range(user, provisioned_instances=[{"uuid": "att-uuid", "private_ip": "10.0.1.5"}])
        _range_instance(user, range_id=rng.id, range_spec=_NESTED_SPEC, request=_request(user))

        result = get_active_range(user)
        assert {i.uuid: i.private_ip for i in result.instances} == {"att-uuid": "10.0.1.5", "vic-uuid": None}

    def test_skips_overlay_when_range_id_is_none(self, user):
        _range_instance(user, range_id=None, range_spec=_NESTED_SPEC, request=_request(user))
        result = get_active_range(user)
        assert all(i.private_ip is None for i in result.instances)

    def test_no_engine_range_degrades_to_no_ip(self, user):
        # range_id set but no matching engine Range -> overlay is empty, projection still renders.
        _range_instance(user, range_id=88888, range_spec=_NESTED_SPEC, request=_request(user))
        result = get_active_range(user)
        assert len(result.instances) == 2
        assert all(i.private_ip is None for i in result.instances)


class TestGetRangeByRequestId:
    def test_populates_private_ip(self, user):
        req = _request(user)
        rng = _engine_range(user, provisioned_instances=[{"uuid": "leg-att", "private_ip": "10.9.9.9"}])
        _range_instance(user, range_id=rng.id, range_spec=_FLAT_SPEC, request=req)

        result = get_range_by_request_id(user, str(req.request_id))
        assert result.instances[0].private_ip == "10.9.9.9"

    def test_skips_overlay_when_range_id_is_none(self, user):
        req = _request(user)
        _range_instance(user, range_id=None, range_spec=_FLAT_SPEC, request=req)
        result = get_range_by_request_id(user, str(req.request_id))
        assert result.instances[0].private_ip is None

    def test_raises_when_not_found(self, user):
        from cms.exceptions import CMSError

        with pytest.raises(CMSError, match="not found"):
            get_range_by_request_id(user, str(uuid4()))
