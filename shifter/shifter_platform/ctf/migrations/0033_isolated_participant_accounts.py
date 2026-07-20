"""Replace participant magic links with isolated account relationships."""

from django.db import migrations, models
from django.db.models import Q


def prepare_legacy_participants(apps, schema_editor):
    """Refuse unsafe live-event relabeling; detach terminal legacy identities."""
    Participant = apps.get_model("ctf", "CTFParticipant")
    live = Participant.objects.filter(user__isnull=False).exclude(
        event__status__in=["ended", "cancelled", "archived"]
    )
    if live.exists():
        raise RuntimeError(
            "Issue #1206 requires an explicit operational migration for linked participants "
            "in non-terminal CTF events; end/cancel those events before deploying."
        )
    Participant.objects.filter(
        user__isnull=False,
        event__status__in=["ended", "cancelled", "archived"],
    ).update(user=None)


class Migration(migrations.Migration):
    dependencies = [
        ("ctf", "0032_ctfevent_spare_range_count_ctfsparerange"),
        ("management", "0010_userprofile_ctf_account_fields"),
    ]

    operations = [
        migrations.RunPython(prepare_legacy_participants, migrations.RunPython.noop),
        migrations.AddField(
            model_name="ctfevent",
            name="participant_password_override",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Optional event-wide bootstrap password for temporary participant accounts",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="ctfparticipant",
            name="unique_active_participant_email_per_event",
        ),
        migrations.RemoveField(model_name="ctfparticipant", name="invite_token"),
        migrations.RemoveField(model_name="ctfparticipant", name="invite_token_expires"),
        migrations.AlterField(
            model_name="ctfparticipant",
            name="email",
            field=models.EmailField(
                blank=True,
                db_index=True,
                default="",
                help_text="Optional credential-delivery email; never an identity key",
                max_length=254,
            ),
        ),
        migrations.AddConstraint(
            model_name="ctfparticipant",
            constraint=models.UniqueConstraint(
                condition=Q(deleted_at__isnull=True, user__isnull=False),
                fields=("user",),
                name="unique_active_ctf_participant_user",
            ),
        ),
    ]
