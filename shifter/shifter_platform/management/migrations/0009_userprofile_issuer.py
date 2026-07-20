"""Add UserProfile.issuer and widen cognito_sub (issue #1521).

REV1 identity hardening: bootstrap-admin binding is keyed on the
``(issuer, subject)`` pair from strict provider verification, never on
email alone. ``issuer`` is a new nullable, opaque, case-sensitive column
paired with the existing ``cognito_sub`` column (kept under its legacy name
for physical-schema and ``mcp_user`` compatibility; it now stores the
provider subject for both Cognito/OIDC and GCP Identity Platform).

This is additive only:

- ``issuer`` is nullable/blank with no default backfill, so every existing
  row (whether it already has a bound ``cognito_sub`` -- a "legacy
  subject-only" row -- or has none at all -- a "fully unbound" row) is
  untouched and simply reads back with ``issuer=None``.
  ``management.services.bind_provider_identity`` is the only place that
  later acquires the verified issuer for a legacy row, on a login that
  presents the matching subject; nothing here rewrites data.
- ``cognito_sub`` widens from 36 to 255 characters (a non-Cognito provider
  subject need not be a UUID) and keeps its existing ``unique=True``
  constraint, so uniqueness enforcement is unchanged.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("management", "0008_revoke_self_service_organizers"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="issuer",
            field=models.CharField(
                blank=True,
                default="",
                help_text=(
                    "Provider issuer (opaque, case-sensitive; issue #1521) paired with "
                    "cognito_sub as the bound (issuer, subject) identity key. Empty for a "
                    "legacy row bound before this field existed; acquired once, on the "
                    "next login presenting the same subject "
                    "(see management.services.bind_provider_identity)."
                ),
                max_length=255,
            ),
        ),
        migrations.AlterField(
            model_name="userprofile",
            name="cognito_sub",
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text=(
                    "Provider subject identifier (opaque, case-sensitive; issue #1521). "
                    "Historically a Cognito user pool UUID; also used for the GCP "
                    "Identity Platform Firebase UID and other provider subjects. "
                    "Paired with `issuer` for the bound (issuer, subject) identity key."
                ),
                max_length=255,
                null=True,
                unique=True,
            ),
        ),
    ]
