"""Tests for the account lifecycle transition service (PLAT-236, #1943).

Drives the ``management.lifecycle`` service against real ``User`` /
``UserProfile`` / ``ApiToken`` / ``AuditLog`` rows: derived state, the closed
transition table, idempotency, the self / superuser / last-active-superuser
guards, token revocation on a disabling transition, and the server-derived
available-action hints.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from management import lifecycle
from management.services import AuditContext
from shared.api_tokens.models import ApiToken
from shared.api_tokens.scopes import MISSION_CONTROL_RANGE_READ
from shared.audit import AuditAction, AuditActorType, AuditEntityType
from shared.models import AuditLog

pytestmark = pytest.mark.django_db

User = get_user_model()

State = lifecycle.AccountLifecycleState
Action = lifecycle.AccountLifecycleAction


def _make_user(username: str, **kwargs) -> User:
    return User.objects.create_user(username=username, email=f"{username}@example.com", **kwargs)


def _audit(actor: User) -> AuditContext:
    return AuditContext(actor_type=AuditActorType.USER, actor_id=actor.id)


@pytest.fixture
def actor() -> User:
    return User.objects.create_superuser(username="root", email="root@example.com", password="pw")


@pytest.fixture
def target() -> User:
    return _make_user("target")


class TestDerivedState:
    def test_active(self, target):
        assert lifecycle.derive_lifecycle_state(target) == State.ACTIVE

    def test_deactivated(self, target):
        target.is_active = False
        target.save(update_fields=["is_active"])
        assert lifecycle.derive_lifecycle_state(target) == State.DEACTIVATED

    def test_suspended(self, target):
        target.is_active = False
        target.save(update_fields=["is_active"])
        target.profile.suspended_at = timezone.now()
        target.profile.save(update_fields=["suspended_at"])
        assert lifecycle.derive_lifecycle_state(target) == State.SUSPENDED

    def test_deleted_takes_precedence(self, target):
        target.profile.suspended_at = timezone.now()
        target.profile.deleted_at = timezone.now()
        target.profile.save(update_fields=["suspended_at", "deleted_at"])
        assert lifecycle.derive_lifecycle_state(target) == State.DELETED


class TestTransitions:
    def test_deactivate_then_activate(self, actor, target):
        lifecycle.transition_account(target, action=Action.DEACTIVATE, actor=actor, audit=_audit(actor))
        target.refresh_from_db()
        assert target.is_active is False
        assert target.profile.suspended_at is None
        assert lifecycle.derive_lifecycle_state(target) == State.DEACTIVATED

        lifecycle.transition_account(target, action=Action.ACTIVATE, actor=actor, audit=_audit(actor))
        target.refresh_from_db()
        assert target.is_active is True
        assert lifecycle.derive_lifecycle_state(target) == State.ACTIVE

    def test_suspend_sets_marker_and_blocks_auth(self, actor, target):
        lifecycle.transition_account(target, action=Action.SUSPEND, actor=actor, audit=_audit(actor))
        target.refresh_from_db()
        assert target.is_active is False
        assert target.profile.suspended_at is not None
        assert lifecycle.derive_lifecycle_state(target) == State.SUSPENDED

    def test_reinstate_clears_suspension(self, actor, target):
        lifecycle.transition_account(target, action=Action.SUSPEND, actor=actor, audit=_audit(actor))
        lifecycle.transition_account(target, action=Action.ACTIVATE, actor=actor, audit=_audit(actor))
        target.refresh_from_db()
        assert target.is_active is True
        assert target.profile.suspended_at is None

    def test_deactivate_clears_suspension_marker(self, actor, target):
        lifecycle.transition_account(target, action=Action.SUSPEND, actor=actor, audit=_audit(actor))
        lifecycle.transition_account(target, action=Action.DEACTIVATE, actor=actor, audit=_audit(actor))
        target.refresh_from_db()
        assert target.profile.suspended_at is None
        assert lifecycle.derive_lifecycle_state(target) == State.DEACTIVATED

    def test_delete_disables_auth_and_audits_delete(self, actor, target):
        lifecycle.transition_account(target, action=Action.DELETE, actor=actor, audit=_audit(actor))
        target.refresh_from_db()
        assert target.is_active is False
        assert target.profile.deleted_at is not None
        assert AuditLog.objects.filter(
            entity_type=AuditEntityType.USER, entity_id=target.id, action=AuditAction.DELETE
        ).exists()

    def test_disabling_account_revokes_model_access_authority_in_same_service(self, actor, target):
        from engine.models import SharingAuthorityFence
        from engine.services import publish_authority_fence

        deployment_id = "11111111-1111-4111-8111-111111111111"
        authority_ref = {"owner": "management", "reference": f"user:{target.pk}"}
        publish_authority_fence(
            deployment_id=deployment_id,
            authority_ref=authority_ref,
            authority_revision=1,
            state="allowed",
        )

        lifecycle.transition_account(target, action=Action.DEACTIVATE, actor=actor, audit=_audit(actor))

        fence = SharingAuthorityFence.objects.get(
            deployment_id=deployment_id,
            authority_owner="management",
            authority_reference=f"user:{target.pk}",
        )
        assert (fence.authority_revision, fence.state) == (2, "revoked")

    def test_activate_deleted_account_rejected(self, actor, target):
        audit = _audit(actor)
        lifecycle.transition_account(target, action=Action.DELETE, actor=actor, audit=audit)
        with pytest.raises(lifecycle.AccountLifecycleError) as exc:
            lifecycle.transition_account(target, action=Action.ACTIVATE, actor=actor, audit=audit)
        assert exc.value.code == "account_deleted"

    def test_anonymized_account_cannot_transition(self, actor, target):
        target.is_active = False
        target.save(update_fields=["is_active"])
        target.profile.anonymized_at = timezone.now()
        target.profile.save(update_fields=["anonymized_at"])
        audit = _audit(actor)
        with pytest.raises(lifecycle.AccountLifecycleError) as exc:
            lifecycle.transition_account(target, action=Action.ACTIVATE, actor=actor, audit=audit)
        assert exc.value.code == "account_anonymized"

    def test_idempotent_noop_writes_no_audit(self, actor, target):
        # target is already active; activate is a no-op.
        before = AuditLog.objects.filter(entity_type=AuditEntityType.USER, entity_id=target.id).count()
        result = lifecycle.transition_account(target, action=Action.ACTIVATE, actor=actor, audit=_audit(actor))
        after = AuditLog.objects.filter(entity_type=AuditEntityType.USER, entity_id=target.id).count()
        assert result == State.ACTIVE
        assert after == before


class TestGuards:
    def test_self_disable_forbidden(self, actor):
        audit = _audit(actor)
        with pytest.raises(lifecycle.AccountLifecycleError) as exc:
            lifecycle.transition_account(actor, action=Action.DEACTIVATE, actor=actor, audit=audit)
        assert exc.value.code == "self_action_forbidden"

    def test_non_superuser_cannot_disable_superuser(self, target):
        superuser = User.objects.create_superuser(username="su2", email="su2@example.com", password="pw")
        staff = _make_user("staff", is_staff=True)
        audit = _audit(staff)
        with pytest.raises(lifecycle.AccountLifecycleError) as exc:
            lifecycle.transition_account(superuser, action=Action.DEACTIVATE, actor=staff, audit=audit)
        assert exc.value.code == "superuser_protected"

    def test_last_active_superuser_protected(self, actor):
        # actor is the only active superuser; a second admin cannot disable it.
        other_su = User.objects.create_superuser(username="su3", email="su3@example.com", password="pw")
        other_su.is_active = False  # inactive, so `actor` is the last ACTIVE superuser
        other_su.save(update_fields=["is_active"])
        audit = _audit(other_su)
        with pytest.raises(lifecycle.AccountLifecycleError) as exc:
            lifecycle.transition_account(actor, action=Action.DEACTIVATE, actor=other_su, audit=audit)
        assert exc.value.code == "last_superuser_protected"


class TestTokenRevocation:
    def test_disable_revokes_live_tokens(self, actor, target):
        token, _raw = ApiToken.create_token(name="t", scopes=[MISSION_CONTROL_RANGE_READ], created_by=target)
        assert token.is_active
        lifecycle.transition_account(target, action=Action.SUSPEND, actor=actor, audit=_audit(actor))
        token.refresh_from_db()
        assert token.revoked_at is not None

    def test_activate_does_not_resurrect_tokens(self, actor, target):
        token, _raw = ApiToken.create_token(name="t", scopes=[MISSION_CONTROL_RANGE_READ], created_by=target)
        lifecycle.transition_account(target, action=Action.DEACTIVATE, actor=actor, audit=_audit(actor))
        lifecycle.transition_account(target, action=Action.ACTIVATE, actor=actor, audit=_audit(actor))
        token.refresh_from_db()
        assert token.revoked_at is not None


class TestAvailableActions:
    def test_active_account_actions(self, actor, target):
        actions = lifecycle.available_actions(target, actor)
        assert "deactivate" in actions
        assert "suspend" in actions
        assert "activate" not in actions  # already active

    def test_deleted_account_has_no_lifecycle_actions(self, actor, target):
        lifecycle.transition_account(target, action=Action.DELETE, actor=actor, audit=_audit(actor))
        target.refresh_from_db()
        actions = lifecycle.available_actions(target, actor)
        assert "activate" not in actions
        assert "deactivate" not in actions
        assert "suspend" not in actions

    def test_self_target_excludes_disabling_actions(self, actor):
        actions = lifecycle.available_actions(actor, actor)
        assert "deactivate" not in actions
        assert "suspend" not in actions
