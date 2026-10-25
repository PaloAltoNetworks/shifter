"""Behavior tests for the management app's identity-row signals.

The ``ManagementConfig.ready()`` post_save wiring is verified through its real
effect — creating/saving a user (auto-)provisions identity rows — rather than
patching ``post_save`` and asserting registration call shapes.
"""

import gc

import pytest
from django.contrib.auth import get_user_model

from management.models import Principal, UserProfile

pytestmark = pytest.mark.django_db

User = get_user_model()


class TestUserProfileSignals:
    def test_receiver_survives_garbage_collection(self):
        """Startup must retain the local receiver for long-running workers."""
        gc.collect()

        user = User.objects.create_user(username="apps-gc@e.com", email="apps-gc@e.com")

        assert UserProfile.objects.filter(user=user).exists()
        assert Principal.objects.filter(user=user).exists()

    def test_creating_user_auto_creates_profile(self):
        """The save signal provisions a profile for a new user."""
        user = User.objects.create_user(username="apps-create@e.com", email="apps-create@e.com")
        assert UserProfile.objects.filter(user=user).exists()

    def test_saving_existing_user_ensures_profile(self):
        """The save signal re-ensures a missing profile on a later save."""
        user = User.objects.create_user(username="apps-save@e.com", email="apps-save@e.com")
        UserProfile.objects.filter(user=user).delete()

        fresh = User.objects.get(pk=user.pk)
        fresh.save()
        assert UserProfile.objects.filter(user=user).exists()


@pytest.mark.django_db(transaction=True)
def test_save_reconciles_principal_after_autocommit_creation_audit_failure(monkeypatch):
    from management.models import Principal
    from management.services import PrincipalConflictError, principal_for_user
    from shared.audit import get_audit_writer
    from shared.models import AuditLog

    def unavailable(_event):
        raise RuntimeError("Synthetic audit outage")

    with monkeypatch.context() as outage:
        outage.setattr(get_audit_writer(), "write", unavailable)
        with pytest.raises(RuntimeError, match="Synthetic audit outage"):
            User.objects.create_user(username="interrupted-provisioning")
    user = User.objects.get(username="interrupted-provisioning")
    assert not Principal.objects.filter(user=user).exists()
    with pytest.raises(PrincipalConflictError):
        principal_for_user(user)
    user.save()
    principal = Principal.objects.get(user=user)
    assert principal_for_user(user).uuid == principal.uuid
    assert UserProfile.objects.filter(user=user).exists()
    user.save()
    assert Principal.objects.filter(user=user).count() == 1
    assert AuditLog.objects.filter(entity_type="principal", entity_id=principal.pk, action="create").count() == 1
