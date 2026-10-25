"""Make exact provider identity bindings append-only at the database boundary."""

from django.db import migrations


def install_guard(apps, schema_editor):  # noqa: ARG001 - Django migration signature
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(
            """
            CREATE FUNCTION management_reject_provider_binding_mutation()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION 'provider binding is immutable';
            END;
            $$
            """
        )
        schema_editor.execute(
            """
            CREATE TRIGGER management_provider_binding_immutable
            BEFORE UPDATE OR DELETE ON management_provider_binding
            FOR EACH ROW EXECUTE FUNCTION management_reject_provider_binding_mutation()
            """
        )
    elif schema_editor.connection.vendor == "sqlite":
        schema_editor.execute(
            """
            CREATE TRIGGER management_provider_binding_immutable_update
            BEFORE UPDATE ON management_provider_binding
            BEGIN SELECT RAISE(ABORT, 'provider binding is immutable'); END
            """
        )
        schema_editor.execute(
            """
            CREATE TRIGGER management_provider_binding_immutable_delete
            BEFORE DELETE ON management_provider_binding
            BEGIN SELECT RAISE(ABORT, 'provider binding is immutable'); END
            """
        )


def remove_guard(apps, schema_editor):  # noqa: ARG001 - Django migration signature
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("DROP TRIGGER IF EXISTS management_provider_binding_immutable ON management_provider_binding")
        schema_editor.execute("DROP FUNCTION IF EXISTS management_reject_provider_binding_mutation()")
    elif schema_editor.connection.vendor == "sqlite":
        schema_editor.execute("DROP TRIGGER IF EXISTS management_provider_binding_immutable_update")
        schema_editor.execute("DROP TRIGGER IF EXISTS management_provider_binding_immutable_delete")


class Migration(migrations.Migration):
    dependencies = [("management", "0015_map_human_principals")]

    operations = [migrations.RunPython(install_guard, remove_guard)]
