"""PostgreSQL arbitration of simultaneous personal-token rotation."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Event
from time import monotonic, sleep
from types import SimpleNamespace

import pytest
from django.db import close_old_connections, connection
from django.utils import timezone

from management.personal_credentials import issue_personal_token, rotate_personal_token
from management.services import principal_for_user
from shared.api_tokens.models import ApiToken
from shared.authorization import AuthorizationDecision, CredentialCeiling, DecisionKind, TargetRef, port
from shared.credentials import CredentialContext
from shared.identity_scope import ResourceScope


@pytest.mark.postgres
@pytest.mark.django_db(transaction=True)
def test_two_rotators_cannot_leave_two_live_replacements(django_user_model, monkeypatch):
    user = django_user_model.objects.create_user(username="rotating-owner")
    principal = principal_for_user(user)
    actor = CredentialContext(
        principal, "session", principal.uuid, CredentialCeiling(frozenset({"installation.read_audit"})), frozenset()
    )
    provider = SimpleNamespace(check=lambda request: AuthorizationDecision(DecisionKind.ALLOWED, "policy_allowed"))
    monkeypatch.setattr(port, "_provider_factory", lambda: provider)
    command = {
        "actor": actor,
        "user": user,
        "name": "rotation",
        "scopes": ["authorization:installation.read_audit"],
        "expires_at": timezone.now() + timedelta(hours=1),
        "target": TargetRef("installation"),
        "scope": ResourceScope("installation"),
    }
    previous, raw = issue_personal_token(**command)
    barrier = Barrier(2)

    def rotate():
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            try:
                return rotate_personal_token(previous.credential_uuid, **command)[0].credential_uuid
            except ValueError:
                return None
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: rotate(), range(2)))
    assert sum(result is not None for result in results) == 1
    assert ApiToken.authenticate(raw) is None
    assert ApiToken.objects.filter(created_by=user, revoked_at__isnull=True).count() == 1


@pytest.mark.postgres
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("operation", ["admin_revoke", "own_revoke", "rotate"])
def test_credential_operations_follow_lifecycle_owner_before_token_order(django_user_model, monkeypatch, operation):
    from management import lifecycle, personal_credentials
    from management.services import AuditContext
    from tests.workspaces.test_account_policy_admin import _actor

    user = django_user_model.objects.create_user(username="overlapping-owner")
    principal = principal_for_user(user)
    owner = CredentialContext(
        principal, "session", principal.uuid, CredentialCeiling(frozenset({"installation.read_audit"})), frozenset()
    )
    administrator = _actor(
        "service", actions=frozenset({"installation.manage_principals", "installation.revoke_personal_tokens"})
    )
    provider = SimpleNamespace(check=lambda request: AuthorizationDecision(DecisionKind.ALLOWED, "policy_allowed"))
    monkeypatch.setattr(port, "_provider_factory", lambda: provider)
    command = {
        "actor": owner,
        "user": user,
        "name": "Overlap",
        "scopes": ["authorization:installation.read_audit"],
        "expires_at": timezone.now() + timedelta(hours=1),
        "target": TargetRef("installation"),
        "scope": ResourceScope("installation"),
    }
    previous, _ = issue_personal_token(**command)
    user_locked, release_lifecycle, credential_started = Event(), Event(), Event()
    original = lifecycle._revoke_live_tokens
    pids = {}

    def revoke_after_owner_lock(locked_user):
        user_locked.set()
        assert release_lifecycle.wait(timeout=15)
        return original(locked_user)

    monkeypatch.setattr(lifecycle, "_revoke_live_tokens", revoke_after_owner_lock)

    def deactivate():
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                pids["lifecycle"] = cursor.fetchone()[0]
            return lifecycle.transition_account(
                user,
                action=lifecycle.AccountLifecycleAction.DEACTIVATE,
                actor=administrator,
                provider=provider,
                audit=AuditContext("principal", None),
            )
        finally:
            close_old_connections()

    def change_credential():
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                pids["credential"] = cursor.fetchone()[0]
            credential_started.set()
            try:
                if operation == "admin_revoke":
                    personal_credentials.admin_revoke_personal_token(administrator, provider, previous.credential_uuid)
                elif operation == "own_revoke":
                    personal_credentials.revoke_own_token(owner, user, previous.credential_uuid)
                else:
                    personal_credentials.rotate_personal_token(previous.credential_uuid, **command)
            except ValueError:
                # A disabling lifecycle may win admission; a deadlock must never
                # replace the bounded rejection or abort the lifecycle itself.
                return "denied"
            return "completed"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        lifecycle_future = executor.submit(deactivate)
        try:
            assert user_locked.wait(timeout=10)
            credential_future = executor.submit(change_credential)
            assert credential_started.wait(timeout=10)
            deadline = monotonic() + 10
            while monotonic() < deadline:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_blocking_pids(%s)", [pids["credential"]])
                    if pids["lifecycle"] in cursor.fetchone()[0]:
                        break
                sleep(0.01)
            else:
                pytest.fail("Credential command never overlapped the locked owner")
        finally:
            release_lifecycle.set()
        assert lifecycle_future.result(timeout=15) == lifecycle.AccountLifecycleState.DEACTIVATED
        assert credential_future.result(timeout=15) in {"completed", "denied"}
    user.refresh_from_db()
    assert not user.is_active
    assert not ApiToken.objects.filter(created_by=user, revoked_at__isnull=True).exists()
