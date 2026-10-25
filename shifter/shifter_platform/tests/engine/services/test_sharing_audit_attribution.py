"""Real-actor attribution for model-access sharing audit events (M09, #2126).

The sharing persistence audit helper historically recorded a ``SYSTEM`` actor.
An authenticated management mutation must record the real server-derived actor
derived from the publisher identity (management-preflight-2126.md).
"""

from __future__ import annotations

import pytest

from shared.model_access import OwnedReference
from shared.models import AuditLog

pytestmark = pytest.mark.django_db


def _latest(action: str) -> AuditLog:
    return AuditLog.objects.filter(action=action).order_by("-id").first()


def test_actor_from_publisher_maps_management_user_and_operator():
    from engine.services._sharing_persistence import _actor_from_publisher
    from shared.audit import AuditActorType

    assert _actor_from_publisher(OwnedReference(owner="management", reference="user:5")) == (
        AuditActorType.USER,
        5,
    )
    assert _actor_from_publisher(OwnedReference(owner="management", reference="operator:9")) == (
        AuditActorType.USER,
        9,
    )


def test_actor_from_publisher_falls_back_to_system_for_unknown_publisher():
    from engine.services._sharing_persistence import _actor_from_publisher
    from shared.audit import AuditActorType

    assert _actor_from_publisher(None) == (AuditActorType.SYSTEM, None)
    assert _actor_from_publisher(OwnedReference(owner="deployment", reference="range:x")) == (
        AuditActorType.SYSTEM,
        None,
    )


def test_audit_records_real_publisher_actor():
    from engine.services._sharing_persistence import _audit

    _audit(
        "sharing_publish",
        entity_id=1,
        context="binding=b revision=1",
        publisher=OwnedReference(owner="management", reference="user:5"),
    )
    row = _latest("sharing_publish")
    assert row is not None
    assert row.actor_type == "user"
    assert row.actor_id == 5


def test_audit_without_publisher_stays_system():
    from engine.services._sharing_persistence import _audit

    _audit("sharing_drain", entity_id=2, context="binding=b revision=2")
    row = _latest("sharing_drain")
    assert row is not None
    assert row.actor_type == "system"
    assert row.actor_id is None
