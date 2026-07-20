"""Behavior tests for cms.services.get_storage_used.

Drives the storage-quota service against real ``AgentConfig`` rows instead of
patching ``cms.assets.services.get_storage_used``.
"""

import pytest
from django.contrib.auth import get_user_model

from cms import services
from shared.constants import USER_CANNOT_BE_NONE

pytestmark = pytest.mark.django_db

User = get_user_model()

_MB = 1024 * 1024


@pytest.fixture
def user(db):
    return User.objects.create_user(username="storage@example.com", email="storage@example.com")


class TestGetStorageUsed:
    def test_returns_zero_when_no_agents(self, user):
        assert services.get_storage_used(user) == 0

    def test_sums_active_agent_bytes(self, user, make_agent):
        make_agent(user, file_size_bytes=5 * _MB)
        make_agent(user, file_size_bytes=2 * _MB)
        assert services.get_storage_used(user) == 7 * _MB

    def test_excludes_other_users_agents(self, user, make_agent, django_user_model):
        other = django_user_model.objects.create_user(username="storage-other@e.com", email="storage-other@e.com")
        make_agent(user, file_size_bytes=3 * _MB)
        make_agent(other, file_size_bytes=9 * _MB)
        assert services.get_storage_used(user) == 3 * _MB

    def test_returns_int(self, user, make_agent):
        make_agent(user, file_size_bytes=1000)
        assert isinstance(services.get_storage_used(user), int)

    def test_raises_typeerror_when_user_is_none(self):
        with pytest.raises(TypeError, match=USER_CANNOT_BE_NONE):
            services.get_storage_used(None)

    def test_raises_typeerror_when_user_is_wrong_type(self):
        with pytest.raises(TypeError, match="user must be a User instance"):
            services.get_storage_used("not_a_user")

    def test_raises_valueerror_when_user_is_unsaved(self):
        with pytest.raises(ValueError, match="user must be saved"):
            services.get_storage_used(User(username="unsaved"))
