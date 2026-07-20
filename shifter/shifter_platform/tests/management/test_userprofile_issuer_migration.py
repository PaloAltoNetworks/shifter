"""Tests for the #1521 ``UserProfile.issuer`` migration.

The migration is a purely additive schema change (a non-null ``AddField``
with an empty-string default plus a widening ``AlterField``, no ``RunPython``
data function), so unlike the ``importlib``-driven data-migration test in
``test_revoke_organizers_migration.py`` there is no forward function to
execute -- existing rows backfill to ``issuer=""`` via the column default,
not a data operation. This module still follows the same ``importlib``-driven
pattern (import the migration module directly) to prove the migration
declares exactly that additive, non-destructive shape: ``issuer`` is
non-null/blank with an empty-string default, and ``cognito_sub`` only widens
(never narrows, never drops its uniqueness constraint).

The behavioral half of "historical unbound + subject-only states" --
proving a legacy subject-only row acquires the verified issuer, and a fully
unbound row binds once -- is covered against the current model shape those
historical rows migrate into by
``tests.management.test_services.TestBindProviderIdentity``.
"""

from __future__ import annotations

import importlib

from django.db import migrations, models

_MIGRATION = importlib.import_module("management.migrations.0009_userprofile_issuer")


def test_migration_depends_on_previous_management_migration():
    assert ("management", "0008_revoke_self_service_organizers") in _MIGRATION.Migration.dependencies


def test_migration_adds_blank_issuer_field_defaulting_to_empty():
    add_issuer = next(
        op for op in _MIGRATION.Migration.operations if isinstance(op, migrations.AddField) and op.name == "issuer"
    )
    assert add_issuer.model_name == "userprofile"
    assert isinstance(add_issuer.field, models.CharField)
    # Non-null with an empty-string default (Django-idiomatic for an optional
    # string field): existing rows (legacy subject-only or fully unbound)
    # backfill to issuer="" -- never NULL -- matching the non-null model field.
    assert add_issuer.field.null is False
    assert add_issuer.field.blank is True
    assert add_issuer.field.has_default()
    assert add_issuer.field.get_default() == ""


def test_migration_widens_cognito_sub_without_narrowing_or_dropping_uniqueness():
    alter_sub = next(
        op
        for op in _MIGRATION.Migration.operations
        if isinstance(op, migrations.AlterField) and op.name == "cognito_sub"
    )
    assert alter_sub.model_name == "userprofile"
    assert alter_sub.field.max_length == 255
    assert alter_sub.field.max_length >= 36, "widening only -- must never narrow the historical 36-char shape"
    assert alter_sub.field.unique is True
    assert alter_sub.field.null is True
    assert alter_sub.field.blank is True


def test_migration_has_no_runpython_data_operations():
    """Purely additive: nothing here rewrites or backfills existing row data."""
    assert not any(isinstance(op, migrations.RunPython) for op in _MIGRATION.Migration.operations)
