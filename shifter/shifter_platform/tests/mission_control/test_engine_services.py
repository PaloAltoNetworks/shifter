"""Behavior tests for engine service functions (create_range / get_range_status).

Drives the real engine.services API against a real database: create_range
interprets a RequestSpec, persists Range/Subnet rows, allocates a subnet index,
and dispatches ECS provisioning (a no-op under the unconfigured test settings).
Assertions are on persisted state and return values, not on mocked ORM calls.
"""

import logging
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model

from engine import create_range, get_range_status
from engine.models import Range
from shared.schemas import InstanceSpec, RangeSpec, RequestSpec, SubnetSpec

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="engine-svc@example.com", email="engine-svc@example.com")


def _request_spec(user_id):
    return RequestSpec(
        request_id=uuid4(),
        user_id=user_id,
        items=[
            RangeSpec(
                user_id=user_id,
                scenario_id="test-scenario",
                subnets=[
                    SubnetSpec(
                        name="test_network",
                        uuid=str(uuid4()),
                        instances=[
                            InstanceSpec(name="attacker-kali", uuid=str(uuid4()), role="attacker", os_type="kali"),
                            InstanceSpec(name="victim-ubuntu", uuid=str(uuid4()), role="victim", os_type="ubuntu"),
                        ],
                        connected_to=[],
                    )
                ],
            )
        ],
    )


class TestGetRangeStatus:
    def test_returns_status_dict_for_existing_range(self, user):
        range_obj = Range.objects.create(user=user, status=Range.Status.PROVISIONING)
        result = get_range_status(range_obj.id)
        assert isinstance(result, dict)
        assert result["status"] == Range.Status.PROVISIONING
        assert set(result) >= {"status", "error_message", "instances", "created_at", "ready_at"}

    def test_reflects_each_status(self, user):
        for status in (Range.Status.READY, Range.Status.FAILED, Range.Status.DESTROYED):
            range_obj = Range.objects.create(user=user, status=status)
            assert get_range_status(range_obj.id)["status"] == status

    def test_returns_none_when_range_not_found(self):
        assert get_range_status(999999) is None

    def test_logs_warning_when_not_found(self, caplog):
        with caplog.at_level(logging.WARNING, logger="engine"):
            assert get_range_status(999999) is None
        assert "not found" in caplog.text.lower()

    def test_requires_range_id_argument(self):
        with pytest.raises(TypeError):
            get_range_status()


class TestCreateRange:
    def test_persists_range_and_subnet(self, user):
        spec = _request_spec(user.id)
        assert Range.objects.count() == 0

        result = create_range(spec)

        assert result == spec.request_id
        range_obj = Range.objects.get()
        assert range_obj.user_id == user.id
        # A subnet index was allocated.
        assert range_obj.subnet_index is not None
        assert range_obj.subnet_index >= Range.SUBNET_INDEX_MIN

    def test_returns_request_id(self, user):
        spec = _request_spec(user.id)
        assert create_range(spec) == spec.request_id

    def test_logs_range_creation(self, user, caplog):
        spec = _request_spec(user.id)
        with caplog.at_level(logging.INFO, logger="engine"):
            create_range(spec)
        assert "create_range" in caplog.text

    def test_allocates_distinct_indices_for_concurrent_ranges(self, user, db, django_user_model):
        other = django_user_model.objects.create_user(username="engine-svc2@example.com", email="e2@example.com")
        create_range(_request_spec(user.id))
        create_range(_request_spec(other.id))
        indices = sorted(Range.objects.values_list("subnet_index", flat=True))
        assert len(indices) == 2
        assert indices[0] != indices[1]

    def test_propagates_subnet_exhaustion(self, user, monkeypatch):
        monkeypatch.setattr(Range, "SUBNET_INDEX_MAX", 1)
        create_range(_request_spec(user.id))  # consumes index 1
        with pytest.raises(ValueError, match="No subnet indices available"):
            create_range(_request_spec(user.id))

    def test_raises_on_none_request(self):
        with pytest.raises(TypeError):
            create_range(None)

    def test_raises_on_non_requestspec(self):
        with pytest.raises(TypeError, match="must be RequestSpec"):
            create_range("not a RequestSpec")

    def test_raises_on_dict_instead_of_requestspec(self):
        with pytest.raises(TypeError, match="must be RequestSpec"):
            create_range({"user_id": 1, "scenario_id": "test"})
