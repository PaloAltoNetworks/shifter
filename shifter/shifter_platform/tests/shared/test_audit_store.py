"""Behavioral coverage for the platform-owned durable audit store."""

from __future__ import annotations

import gzip
import json
from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from django.contrib import admin
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from shared.api_tokens.models import ApiToken
from shared.audit import AuditAction, AuditActorType, AuditEntityType, AuditEvent
from shared.audit_adapter import DjangoAuditLogWriter
from shared.models import AuditLog

pytestmark = pytest.mark.django_db

AUDIT_URL = "/api/v1/audit/"


@pytest.fixture
def client() -> APIClient:
    return APIClient()


@pytest.fixture
def staff_user(django_user_model):
    return django_user_model.objects.create_user(
        username="audit-staff",
        email="audit-staff@example.com",
        password="pw",
        is_staff=True,
    )


@pytest.fixture
def regular_user(django_user_model):
    return django_user_model.objects.create_user(
        username="audit-user",
        email="audit-user@example.com",
        password="pw",
    )


def test_writer_persists_to_shared_audit_table():
    DjangoAuditLogWriter().write(
        AuditEvent(
            entity_type=AuditEntityType.RANGE,
            entity_id=7,
            action=AuditAction.PROVISION,
            actor_type=AuditActorType.SYSTEM,
            context="shared store",
        )
    )

    stored = AuditLog.objects.get(entity_type=AuditEntityType.RANGE, entity_id=7)
    assert stored.context == "shared store"
    assert stored._meta.db_table == "shared_auditlog"


def test_staff_session_can_read_audit_rows(client, staff_user):
    AuditLog.objects.create(
        entity_type=AuditEntityType.RANGE,
        entity_id=7,
        action=AuditAction.PROVISION,
        actor_type=AuditActorType.SYSTEM,
    )
    client.force_login(staff_user)

    response = client.get(AUDIT_URL)

    assert response.status_code == 200
    assert response.json()["results"][0]["entity_type"] == AuditEntityType.RANGE


def test_non_staff_session_is_denied_and_denial_is_audited(client, regular_user):
    client.force_login(regular_user)

    response = client.get(AUDIT_URL)

    assert response.status_code == 403
    assert AuditLog.objects.filter(action=AuditAction.ACCESS_DENIED).exists()


def test_platform_token_cannot_read_audit_rows(client, staff_user):
    _, raw = ApiToken.create_token(
        name="range-reader",
        created_by=staff_user,
        scopes=["mission_control:range:read"],
    )
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")

    response = client.get(AUDIT_URL)

    assert response.status_code == 403
    assert AuditLog.objects.filter(action=AuditAction.ACCESS_DENIED).exists()


def test_anonymous_cannot_read_audit_rows(client):
    response = client.get(AUDIT_URL)

    assert response.status_code in {401, 403}
    assert AuditLog.objects.filter(action=AuditAction.ACCESS_DENIED).exists()


def test_audit_read_filters_are_preserved(client, staff_user):
    AuditLog.objects.create(
        entity_type=AuditEntityType.RANGE,
        entity_id=7,
        action=AuditAction.PROVISION,
        actor_type=AuditActorType.SYSTEM,
        request_id="keep",
    )
    AuditLog.objects.create(
        entity_type=AuditEntityType.USER,
        entity_id=8,
        action=AuditAction.UPDATE,
        actor_type=AuditActorType.SYSTEM,
        request_id="skip",
    )
    client.force_login(staff_user)

    response = client.get(AUDIT_URL, {"entity_type": "range", "request_id": "keep"})

    assert response.status_code == 200
    assert [row["request_id"] for row in response.json()["results"]] == ["keep"]


def test_audit_read_filters_by_actor_entity_time_and_action(client, staff_user):
    base = timezone.now()
    keep = AuditLog.objects.create(
        entity_type=AuditEntityType.WORKSPACE_MEMBERSHIP,
        entity_id=42,
        action=AuditAction.ROLE_SYNC,
        actor_type=AuditActorType.USER,
        actor_id=5,
    )
    AuditLog.objects.filter(pk=keep.pk).update(timestamp=base - timedelta(hours=1))
    # Wrong actor.
    other_actor = AuditLog.objects.create(
        entity_type=AuditEntityType.WORKSPACE_MEMBERSHIP,
        entity_id=42,
        action=AuditAction.ROLE_SYNC,
        actor_type=AuditActorType.USER,
        actor_id=6,
    )
    AuditLog.objects.filter(pk=other_actor.pk).update(timestamp=base - timedelta(hours=1))
    # Right actor/entity/action but outside the time window.
    too_old = AuditLog.objects.create(
        entity_type=AuditEntityType.WORKSPACE_MEMBERSHIP,
        entity_id=42,
        action=AuditAction.ROLE_SYNC,
        actor_type=AuditActorType.USER,
        actor_id=5,
    )
    AuditLog.objects.filter(pk=too_old.pk).update(timestamp=base - timedelta(days=5))
    client.force_login(staff_user)

    response = client.get(
        AUDIT_URL,
        {
            "actor_type": "user",
            "actor_id": "5",
            "entity_type": "workspace_membership",
            "entity_id": "42",
            "action": "role_sync",
            "from_date": (base - timedelta(days=1)).isoformat(),
            "to_date": base.isoformat(),
        },
    )

    assert response.status_code == 200
    ids = [row["id"] for row in response.json()["results"]]
    assert ids == [keep.pk]


def test_audit_read_rejects_malformed_entity_id(client, staff_user):
    client.force_login(staff_user)
    response = client.get(AUDIT_URL, {"entity_id": "not-an-int"})
    assert response.status_code == 400
    assert response.json()["error"]["code"]


def test_audit_read_rejects_malformed_date(client, staff_user):
    client.force_login(staff_user)
    response = client.get(AUDIT_URL, {"from_date": "not-a-date"})
    assert response.status_code == 400


def test_audit_read_rejects_inverted_time_range(client, staff_user):
    base = timezone.now()
    client.force_login(staff_user)
    response = client.get(
        AUDIT_URL,
        {"from_date": base.isoformat(), "to_date": (base - timedelta(days=1)).isoformat()},
    )
    assert response.status_code == 400


def test_audit_read_is_read_only(client, staff_user):
    client.force_login(staff_user)
    assert client.post(AUDIT_URL, {}, format="json").status_code == 405
    assert client.delete(AUDIT_URL).status_code == 405


def test_successful_audit_read_writes_no_audit_row(client, staff_user):
    AuditLog.objects.create(
        entity_type=AuditEntityType.RANGE,
        entity_id=7,
        action=AuditAction.PROVISION,
        actor_type=AuditActorType.SYSTEM,
    )
    client.force_login(staff_user)
    before = AuditLog.objects.count()

    response = client.get(AUDIT_URL)

    assert response.status_code == 200
    # Reading the feed must not grow the feed (no successful-read write amplification).
    assert AuditLog.objects.count() == before
    assert not AuditLog.objects.filter(action=AuditAction.ACCESS_DENIED).exists()


def test_audit_read_orders_by_timestamp_then_id_descending(client, staff_user):
    shared_ts = timezone.now()
    first = AuditLog.objects.create(
        entity_type=AuditEntityType.RANGE,
        entity_id=1,
        action=AuditAction.PROVISION,
        actor_type=AuditActorType.SYSTEM,
    )
    second = AuditLog.objects.create(
        entity_type=AuditEntityType.RANGE,
        entity_id=2,
        action=AuditAction.PROVISION,
        actor_type=AuditActorType.SYSTEM,
    )
    # Force an exact timestamp tie so ordering must fall through to -id.
    AuditLog.objects.filter(pk__in=[first.pk, second.pk]).update(timestamp=shared_ts)
    client.force_login(staff_user)

    ids = [row["id"] for row in client.get(AUDIT_URL).json()["results"]]

    assert ids.index(second.pk) < ids.index(first.pk)


def test_audit_read_tolerates_historical_unknown_vocabulary(client, staff_user):
    # A row written under retired vocabulary must remain readable and filterable.
    AuditLog.objects.create(
        entity_type="retired_entity",
        entity_id=3,
        action="retired_action",
        actor_type=AuditActorType.SYSTEM,
    )
    client.force_login(staff_user)

    response = client.get(AUDIT_URL, {"entity_type": "retired_entity", "action": "retired_action"})

    assert response.status_code == 200
    rows = response.json()["results"]
    assert [row["entity_type"] for row in rows] == ["retired_entity"]
    assert rows[0]["action"] == "retired_action"


def test_audit_archive_command_remains_available(capsys):
    row = AuditLog.objects.create(
        entity_type=AuditEntityType.RANGE,
        entity_id=7,
        action=AuditAction.PROVISION,
        actor_type=AuditActorType.SYSTEM,
    )

    call_command("audit_archive", dry_run=True, retention_days=0)

    assert "Dry run - no changes made" in capsys.readouterr().out
    assert AuditLog.objects.filter(pk=row.pk).exists()


@pytest.mark.parametrize("no_delete", [False, True])
def test_audit_archive_uploads_each_row_once(monkeypatch, no_delete):
    row = AuditLog.objects.create(
        entity_type=AuditEntityType.RANGE,
        entity_id=9,
        action=AuditAction.PROVISION,
        actor_type=AuditActorType.SYSTEM,
        context="archive me",
    )
    AuditLog.objects.filter(pk=row.pk).update(timestamp=timezone.now() - timedelta(days=2))
    s3_client = MagicMock()
    sts_client = MagicMock()
    sts_client.get_caller_identity.return_value = {"Account": "123456789012"}

    def _client(service_name):
        return {"s3": s3_client, "sts": sts_client}[service_name]

    monkeypatch.setattr("boto3.client", _client)
    monkeypatch.setattr("django.conf.settings.LOGS_BUCKET_NAME", "audit-bucket", raising=False)

    call_command(
        "audit_archive",
        retention_days=1,
        batch_size=1,
        no_delete=no_delete,
    )

    s3_client.put_object.assert_called_once()
    uploaded = s3_client.put_object.call_args.kwargs
    archived_row = json.loads(gzip.decompress(uploaded["Body"]).decode())
    assert archived_row["id"] == row.pk
    assert archived_row["context"] == "archive me"
    assert AuditLog.objects.filter(pk=row.pk).exists() is no_delete


def test_audit_admin_is_read_only(rf):
    model_admin = admin.site._registry[AuditLog]
    request = rf.get("/admin/shared/auditlog/")

    assert model_admin.has_add_permission(request) is False
    assert model_admin.has_change_permission(request) is False
    assert model_admin.has_delete_permission(request) is False


def test_audit_admin_rejects_real_add_change_and_delete_requests(client, django_user_model):
    superuser = django_user_model.objects.create_superuser(
        username="audit-admin",
        email="audit-admin@example.com",
        password="pw",
    )
    row = AuditLog.objects.create(
        entity_type=AuditEntityType.RANGE,
        entity_id=17,
        action=AuditAction.PROVISION,
        actor_type=AuditActorType.SYSTEM,
        context="immutable",
    )
    client.force_login(superuser)

    assert client.post(reverse("admin:shared_auditlog_add"), {}).status_code == 403
    change_response = client.post(
        reverse("admin:shared_auditlog_change", args=[row.pk]),
        {"context": "changed"},
    )
    assert change_response.status_code == 403
    assert client.post(reverse("admin:shared_auditlog_delete", args=[row.pk]), {"post": "yes"}).status_code == 403

    row.refresh_from_db()
    assert row.context == "immutable"
