"""Behavior tests for Engine Range model classmethods (#450).

Tests Range.resolve_active_for_instance — the portable pure-Python resolver that
finds the user's active range containing a given instance UUID by iterating the
user's active ranges and calling get_instance_by_uuid on each. This avoids any
provider-specific JSON DB lookup and is correct for N concurrent ranges.
"""

import pytest
from django.contrib.auth import get_user_model

from engine.models import Range

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(
        username="engine-range-model@example.com",
        email="engine-range-model@example.com",
    )


@pytest.fixture
def other_user(db):
    return User.objects.create_user(
        username="engine-range-model-other@example.com",
        email="engine-range-model-other@example.com",
    )


def _make_range(user, instances, *, status=Range.Status.READY):
    return Range.objects.create(
        user=user,
        status=status,
        provisioned_instances=instances,
    )


class TestResolveActiveForInstance:
    """Range.resolve_active_for_instance returns the range that owns a UUID."""

    def test_returns_range_containing_uuid(self, user):
        instance = {"uuid": "target-uuid", "role": "attacker", "os_type": "kali", "private_ip": "10.0.0.1"}
        r = _make_range(user, [instance])
        result = Range.resolve_active_for_instance(user, "target-uuid")
        assert result is not None
        assert result.pk == r.pk

    def test_returns_none_when_uuid_not_in_any_range(self, user):
        instance = {"uuid": "present-uuid", "role": "attacker", "os_type": "kali", "private_ip": "10.0.0.1"}
        _make_range(user, [instance])
        result = Range.resolve_active_for_instance(user, "absent-uuid")
        assert result is None

    def test_returns_none_when_user_has_no_active_ranges(self, user):
        result = Range.resolve_active_for_instance(user, "any-uuid")
        assert result is None

    def test_resolves_correct_range_when_user_has_two_active_ranges(self, user):
        """With two simultaneous active ranges, the correct one is selected by UUID."""
        instance_a = {"uuid": "uuid-range-a", "role": "attacker", "os_type": "kali", "private_ip": "10.0.0.1"}
        instance_b = {"uuid": "uuid-range-b", "role": "attacker", "os_type": "kali", "private_ip": "10.0.0.2"}
        range_a = _make_range(user, [instance_a])
        range_b = _make_range(user, [instance_b])

        result_a = Range.resolve_active_for_instance(user, "uuid-range-a")
        result_b = Range.resolve_active_for_instance(user, "uuid-range-b")

        assert result_a is not None
        assert result_b is not None
        assert result_a.pk == range_a.pk
        assert result_b.pk == range_b.pk

    def test_does_not_return_range_owned_by_other_user(self, user, other_user):
        instance = {"uuid": "other-uuid", "role": "attacker", "os_type": "kali", "private_ip": "10.0.0.1"}
        _make_range(other_user, [instance])
        result = Range.resolve_active_for_instance(user, "other-uuid")
        assert result is None

    def test_excludes_terminal_ranges(self, user):
        """DESTROYED and FAILED ranges are excluded (same set as get_active_for_user)."""
        instance = {"uuid": "dead-uuid", "role": "attacker", "os_type": "kali", "private_ip": "10.0.0.1"}
        _make_range(user, [instance], status=Range.Status.DESTROYED)
        _make_range(user, [instance], status=Range.Status.FAILED)
        result = Range.resolve_active_for_instance(user, "dead-uuid")
        assert result is None

    def test_includes_non_ready_active_ranges(self, user):
        """PROVISIONING / PENDING ranges are included so the caller can check READY status."""
        instance = {"uuid": "prov-uuid", "role": "attacker", "os_type": "kali", "private_ip": "10.0.0.1"}
        r = _make_range(user, [instance], status=Range.Status.PROVISIONING)
        result = Range.resolve_active_for_instance(user, "prov-uuid")
        assert result is not None
        assert result.pk == r.pk
