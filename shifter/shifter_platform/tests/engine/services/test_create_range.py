"""Behavior tests for create_range() in engine/services.

Drives the real service against a real database: a RequestSpec is interpreted
into Request/Instance rows, a Range row is persisted with an allocated subnet
index, and ECS provisioning is dispatched. ECS is unconfigured under the test
settings, so provisioning is a no-op and needs no boundary mock. Assertions are
on persisted state and return values, not on mocked ORM/interpreter/ECS calls.
"""

import logging
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from engine import create_range
from engine.models import Range
from shared.cloud.exceptions import CloudTaskError
from shared.schemas import InstanceSpec, RangeRef, RangeSpec, RequestSpec, SubnetSpec

from .conftest import ECS_TASK_ARN

pytestmark = pytest.mark.django_db

User = get_user_model()


def make_request_spec(*, user_id: int, scenario_id: str = "basic-attack") -> RequestSpec:
    range_spec = RangeSpec(
        uuid=str(uuid4()),
        scenario_id=scenario_id,
        user_id=user_id,
        subnets=[
            SubnetSpec(
                name="default",
                uuid=str(uuid4()),
                instances=[InstanceSpec(role="attacker", os_type="kali", uuid=str(uuid4()))],
                connected_to=[],
            )
        ],
    )
    return RequestSpec(request_id=uuid4(), user_id=user_id, items=[range_spec])


@pytest.fixture
def user(db):
    return User.objects.create_user(username="engine-create@example.com", email="engine-create@example.com")


class TestCreateRangePersistence:
    def test_returns_range_ref(self, user):
        spec = make_request_spec(user_id=user.id)
        result = create_range(spec)
        assert isinstance(result, RangeRef)
        assert result.request_id == spec.request_id
        assert result.user_id == user.id
        assert result.range_id is not None
        assert result.range_id > 0

    def test_persists_range_for_the_looked_up_user(self, user):
        create_range(make_request_spec(user_id=user.id))
        range_obj = Range.objects.get()
        assert range_obj.user == user
        assert range_obj.cms_user_id == user.id

    def test_persists_range_config_with_schema_discriminator(self, user):
        create_range(make_request_spec(user_id=user.id))
        range_obj = Range.objects.get()
        assert range_obj.range_config["spec_schema"] == "range_spec"
        assert range_obj.range_config["spec_version"] == "1"
        assert range_obj.range_config["payload"]["scenario_id"] == "basic-attack"

    def test_allocates_a_subnet_index(self, user):
        create_range(make_request_spec(user_id=user.id))
        assert Range.objects.get().subnet_index is not None

    def test_creates_range_with_provisioning_status_and_request(self, user):
        spec = make_request_spec(user_id=user.id)
        create_range(spec)
        range_obj = Range.objects.get()
        assert range_obj.status == Range.Status.PROVISIONING
        assert range_obj.subnet_index >= Range.SUBNET_INDEX_MIN
        # The interpreted Request was linked to the Range.
        assert range_obj.request is not None
        assert str(range_obj.request.request_id) == str(spec.request_id)

    @override_settings(LOCAL_PROVISIONER=None, ENGINE_TASK_CLUSTER="", ENGINE_ECS_CLUSTER_ARN="")
    def test_no_task_arn_stored_when_ecs_unconfigured(self, user):
        # With no local provisioner and no ECS cluster configured,
        # start_range_provisioning returns None, so no task ARN is recorded.
        # Pinned via override_settings so the precondition holds regardless of
        # settings leaked by other tests under xdist.
        create_range(make_request_spec(user_id=user.id))
        range_obj = Range.objects.get()
        assert range_obj.provisioning_task_arn == ""
        assert range_obj.teardown_task_arn == ""

    def test_stores_provisioning_task_arn_when_ecs_configured(self, user, ecs_dispatch):
        create_range(make_request_spec(user_id=user.id))
        range_obj = Range.objects.get()
        assert range_obj.provisioning_task_arn == ECS_TASK_ARN
        assert range_obj.teardown_task_arn == ""

    def test_reuses_existing_range_for_same_request_id(self, user):
        spec = make_request_spec(user_id=user.id)
        first = create_range(spec)
        second = create_range(spec)

        assert second.range_id == first.range_id
        assert Range.objects.count() == 1

    def test_marks_range_failed_when_provisioning_dispatch_fails(self, user, settings):
        settings.CLOUD_PROVIDER = "aws"
        settings.LOCAL_PROVISIONER = None
        settings.ENGINE_TASK_CLUSTER = "test-cluster"
        settings.ENGINE_TASK_DEFINITION = "test-taskdef"
        settings.ENGINE_TASK_NETWORK_SECURITY_GROUP_ID = "sg-test"
        settings.ENGINE_TASK_NETWORK_SUBNET_IDS = "subnet-aaa,subnet-bbb"
        ecs_client = MagicMock()
        ecs_client.run_task.return_value = {"tasks": [], "failures": [{"reason": "RESOURCE:CPU"}]}

        spec = make_request_spec(user_id=user.id)
        with patch("boto3.client", return_value=ecs_client), pytest.raises(CloudTaskError):
            create_range(spec)

        range_obj = Range.objects.get(request__request_id=spec.request_id)
        assert range_obj.status == Range.Status.FAILED
        assert range_obj.error_message == "Provisioning dispatch failed"


class TestCreateRangeErrorValidation:
    def test_validates_request_spec_type(self):
        for invalid in (None, {"scenario_id": "test", "user_id": 1}, "not-a-request"):
            with pytest.raises(TypeError, match="request_spec must be RequestSpec"):
                create_range(invalid)

    def test_rejects_rangespec_passed_directly(self):
        range_spec = RangeSpec(
            scenario_id="basic-attack",
            user_id=1,
            subnets=[
                SubnetSpec(
                    name="default",
                    uuid=str(uuid4()),
                    instances=[InstanceSpec(role="attacker", os_type="kali", uuid=str(uuid4()))],
                )
            ],
        )
        with pytest.raises(TypeError, match="request_spec must be RequestSpec"):
            create_range(range_spec)

    def test_raises_when_no_range_spec_item(self):
        spec = RequestSpec(request_id=uuid4(), user_id=1, items=[])
        with pytest.raises(ValueError, match="must contain a RangeSpec"):
            create_range(spec)

    def test_propagates_user_does_not_exist(self, db):
        spec = make_request_spec(user_id=9_999_999)  # no such user
        with pytest.raises(User.DoesNotExist):
            create_range(spec)

    def test_propagates_and_rolls_back_on_subnet_exhaustion(self, user, monkeypatch):
        monkeypatch.setattr(Range, "SUBNET_INDEX_MAX", 1)
        Range.objects.create(user=user, subnet_index=1, status=Range.Status.READY)  # consume the only index

        with pytest.raises(ValueError, match="No subnet indices available"):
            create_range(make_request_spec(user_id=user.id))

        # No new Range row was created (allocation fails before persistence).
        assert Range.objects.count() == 1


class TestCreateRangeLogging:
    def test_logs_scenario_and_user_on_entry(self, user, caplog):
        with caplog.at_level(logging.DEBUG, logger="engine"):
            ref = create_range(make_request_spec(user_id=user.id, scenario_id="advanced-persistent-threat"))
        assert isinstance(ref, RangeRef)
        assert "advanced-persistent-threat" in caplog.text
        assert str(user.id) in caplog.text

    def test_logs_range_creation(self, user, caplog):
        with caplog.at_level(logging.INFO, logger="engine"):
            ref = create_range(make_request_spec(user_id=user.id))
        range_obj = Range.objects.get()
        assert isinstance(ref, RangeRef)
        assert str(range_obj.id) in caplog.text
