"""Behavior tests for the management app's user-profile signals.

The ``ManagementConfig.ready()`` post_save wiring is verified through its real
effect — creating/saving a user (auto-)provisions a ``UserProfile`` — rather than
patching ``post_save`` and asserting registration call shapes.
"""

import pytest
from django.contrib.auth import get_user_model

from management.models import UserProfile

pytestmark = pytest.mark.django_db

User = get_user_model()


class TestUserProfileSignals:
    def test_creating_user_auto_creates_profile(self):
        """on_user_created (post_save) provisions a profile for a new user."""
        user = User.objects.create_user(username="apps-create@e.com", email="apps-create@e.com")
        assert UserProfile.objects.filter(user=user).exists()

    def test_saving_existing_user_ensures_profile(self):
        """on_user_saved (post_save) re-ensures the profile on a later save.

        The handler skips when the instance already has a (cached) profile, so
        re-fetch a clean instance after deleting the row before saving.
        """
        user = User.objects.create_user(username="apps-save@e.com", email="apps-save@e.com")
        UserProfile.objects.filter(user=user).delete()

        fresh = User.objects.get(pk=user.pk)
        fresh.save()
        assert UserProfile.objects.filter(user=user).exists()
