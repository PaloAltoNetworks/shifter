"""Add the versioned audit hash chain and PostgreSQL mutation guards (#327)."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC

from django.db import migrations, models
from django.utils import timezone

CANONICALIZATION_VERSION = 1
CHAIN_GENERATION = 1


def _canonical_record_digest(record) -> str:
    """Frozen canonicalization-v1 profile for upgrade reproducibility."""
    payload = {
        "action": record["action"],
        "actor_id": record["actor_id"],
        "actor_type": record["actor_type"],
        "canonicalization_version": record["canonicalization_version"],
        "chain_generation": record["chain_generation"],
        "context": record["context"],
        "deployment_scope": record["deployment_scope"],
        "entity_id": record["entity_id"],
        "entity_ref": record["entity_ref"],
        "entity_type": record["entity_type"],
        "event_id": str(record["event_id"]),
        "new_state": record["new_state"],
        "previous_digest": record["previous_digest"],
        "previous_state": record["previous_state"],
        "recorded_at": record["recorded_at"].astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z"),
        "request_id": record["request_id"],
        "sequence": record["sequence"],
        "source_ip": str(record["source_ip"]) if record["source_ip"] is not None else None,
        "user_agent": record["user_agent"],
    }
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _backfill_integrity_chain(apps, schema_editor) -> None:
    from shared.deployment import resolve_audit_deployment_scope

    audit_log = apps.get_model("shared", "AuditLog")
    chain_head = apps.get_model("shared", "AuditChainHead")
    deployment_scope = resolve_audit_deployment_scope()
    previous_digest = ""
    last_sequence = 0

    for sequence, row in enumerate(audit_log.objects.order_by("timestamp", "id").iterator(), start=1):
        event_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"shifter:audit:v1:{deployment_scope}:{row.pk}",
        )
        record = {
            "event_id": event_id,
            "deployment_scope": deployment_scope,
            "chain_generation": CHAIN_GENERATION,
            "sequence": sequence,
            "canonicalization_version": CANONICALIZATION_VERSION,
            "recorded_at": row.timestamp,
            "previous_digest": previous_digest,
            "entity_type": row.entity_type,
            "entity_id": row.entity_id,
            "entity_ref": "",
            "action": row.action,
            "actor_type": row.actor_type,
            "actor_id": row.actor_id,
            "previous_state": row.previous_state,
            "new_state": row.new_state,
            "context": row.context,
            "source_ip": row.source_ip,
            "user_agent": row.user_agent,
            "request_id": row.request_id,
        }
        record_digest = _canonical_record_digest(record)
        audit_log.objects.filter(pk=row.pk).update(
            event_id=event_id,
            deployment_scope=deployment_scope,
            chain_generation=CHAIN_GENERATION,
            sequence=sequence,
            canonicalization_version=CANONICALIZATION_VERSION,
            previous_digest=previous_digest,
            record_digest=record_digest,
            entity_ref="",
        )
        previous_digest = record_digest
        last_sequence = sequence

    chain_head.objects.update_or_create(
        singleton=1,
        defaults={
            "deployment_scope": deployment_scope,
            "chain_generation": CHAIN_GENERATION,
            "canonicalization_version": CANONICALIZATION_VERSION,
            "last_sequence": last_sequence,
            "last_digest": previous_digest,
        },
    )


def _clear_integrity_chain(apps, schema_editor) -> None:
    apps.get_model("shared", "AuditChainHead").objects.all().delete()


_INSTALL_POSTGRES_GUARDS = r"""
CREATE OR REPLACE FUNCTION public.shared_reject_audit_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    RAISE EXCEPTION 'committed audit evidence is append-only';
END;
$function$;

DROP TRIGGER IF EXISTS shared_auditlog_append_only ON public.shared_auditlog;
CREATE TRIGGER shared_auditlog_append_only
BEFORE UPDATE OR DELETE ON public.shared_auditlog
FOR EACH ROW EXECUTE FUNCTION public.shared_reject_audit_mutation();

CREATE OR REPLACE FUNCTION public.shared_validate_audit_chain_head()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    IF OLD.last_sequence = 0
       AND OLD.last_digest = ''
       AND NEW.last_sequence = 0
       AND NEW.last_digest = ''
       AND NEW.singleton IS NOT DISTINCT FROM OLD.singleton
       AND NEW.chain_generation IS NOT DISTINCT FROM OLD.chain_generation
       AND NEW.canonicalization_version IS NOT DISTINCT FROM OLD.canonicalization_version THEN
        RETURN NEW;
    END IF;

    IF NEW.singleton IS DISTINCT FROM OLD.singleton
       OR NEW.deployment_scope IS DISTINCT FROM OLD.deployment_scope
       OR NEW.chain_generation IS DISTINCT FROM OLD.chain_generation
       OR NEW.canonicalization_version IS DISTINCT FROM OLD.canonicalization_version THEN
        RAISE EXCEPTION 'audit chain identity is immutable';
    END IF;

    IF NEW.last_sequence <> OLD.last_sequence + 1 THEN
        RAISE EXCEPTION 'audit chain head must advance by exactly one sequence';
    END IF;

    IF NEW.last_digest !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'audit chain head digest is invalid';
    END IF;

    PERFORM 1
      FROM public.shared_auditlog
     WHERE deployment_scope = NEW.deployment_scope
       AND chain_generation = NEW.chain_generation
       AND canonicalization_version = NEW.canonicalization_version
       AND sequence = NEW.last_sequence
       AND previous_digest = OLD.last_digest
       AND record_digest = NEW.last_digest;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'audit chain head has no matching appended record';
    END IF;
    RETURN NEW;
END;
$function$;

DROP TRIGGER IF EXISTS shared_audit_chain_head_guard ON public.shared_audit_chain_head;
CREATE TRIGGER shared_audit_chain_head_guard
BEFORE UPDATE ON public.shared_audit_chain_head
FOR EACH ROW EXECUTE FUNCTION public.shared_validate_audit_chain_head();

DO $block$
DECLARE
    audit_sequence regclass;
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'portal_runtime') THEN
        REVOKE UPDATE, DELETE, TRUNCATE ON TABLE public.shared_auditlog FROM portal_runtime;
        GRANT SELECT, INSERT ON TABLE public.shared_auditlog TO portal_runtime;
        audit_sequence := pg_get_serial_sequence('public.shared_auditlog', 'id')::regclass;
        IF audit_sequence IS NULL THEN
            RAISE EXCEPTION 'shared_auditlog.id has no owned sequence';
        END IF;
        EXECUTE format(
            'GRANT USAGE, SELECT, UPDATE ON SEQUENCE %%s TO portal_runtime',
            audit_sequence
        );

        REVOKE INSERT, DELETE, TRUNCATE ON TABLE public.shared_audit_chain_head FROM portal_runtime;
        GRANT SELECT, UPDATE ON TABLE public.shared_audit_chain_head TO portal_runtime;
    END IF;
END;
$block$;
"""


_REMOVE_POSTGRES_GUARDS = r"""
DROP TRIGGER IF EXISTS shared_audit_chain_head_guard ON public.shared_audit_chain_head;
DROP FUNCTION IF EXISTS public.shared_validate_audit_chain_head();
DROP TRIGGER IF EXISTS shared_auditlog_append_only ON public.shared_auditlog;
DROP FUNCTION IF EXISTS public.shared_reject_audit_mutation();

DO $block$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'portal_runtime') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.shared_auditlog TO portal_runtime;
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.shared_audit_chain_head TO portal_runtime;
    END IF;
END;
$block$;
"""


def _install_postgres_guards(apps, schema_editor) -> None:
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(_INSTALL_POSTGRES_GUARDS)


def _remove_postgres_guards(apps, schema_editor) -> None:
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(_REMOVE_POSTGRES_GUARDS)


class Migration(migrations.Migration):
    dependencies = [
        ("mission_control", "0041_create_portal_runtime_user"),
        ("shared", "0019_alter_auditlog_entity_type"),
    ]

    operations = [
        migrations.CreateModel(
            name="AuditChainHead",
            fields=[
                (
                    "singleton",
                    models.PositiveSmallIntegerField(default=1, editable=False, primary_key=True, serialize=False),
                ),
                ("deployment_scope", models.CharField(max_length=255)),
                ("chain_generation", models.PositiveIntegerField(default=1)),
                ("canonicalization_version", models.PositiveSmallIntegerField(default=1)),
                ("last_sequence", models.PositiveBigIntegerField(default=0)),
                ("last_digest", models.CharField(blank=True, max_length=64)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Audit Chain Head",
                "db_table": "shared_audit_chain_head",
            },
        ),
        migrations.AddField(
            model_name="auditlog",
            name="canonicalization_version",
            field=models.PositiveSmallIntegerField(null=True),
        ),
        migrations.AddField(
            model_name="auditlog",
            name="chain_generation",
            field=models.PositiveIntegerField(null=True),
        ),
        migrations.AddField(
            model_name="auditlog",
            name="deployment_scope",
            field=models.CharField(max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="auditlog",
            name="entity_ref",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="auditlog",
            name="event_id",
            field=models.UUIDField(null=True, unique=True),
        ),
        migrations.AddField(
            model_name="auditlog",
            name="previous_digest",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="auditlog",
            name="record_digest",
            field=models.CharField(max_length=64, null=True, unique=True),
        ),
        migrations.AddField(
            model_name="auditlog",
            name="sequence",
            field=models.PositiveBigIntegerField(null=True, unique=True),
        ),
        migrations.AlterField(
            model_name="auditlog",
            name="timestamp",
            field=models.DateTimeField(default=timezone.now, editable=False),
        ),
        migrations.RunPython(_backfill_integrity_chain, _clear_integrity_chain),
        migrations.AlterField(
            model_name="auditlog",
            name="entity_ref",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AlterField(
            model_name="auditlog",
            name="previous_digest",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AlterField(
            model_name="auditlog",
            name="canonicalization_version",
            field=models.PositiveSmallIntegerField(default=1),
        ),
        migrations.AlterField(
            model_name="auditlog",
            name="chain_generation",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AlterField(
            model_name="auditlog",
            name="deployment_scope",
            field=models.CharField(max_length=255),
        ),
        migrations.AlterField(
            model_name="auditlog",
            name="event_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
        migrations.AlterField(
            model_name="auditlog",
            name="record_digest",
            field=models.CharField(max_length=64, unique=True),
        ),
        migrations.AlterField(
            model_name="auditlog",
            name="sequence",
            field=models.PositiveBigIntegerField(unique=True),
        ),
        migrations.AddIndex(
            model_name="auditlog",
            index=models.Index(
                fields=["deployment_scope", "chain_generation", "sequence"],
                name="shared_audit_chain_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="auditlog",
            index=models.Index(fields=["entity_type", "entity_ref"], name="shared_audit_entity_ref_idx"),
        ),
        migrations.AddConstraint(
            model_name="auditchainhead",
            constraint=models.CheckConstraint(
                condition=models.Q(("singleton", 1)),
                name="shared_audit_head_singleton_one",
            ),
        ),
        migrations.RunPython(_install_postgres_guards, _remove_postgres_guards),
    ]
