from datetime import timedelta

from django.db import migrations, models
from django.utils import timezone


def backfill_active_range_leases(apps, schema_editor):
    RangeInstance = apps.get_model("cms", "RangeInstance")
    CTFParticipant = apps.get_model("ctf", "CTFParticipant")
    CTFSpareRange = apps.get_model("ctf", "CTFSpareRange")
    now = timezone.now()
    RangeInstance.objects.filter(
        range_source="mission_control",
        deleted_at__isnull=True,
        expires_at__isnull=True,
    ).exclude(status__in=("destroying", "destroyed", "failed")).update(
        expires_at=now + timedelta(days=30),
        maximum_expires_at=now + timedelta(days=365),
    )

    participant_ranges = CTFParticipant.objects.exclude(range_instance_id__isnull=True).select_related("event")
    for participant in participant_ranges.iterator():
        deadline = participant.event.event_end + timedelta(hours=participant.event.cleanup_delay_hours)
        RangeInstance.objects.filter(
            pk=participant.range_instance_id,
            range_source="ctf",
            expires_at__isnull=True,
        ).update(expires_at=deadline, maximum_expires_at=deadline)

    spare_ranges = CTFSpareRange.objects.exclude(range_instance_id__isnull=True).select_related("event")
    for spare in spare_ranges.iterator():
        deadline = spare.event.event_end + timedelta(hours=spare.event.cleanup_delay_hours)
        RangeInstance.objects.filter(
            pk=spare.range_instance_id,
            range_source="ctf",
            expires_at__isnull=True,
        ).update(expires_at=deadline, maximum_expires_at=deadline)


class Migration(migrations.Migration):
    dependencies = [
        ("cms", "0036_add_active_range_unique_constraint"),
        ("ctf", "0032_ctfevent_spare_range_count_ctfsparerange"),
    ]

    operations = [
        migrations.AddField(
            model_name="rangeinstance",
            name="expires_at",
            field=models.DateTimeField(
                blank=True,
                db_index=True,
                help_text="Server-enforced deadline after which the range is automatically destroyed.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="rangeinstance",
            name="maximum_expires_at",
            field=models.DateTimeField(
                blank=True,
                help_text="Immutable generation lifetime ceiling; VPN credentials cannot outlive it.",
                null=True,
            ),
        ),
        migrations.RunPython(backfill_active_range_leases, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="rangeinstance",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(expires_at__isnull=True, maximum_expires_at__isnull=True)
                    | models.Q(
                        expires_at__isnull=False,
                        maximum_expires_at__isnull=False,
                        expires_at__lte=models.F("maximum_expires_at"),
                    )
                ),
                name="ck_rangeinstance_lease_bounds",
            ),
        ),
    ]
