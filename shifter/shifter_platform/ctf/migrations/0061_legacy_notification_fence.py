"""Irreversible PostgreSQL fence retained across forward-only cutover recovery."""

from django.db import migrations
from django.db.migrations.exceptions import IrreversibleError


def install_fence(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("""
        CREATE FUNCTION ctf_reject_retired_notification_write() RETURNS trigger AS $$
        BEGIN
          IF EXISTS (SELECT 1 FROM ctf_communication_cutover WHERE id = 1) THEN
            IF TG_TABLE_NAME = 'ctf_notification' THEN
              IF TG_OP = 'INSERT' OR NEW.status IN ('draft', 'scheduled', 'sending', 'sent') THEN
                RAISE EXCEPTION 'legacy_notification_writer_retired' USING ERRCODE = '23514';
              END IF;
            ELSIF NEW.task_type = 'send_notification' AND NEW.status IN ('pending', 'running') THEN
              RAISE EXCEPTION 'legacy_notification_task_retired' USING ERRCODE = '23514';
            ELSIF NEW.status = 'running'
              AND (TG_OP = 'INSERT' OR OLD.status IS DISTINCT FROM 'running'
                   OR NEW.claim_token IS DISTINCT FROM OLD.claim_token) AND (
              current_setting('shifter.communication_writer', true) IS DISTINCT FROM 'ledger_v1'
              OR NOT EXISTS (SELECT 1 FROM ctf_communication_cutover WHERE id = 1 AND activated_at IS NOT NULL)
            ) THEN
              RAISE EXCEPTION 'legacy_scheduler_claim_retired' USING ERRCODE = '23514';
            END IF;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER ctf_notification_writer_fence BEFORE INSERT OR UPDATE ON ctf_notification
          FOR EACH ROW EXECUTE FUNCTION ctf_reject_retired_notification_write();
        CREATE TRIGGER ctf_notification_task_fence BEFORE INSERT OR UPDATE ON ctf_scheduled_task
          FOR EACH ROW EXECUTE FUNCTION ctf_reject_retired_notification_write();
    """)


def remove_unused_fence(apps, schema_editor):
    if apps.get_model("ctf", "CommunicationCutover").objects.exists():
        raise IrreversibleError("An initiated communication cutover requires forward recovery")
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("""
            DROP TRIGGER ctf_notification_writer_fence ON ctf_notification;
            DROP TRIGGER ctf_notification_task_fence ON ctf_scheduled_task;
            DROP FUNCTION ctf_reject_retired_notification_write();
        """)


class Migration(migrations.Migration):
    dependencies = [("ctf", "0060_communication_cutover")]
    operations = [migrations.RunPython(install_fence, remove_unused_fence)]
