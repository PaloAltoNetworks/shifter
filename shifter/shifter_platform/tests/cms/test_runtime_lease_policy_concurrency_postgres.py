"""PostgreSQL concurrency proof for runtime Mission Control lease policy (#2169)."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.contrib.auth import get_user_model
from django.db import close_old_connections

from shared.audit import AuditEntityType
from shared.mission_control_lease import MissionControlLeasePolicy
from shared.models import AuditLog

pytestmark = [pytest.mark.postgres, pytest.mark.django_db(transaction=True)]

User = get_user_model()


def test_concurrent_create_commands_have_one_revision_checked_winner():
    from cms.models import MissionControlTenantLeasePolicy
    from cms.services import (
        LeasePolicyAuditContext,
        MissionControlLeasePolicyAdminError,
        replace_tenant_lease_policy,
    )

    admin = User.objects.create_superuser(username="concurrent-lease-admin", password="pw")
    barrier = threading.Barrier(2)

    def replace(initial_days: int) -> str:
        close_old_connections()
        try:
            actor = User.objects.get(pk=admin.pk)
            barrier.wait(timeout=10)
            replace_tenant_lease_policy(
                actor,
                MissionControlLeasePolicy(
                    initial_days=initial_days,
                    extension_days=7,
                    maximum_days=90,
                ),
                expected_revision=0,
                audit=LeasePolicyAuditContext(actor_type="user", actor_id=actor.pk),
            )
            return "written"
        except MissionControlLeasePolicyAdminError as exc:
            return exc.kind.value
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(replace, (14, 21)))

    assert sorted(results) == ["revision_conflict", "written"]
    assert MissionControlTenantLeasePolicy.objects.get().revision == 1
    assert AuditLog.objects.filter(entity_type=AuditEntityType.CONFIG).count() == 1
