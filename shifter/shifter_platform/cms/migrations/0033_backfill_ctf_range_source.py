"""Backfill range_source='ctf' for provably CTF-created ranges (#450).

0031 added ``RangeInstance.range_source`` defaulting every existing row to
``mission_control``. Ranges that were created through the CTF path are provable
via ``CTFParticipant.range_instance_id`` (a CMS ``RangeInstance.pk``). Leaving
those rows as ``mission_control`` would occupy the user's Mission Control
admission slot while leaving their CTF slot empty after deploy, defeating the
per-(user_id, range_source) admission this change introduces. This data
migration marks those provable CTF rows ``ctf``; rows with no CTF linkage keep
the ``mission_control`` default.
"""

from django.db import migrations


def backfill_ctf_range_source(apps, schema_editor):
    RangeInstance = apps.get_model("cms", "RangeInstance")
    CTFParticipant = apps.get_model("ctf", "CTFParticipant")

    ctf_range_instance_pks = list(
        CTFParticipant.objects.exclude(range_instance_id__isnull=True).values_list("range_instance_id", flat=True)
    )
    if not ctf_range_instance_pks:
        return

    RangeInstance.objects.filter(pk__in=ctf_range_instance_pks).update(range_source="ctf")


class Migration(migrations.Migration):
    dependencies = [
        ("cms", "0032_rangeinstance_range_source"),
        ("ctf", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(backfill_ctf_range_source, migrations.RunPython.noop),
    ]
