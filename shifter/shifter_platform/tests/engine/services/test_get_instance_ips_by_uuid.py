"""Behavior tests for get_instance_ips_by_uuid() in engine/services.

Reads a real ``Range`` row's ``provisioned_instances`` and maps each instance's
uuid to its resolved internal host (host > private_ip > provider metadata),
skipping instances without a uuid or a resolvable IP. No ORM mocking.
"""

import pytest
from django.contrib.auth import get_user_model

from engine.models import Range
from engine.services import get_instance_ips_by_uuid

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="engine-ips@example.com", email="engine-ips@example.com")


def _range(user, instances):
    return Range.objects.create(user=user, status=Range.Status.READY, provisioned_instances=instances)


class TestGetInstanceIpsByUuid:
    def test_returns_empty_when_range_not_found(self):
        assert get_instance_ips_by_uuid(999999) == {}

    def test_returns_empty_when_no_provisioned_instances(self, user):
        assert get_instance_ips_by_uuid(_range(user, None).id) == {}

    def test_maps_uuid_to_resolved_host(self, user):
        range_obj = _range(user, [{"uuid": "i-1", "private_ip": "10.1.1.10"}])
        assert get_instance_ips_by_uuid(range_obj.id) == {"i-1": "10.1.1.10"}

    def test_skips_instances_without_uuid(self, user):
        range_obj = _range(user, [{"private_ip": "10.1.1.10"}, {"uuid": "i-2", "private_ip": "10.1.1.20"}])
        assert get_instance_ips_by_uuid(range_obj.id) == {"i-2": "10.1.1.20"}

    def test_skips_instances_without_resolvable_ip(self, user):
        range_obj = _range(user, [{"uuid": "i-1"}, {"uuid": "i-2", "private_ip": "10.1.1.20"}])
        assert get_instance_ips_by_uuid(range_obj.id) == {"i-2": "10.1.1.20"}

    def test_resolves_via_provider_metadata(self, user):
        # provider_metadata nests the connectivity block under the provider name.
        range_obj = _range(user, [{"uuid": "i-1", "provider_metadata": {"aws": {"private_ip": "10.2.2.2"}}}])
        assert get_instance_ips_by_uuid(range_obj.id) == {"i-1": "10.2.2.2"}

    def test_prefers_host_over_private_ip(self, user):
        range_obj = _range(user, [{"uuid": "i-1", "host": "10.0.0.5", "private_ip": "10.1.1.10"}])
        assert get_instance_ips_by_uuid(range_obj.id) == {"i-1": "10.0.0.5"}
