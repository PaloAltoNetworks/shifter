"""Behavior tests for the engine ``Range`` model.

Value-logic (status enums, computed properties, ``get_instance_by_uuid``) is
exercised on in-memory instances; the manager lookups
(``get_active_for_user`` / ``get_destroyable_for_user``) run against the real
database. ``allocate_subnet_index`` has its full behavior matrix in
``test_range_api_agents_subnets.py``.
"""

import pytest

from engine.models import Range


class TestRangeStatusEnums:
    def test_range_status_enum_values(self):
        assert Range.Status.PENDING == "pending"
        assert Range.Status.PROVISIONING == "provisioning"
        assert Range.Status.READY == "ready"
        assert Range.Status.PAUSED == "paused"
        assert Range.Status.DESTROYED == "destroyed"
        assert Range.Status.FAILED == "failed"

    def test_terminal_statuses_defined(self):
        from shared.enums import TERMINAL_STATUSES, ResourceStatus

        assert ResourceStatus.DESTROYED in TERMINAL_STATUSES
        assert ResourceStatus.FAILED in TERMINAL_STATUSES

    def test_cancellable_statuses_defined(self):
        from shared.enums import CANCELLABLE_STATUSES, ResourceStatus

        assert ResourceStatus.PENDING in CANCELLABLE_STATUSES
        assert ResourceStatus.PROVISIONING in CANCELLABLE_STATUSES


class TestRangeUserLookups:
    """get_active_for_user / get_destroyable_for_user against real rows."""

    @pytest.fixture
    def user(self, db, django_user_model):
        return django_user_model.objects.create_user(
            username="rangelookup@example.com", email="rangelookup@example.com"
        )

    def test_get_active_returns_none_when_no_range(self, user):
        assert Range.get_active_for_user(user) is None

    def test_get_active_returns_active_range(self, user):
        active = Range.objects.create(user=user, status=Range.Status.READY)
        assert Range.get_active_for_user(user) == active

    def test_get_active_excludes_destroyed_and_destroying(self, user):
        Range.objects.create(user=user, status=Range.Status.DESTROYED)
        Range.objects.create(user=user, status=Range.Status.DESTROYING)
        assert Range.get_active_for_user(user) is None

    def test_get_active_ignores_other_users(self, user, django_user_model):
        other = django_user_model.objects.create_user(username="rl-other@example.com", email="rl-other@example.com")
        Range.objects.create(user=other, status=Range.Status.READY)
        assert Range.get_active_for_user(user) is None

    def test_get_destroyable_includes_failed(self, user):
        failed = Range.objects.create(user=user, status=Range.Status.FAILED)
        assert Range.get_destroyable_for_user(user) == failed


class TestRangeProperties:
    def test_is_usable_ready(self):
        assert Range(user_id=1, status=Range.Status.READY).is_usable is True

    def test_is_usable_paused(self):
        assert Range(user_id=1, status=Range.Status.PAUSED).is_usable is True

    def test_is_usable_failed(self):
        assert Range(user_id=1, status=Range.Status.FAILED).is_usable is False

    def test_is_terminal_destroyed(self):
        assert Range(user_id=1, status=Range.Status.DESTROYED).is_terminal is True

    def test_is_terminal_failed(self):
        assert Range(user_id=1, status=Range.Status.FAILED).is_terminal is True

    def test_is_terminal_ready(self):
        assert Range(user_id=1, status=Range.Status.READY).is_terminal is False


class TestRangeGetInstanceByUUID:
    def _range(self, instances):
        return Range(user_id=1, status=Range.Status.READY, provisioned_instances=instances)

    def test_returns_instance_when_uuid_matches(self):
        data = {"uuid": "abc-123-def", "role": "attacker", "private_ip": "10.1.1.10"}
        assert self._range([data]).get_instance_by_uuid("abc-123-def") == data

    def test_returns_correct_instance_from_multiple(self):
        attacker = {"uuid": "attacker-111", "role": "attacker"}
        victim = {"uuid": "victim-222", "role": "victim"}
        assert self._range([attacker, victim]).get_instance_by_uuid("victim-222") == victim

    def test_returns_none_when_uuid_not_found(self):
        assert self._range([{"uuid": "existing", "role": "attacker"}]).get_instance_by_uuid("nope") is None

    def test_returns_none_when_empty_or_null(self):
        for instances in ([], None):
            assert self._range(instances).get_instance_by_uuid("any") is None

    def test_raises_on_invalid_uuid(self):
        range_obj = self._range([{"uuid": "test", "role": "attacker"}])
        for invalid in (None, ""):
            with pytest.raises(ValueError, match="uuid"):
                range_obj.get_instance_by_uuid(invalid)

    def test_has_no_side_effects(self):
        data = {"uuid": "abc-123-def", "role": "attacker"}
        range_obj = self._range([data])
        original = [dict(data)]
        range_obj.get_instance_by_uuid("abc-123-def")
        assert range_obj.provisioned_instances == original

    def test_skips_instances_without_uuid_key(self):
        malformed = {"role": "attacker"}
        valid = {"uuid": "valid-uuid", "role": "victim"}
        assert self._range([malformed, valid]).get_instance_by_uuid("valid-uuid") == valid

    def test_returns_none_when_all_instances_malformed(self):
        assert self._range([{"role": "attacker"}, {"role": "victim"}]).get_instance_by_uuid("any") is None

    def test_case_sensitive_uuid_match(self):
        assert self._range([{"uuid": "ABC-123", "role": "attacker"}]).get_instance_by_uuid("abc-123") is None
