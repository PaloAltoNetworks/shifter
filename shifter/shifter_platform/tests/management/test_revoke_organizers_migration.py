"""Tests for the #1516 data migration that revokes self-service-derived organizers.

The repo has no dedicated migration-test harness, so the migration's forward
function is imported directly and driven against seeded data with the real app
registry. It proves the fail-closed revocation (per maintainer decision
2026-07-11): every current ``CTF Organizer`` member loses the group, each removal
is audited, and non-organizer memberships are untouched.
"""

from __future__ import annotations

import importlib

import pytest
from django.apps import apps as global_apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from risk_register.models import AuditLog
from shared.audit import AuditAction
from shared.auth import CTF_ORGANIZER_GROUP, CTF_PARTICIPANT_GROUP

User = get_user_model()

_MIGRATION = importlib.import_module("management.migrations.0008_revoke_self_service_organizers")


@pytest.mark.django_db
def test_migration_revokes_and_audits_existing_organizers():
    organizer = Group.objects.get_or_create(name=CTF_ORGANIZER_GROUP)[0]
    participant = Group.objects.get_or_create(name=CTF_PARTICIPANT_GROUP)[0]

    org_user = User.objects.create_user(username="org@example.com", email="org@example.com")
    org_user.groups.add(organizer, participant)
    plain_participant = User.objects.create_user(username="p@example.com", email="p@example.com")
    plain_participant.groups.add(participant)

    _MIGRATION.revoke_self_service_organizers(global_apps, None)

    org_user.refresh_from_db()
    plain_participant.refresh_from_db()
    # Organizer removed; the user's other (participant) membership is untouched.
    assert set(org_user.groups.values_list("name", flat=True)) == {CTF_PARTICIPANT_GROUP}
    # A non-organizer is unaffected and gets no audit row.
    assert set(plain_participant.groups.values_list("name", flat=True)) == {CTF_PARTICIPANT_GROUP}

    # The migration's own revocation audit row, isolated by its context (the
    # organizer-authority m2m signal also audits real-model group changes in this
    # test, so filter to the migration's row rather than asserting a total count).
    migration_rows = AuditLog.objects.filter(
        entity_type="user",
        entity_id=org_user.id,
        action=AuditAction.ROLE_SYNC,
        context__icontains="separated from self-service",
    )
    assert migration_rows.count() == 1
    row = migration_rows.get()
    assert CTF_ORGANIZER_GROUP in row.previous_state["groups"]
    assert CTF_ORGANIZER_GROUP not in row.new_state["groups"]
    # A non-organizer is unaffected: no organizer change, so no audit row at all.
    assert AuditLog.objects.filter(entity_id=plain_participant.id).count() == 0


@pytest.mark.django_db
def test_migration_no_op_when_no_organizer_members():
    Group.objects.get_or_create(name=CTF_ORGANIZER_GROUP)
    _MIGRATION.revoke_self_service_organizers(global_apps, None)
    assert AuditLog.objects.filter(action=AuditAction.ROLE_SYNC).count() == 0
