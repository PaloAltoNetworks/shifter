"""Participant lifecycle cleanup (issue #535 / CTF-006).

Organizer creation is immediate seat provisioning, not invitation acceptance:

* ``invited_at`` -> ``login_info_sent_at`` -- the timestamp is stamped only when
  non-secret login information is delivered, so its honest name reflects that.
* The ``invited`` participant status is removed. No production path leaves a
  participant unregistered (creation provisions an isolated account in the same
  transaction), so the reconcile below acts on an expected-empty set; it exists
  only to move any legacy ``invited`` row to ``registered`` before the state is
  dropped from the field's choices.
"""

from django.db import migrations, models
from django.utils import timezone


def reconcile_invited_to_registered(apps, schema_editor):
    """Move any residual ``invited`` participant to ``registered`` (should be none)."""
    participant_model = apps.get_model("ctf", "CTFParticipant")
    for participant in participant_model.objects.filter(status="invited"):
        participant.status = "registered"
        if participant.registered_at is None:
            participant.registered_at = timezone.now()
        participant.save(update_fields=["status", "registered_at"])


class Migration(migrations.Migration):
    dependencies = [
        ("ctf", "0047_drop_challenge_flag_hash"),
    ]

    operations = [
        migrations.RenameField(
            model_name="ctfparticipant",
            old_name="invited_at",
            new_name="login_info_sent_at",
        ),
        migrations.AlterField(
            model_name="ctfparticipant",
            name="login_info_sent_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When login information was last delivered",
                null=True,
            ),
        ),
        migrations.RunPython(reconcile_invited_to_registered, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="ctfparticipant",
            name="status",
            field=models.CharField(
                choices=[
                    ("registered", "Registered"),
                    ("active", "Active"),
                    ("completed", "Completed"),
                    ("disqualified", "Disqualified"),
                    ("banned", "Banned"),
                ],
                db_index=True,
                default="registered",
                help_text="Current participant lifecycle status",
                max_length=20,
            ),
        ),
    ]
