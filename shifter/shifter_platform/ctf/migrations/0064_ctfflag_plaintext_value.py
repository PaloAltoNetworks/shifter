"""Store static flags as normalized plaintext in ``CTFFlag.value`` (was ``flag_hash``).

Static flags were previously stored only as one-way hashes, so they cannot be
converted to plaintext. No live events exist when this ships: the hashed static
rows are removed rather than kept as values no submission could ever match.
Affected challenges report "no flag records" until their flags are re-entered or
the event's challenges are re-imported. Regex patterns and programmable/http
sentinels were already stored in the clear and carry over unchanged.
"""

from django.db import migrations, models
from django.db.models import Q

_ONE_WAY_HASH_PREFIXES = ("$2", "pbkdf2:", "sha256:")


def _remove_unrecoverable_static_hashes(apps, schema_editor):
    """Delete static flag rows that only hold a one-way hash."""
    ctf_flag = apps.get_model("ctf", "CTFFlag")
    hashed = Q()
    for prefix in _ONE_WAY_HASH_PREFIXES:
        hashed |= Q(value__startswith=prefix)
    ctf_flag.objects.filter(Q(flag_type="static") & hashed).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("ctf", "0063_ctfparticipant_principal_uuid"),
    ]

    operations = [
        migrations.RenameField(
            model_name="ctfflag",
            old_name="flag_hash",
            new_name="value",
        ),
        migrations.AlterField(
            model_name="ctfflag",
            name="value",
            field=models.CharField(
                help_text="Plaintext static flag (normalized), regex pattern, or programmable/http sentinel",
                max_length=255,
            ),
        ),
        migrations.RunPython(_remove_unrecoverable_static_hashes, migrations.RunPython.noop),
    ]
