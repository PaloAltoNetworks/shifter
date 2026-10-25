"""Upgrade the append profile without rewriting historical evidence."""

from importlib import import_module
from uuid import uuid4

import pytest
from django.db import connection
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from shared.audit import AuditEvent
from shared.audit.integrity import canonical_record_digest, verify_audit_chain
from shared.audit_adapter import append_audit_event
from shared.deployment import resolve_audit_deployment_scope
from shared.models import AuditChainHead, AuditLog

pytestmark = pytest.mark.django_db(transaction=True)
BEFORE = [("shared", "0028_personal_credential_guards")]
AFTER = [("shared", "0029_principal_audit_attribution")]


def test_upgrade_preserves_v1_digests_and_appends_attributed_v2_evidence():
    executor = MigrationExecutor(connection)
    executor.migrate(BEFORE)
    try:
        apps = executor.loader.project_state(BEFORE).apps
        legacy = apps.get_model("shared", "AuditLog")
        head_model = apps.get_model("shared", "AuditChainHead")
        deployment = resolve_audit_deployment_scope()
        head_model.objects.get_or_create(singleton=1, defaults={"deployment_scope": deployment})
        head_model.objects.filter(singleton=1).update(deployment_scope=deployment)
        recorded_at = timezone.now()
        record = {
            "event_id": uuid4(),
            "deployment_scope": deployment,
            "chain_generation": 1,
            "sequence": 1,
            "canonicalization_version": 1,
            "recorded_at": recorded_at,
            "previous_digest": "",
            "entity_type": "config",
            "entity_id": 1,
            "entity_ref": "",
            "action": "update",
            "actor_type": "user",
            "actor_id": 7,
            "previous_state": None,
            "new_state": None,
            "context": "historical",
            "source_ip": None,
            "user_agent": "",
            "request_id": "",
        }
        frozen = import_module("shared.migrations.0020_audit_integrity_chain")._canonical_record_digest(record)
        assert canonical_record_digest(record) == frozen
        values = {key: value for key, value in record.items() if key != "recorded_at"}
        old = legacy.objects.create(**values, timestamp=recorded_at, record_digest=frozen)
        head_model.objects.filter(singleton=1).update(last_sequence=1, last_digest=frozen)
        executor = MigrationExecutor(connection)
        executor.migrate(AFTER)
        upgraded = AuditLog.objects.get(pk=old.pk)
        assert upgraded.record_digest == frozen
        assert upgraded.canonicalization_version == 1
        assert upgraded.actor_principal_uuid is None
        new = append_audit_event(
            AuditEvent(
                entity_type="config", entity_id=1, action="update", actor_type="principal", actor_principal_uuid=uuid4()
            )
        )
        assert new.previous_digest == frozen
        assert new.canonicalization_version == 2
        assert verify_audit_chain().record_count == 2
        # A downgrade may not drop the column carrying committed identity.
        with pytest.raises(IrreversibleError):
            import_module("shared.migrations.0029_principal_audit_attribution").downgrade_empty_v2_profile(
                executor.loader.project_state(AFTER).apps, connection.schema_editor()
            )
        assert AuditChainHead.objects.get(singleton=1).canonicalization_version == 2
        assert AuditLog.objects.get(pk=old.pk).record_digest == frozen
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
