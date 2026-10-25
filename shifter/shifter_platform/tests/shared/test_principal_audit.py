"""Canonical principal identity survives storage, queries, export and integrity checks."""

import gzip
import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from rest_framework.test import APIClient

from shared.audit import AuditEvent, AuditTarget, audit_log_from_request
from shared.audit.integrity import AuditIntegrityError, digest_for_row, verify_audit_chain
from shared.audit_adapter import append_audit_event
from shared.authorization import CredentialCeiling
from shared.credentials import CredentialContext
from shared.identity_scope import PrincipalRef
from shared.management.commands.audit_archive import Command
from shared.models import AuditLog

pytestmark = pytest.mark.django_db


def _event(**overrides):
    return AuditEvent(entity_type="principal", entity_id=0, entity_ref=str(uuid4()), action="update", **overrides)


@pytest.mark.parametrize(
    "actor_type,actor_id,principal_uuid",
    [
        ("principal", None, None),
        ("principal", 7, uuid4()),
        ("principal", None, UUID(int=0)),
        ("principal", None, "not-a-uuid"),
        ("system", None, uuid4()),
    ],
)
def test_audit_writer_rejects_ambiguous_principal_actor(actor_type, actor_id, principal_uuid):
    with pytest.raises(ValueError):
        append_audit_event(_event(actor_type=actor_type, actor_id=actor_id, actor_principal_uuid=principal_uuid))
    assert AuditLog.objects.count() == 0


def test_principal_identity_is_hashed_exported_and_queryable(django_user_model):
    principal_uuid = uuid4()
    row = append_audit_event(_event(actor_type="principal", actor_principal_uuid=principal_uuid))
    append_audit_event(_event(actor_type="principal", actor_principal_uuid=uuid4()))
    assert row.canonicalization_version == 2
    original_digest = digest_for_row(row)
    row.actor_principal_uuid = uuid4()
    assert digest_for_row(row) != original_digest
    row.refresh_from_db()
    exported = json.loads(gzip.decompress(Command._serialize_batch([row])))
    assert exported["actor_principal_uuid"] == str(principal_uuid)
    assert exported["record_digest"] == original_digest
    staff = django_user_model.objects.create_user(username="principal-audit-reader", is_staff=True)
    client = APIClient()
    client.force_login(staff, backend="config.auth.PlatformModelBackend")
    response = client.get("/api/v1/audit/", {"actor_principal_uuid": str(principal_uuid)})
    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert response.json()["results"][0]["actor_principal_uuid"] == str(principal_uuid)
    verify_audit_chain()


def test_shared_request_writer_uses_authenticated_service_not_body_attribution():
    credential = CredentialContext(
        PrincipalRef(uuid4(), "service"), "service", uuid4(), CredentialCeiling(frozenset()), frozenset()
    )
    request = SimpleNamespace(user=None, auth=credential, META={}, data={"actor_principal_uuid": str(uuid4())})
    assert audit_log_from_request(request, AuditTarget("config", 1), "update")
    row = AuditLog.objects.get()
    assert row.actor_type == "principal"
    assert row.actor_id is None
    assert row.actor_principal_uuid == credential.principal.uuid


def test_verifier_rejects_principal_identity_tampering():
    from tests.shared.test_audit_integrity import _privileged_tamper_access

    row = append_audit_event(_event(actor_type="principal", actor_principal_uuid=uuid4()))
    with _privileged_tamper_access():
        AuditLog.objects.filter(pk=row.pk).update(actor_principal_uuid=uuid4())
    with pytest.raises(AuditIntegrityError, match="digest mismatch"):
        verify_audit_chain()
