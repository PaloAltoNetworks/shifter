"""Behavior tests for get_range_status() in engine/services.

Reads real ``Range`` rows and returns a status dict (status, error_message,
instances from ``provisioned_instances``, created_at, ready_at) or None when the
range is missing. No ORM mocking.
"""

import logging

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from engine import get_range_status
from engine.models import Range

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="engine-status@example.com", email="engine-status@example.com")


class TestGetRangeStatus:
    def test_returns_complete_status_dict(self, user):
        instances = [{"uuid": "i-1", "role": "attacker", "private_ip": "10.1.1.10"}]
        range_obj = Range.objects.create(
            user=user, status=Range.Status.READY, error_message="", provisioned_instances=instances
        )
        Range.objects.filter(pk=range_obj.pk).update(ready_at=timezone.now())

        result = get_range_status(range_obj.id)
        assert result["status"] == Range.Status.READY
        assert result["error_message"] == ""
        assert result["instances"] == instances
        assert result["created_at"] is not None
        assert result["ready_at"] is not None

    def test_handles_null_fields(self, user):
        range_obj = Range.objects.create(user=user, status=Range.Status.PENDING, provisioned_instances=None)
        result = get_range_status(range_obj.id)
        assert result["instances"] == []
        assert result["ready_at"] is None

    def test_preserves_provider_metadata_in_instances(self, user):
        instances = [{"uuid": "i-1", "provider_metadata": {"private_ip": "10.9.9.9", "zone": "us-east-2a"}}]
        range_obj = Range.objects.create(user=user, status=Range.Status.READY, provisioned_instances=instances)
        assert get_range_status(range_obj.id)["instances"] == instances

    def test_returns_none_when_not_found(self):
        assert get_range_status(999999) is None

    def test_does_not_modify_range(self, user):
        range_obj = Range.objects.create(user=user, status=Range.Status.READY, error_message="orig")
        get_range_status(range_obj.id)
        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.READY
        assert range_obj.error_message == "orig"

    def test_logs_debug_on_entry(self, user, caplog):
        range_obj = Range.objects.create(user=user, status=Range.Status.READY)
        with caplog.at_level(logging.DEBUG, logger="engine"):
            get_range_status(range_obj.id)
        assert str(range_obj.id) in caplog.text

    def test_logs_warning_when_not_found(self, caplog):
        with caplog.at_level(logging.WARNING, logger="engine"):
            get_range_status(999999)
        assert "not found" in caplog.text.lower()

    def test_created_at_is_iso_string(self, user):
        from datetime import datetime

        range_obj = Range.objects.create(user=user, status=Range.Status.READY)
        # created_at is auto-set and serialised to an ISO-8601 string that
        # round-trips through fromisoformat.
        created = get_range_status(range_obj.id)["created_at"]
        assert isinstance(created, str)
        assert isinstance(datetime.fromisoformat(created), datetime)
