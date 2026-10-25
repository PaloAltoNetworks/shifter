"""Service admission is append-only except for irreversible disabling."""

from django.db import migrations


def install_guard(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    comparison = "IS DISTINCT FROM" if vendor == "postgresql" else "IS NOT"
    fields = ("binding_id", "audience", "scopes", "uuid")
    changed = [f"NEW.{field} {comparison} OLD.{field}" for field in fields]
    changed.append("(NOT OLD.is_active AND NEW.is_active)")
    condition = " OR ".join(changed)
    if vendor == "postgresql":
        schema_editor.execute(f"""CREATE FUNCTION management_guard_service_admission()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF {condition} THEN RAISE EXCEPTION 'service admission is immutable'; END IF;
            RETURN NEW; END; $$""")
        schema_editor.execute("""CREATE TRIGGER management_service_admission_immutable
            BEFORE UPDATE ON management_service_credential_admission
            FOR EACH ROW EXECUTE FUNCTION management_guard_service_admission()""")
    elif vendor == "sqlite":
        schema_editor.execute(f"""CREATE TRIGGER management_service_admission_immutable
            BEFORE UPDATE ON management_service_credential_admission WHEN {condition}
            BEGIN SELECT RAISE(ABORT, 'service admission is immutable'); END""")


def remove_guard(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(
            "DROP TRIGGER IF EXISTS management_service_admission_immutable ON management_service_credential_admission"
        )
        schema_editor.execute("DROP FUNCTION IF EXISTS management_guard_service_admission()")
    elif schema_editor.connection.vendor == "sqlite":
        schema_editor.execute("DROP TRIGGER IF EXISTS management_service_admission_immutable")


class Migration(migrations.Migration):
    dependencies = [("management", "0017_service_credential_admission")]
    operations = [migrations.RunPython(install_guard, remove_guard)]
