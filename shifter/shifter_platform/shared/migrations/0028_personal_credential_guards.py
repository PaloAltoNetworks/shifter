"""Enforce immutable credential limits against bulk and non-ORM updates."""

from django.db import migrations


def install_guard(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    comparison = "IS DISTINCT FROM" if vendor == "postgresql" else "IS NOT"
    fields = ("scopes", "expires_at", "principal_uuid", "credential_uuid", "token_id", "target_type", "target_uuid")
    changed = [f"NEW.{field} {comparison} OLD.{field}" for field in fields]
    changed += [
        f"(NEW.created_by_id IS NOT NULL AND NEW.created_by_id {comparison} OLD.created_by_id)",
        f"(NEW.knox_token_id IS NOT NULL AND NEW.knox_token_id {comparison} OLD.knox_token_id)",
        f"(OLD.revoked_at IS NOT NULL AND NEW.revoked_at {comparison} OLD.revoked_at)",
    ]
    condition = " OR ".join(changed)
    if vendor == "postgresql":
        schema_editor.execute(f"""CREATE FUNCTION shared_guard_personal_credential()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF {condition} THEN RAISE EXCEPTION 'personal credential is immutable'; END IF;
            RETURN NEW; END; $$""")
        schema_editor.execute("""CREATE TRIGGER shared_personal_credential_immutable BEFORE UPDATE ON shared_api_token
            FOR EACH ROW EXECUTE FUNCTION shared_guard_personal_credential()""")
    elif vendor == "sqlite":
        schema_editor.execute(f"""CREATE TRIGGER shared_personal_credential_immutable BEFORE UPDATE ON shared_api_token
            WHEN {condition} BEGIN SELECT RAISE(ABORT, 'personal credential is immutable'); END""")


def remove_guard(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("DROP TRIGGER IF EXISTS shared_personal_credential_immutable ON shared_api_token")
        schema_editor.execute("DROP FUNCTION IF EXISTS shared_guard_personal_credential()")
    elif schema_editor.connection.vendor == "sqlite":
        schema_editor.execute("DROP TRIGGER IF EXISTS shared_personal_credential_immutable")


class Migration(migrations.Migration):
    dependencies = [("shared", "0027_personal_credential_metadata")]
    operations = [migrations.RunPython(install_guard, remove_guard)]
