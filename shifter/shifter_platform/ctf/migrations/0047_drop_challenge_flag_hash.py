"""Drop the legacy ``CTFChallenge.flag_hash`` column; ``CTFFlag`` becomes the
sole source of flag truth (#532).

Single-release full removal (per the issue decision): backfill a static
``CTFFlag`` for any challenge that still relies only on the legacy
challenge-level hash, then remove the column.
"""

from __future__ import annotations

from django.db import migrations

# Stored-hash families ``verify_flag`` can check. A legacy value outside these
# (blank, or a ``multi-flag`` / ``programmable`` / ``http`` sentinel) is not
# verifiable material and cannot be backfilled.
_SUPPORTED_HASH_PREFIXES = ("$2", "pbkdf2:", "sha256:")


def _backfill_ctfflags(apps, schema_editor):
    """Create one static ``CTFFlag`` for every challenge (including recoverable
    soft-deleted ones) that has no active flag rows but carries a supported
    legacy hash. The stored digest is copied verbatim -- never rehashed.
    Existing active ``CTFFlag`` rows always win and are never duplicated.

    An *active* challenge with no flag rows and no usable legacy hash is invalid
    input: fail the deploy with bounded identifiers (never flag material) so the
    misconfiguration is fixed rather than shipped as an unverifiable challenge.
    Rerunning is safe -- backfilled rows make the challenge skip on a second pass.
    """
    Challenge = apps.get_model("ctf", "CTFChallenge")
    Flag = apps.get_model("ctf", "CTFFlag")

    invalid_active_ids: list[str] = []
    for challenge in Challenge.objects.all().iterator():
        if Flag.objects.filter(challenge=challenge, deleted_at__isnull=True).exists():
            continue
        legacy = challenge.flag_hash or ""
        if legacy.startswith(_SUPPORTED_HASH_PREFIXES):
            Flag.objects.create(
                challenge=challenge,
                flag_hash=legacy,
                flag_type="static",
                case_sensitive=True,
                order=0,
            )
        elif challenge.deleted_at is None:
            invalid_active_ids.append(str(challenge.pk))

    if invalid_active_ids:
        raise RuntimeError(
            "Cannot drop CTFChallenge.flag_hash: "
            f"{len(invalid_active_ids)} active challenge(s) have no flag records and no "
            "usable legacy hash. Add at least one flag to each before migrating. "
            f"Challenge ids: {', '.join(sorted(invalid_active_ids))}"
        )


class Migration(migrations.Migration):
    dependencies = [
        ("ctf", "0046_content_hydration_receipt"),
    ]

    operations = [
        migrations.RunPython(_backfill_ctfflags, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="ctfchallenge",
            name="flag_hash",
        ),
    ]
