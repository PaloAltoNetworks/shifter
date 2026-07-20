"""Replace the scoreboard_visible boolean with three-mode visibility (CTF-404).

Data-preserving: visible events keep today's effective behavior (the public
scoreboard endpoint was AllowAny, so True maps to ``public``); hidden events
stay hidden.
"""

from django.db import migrations, models


def _forward(apps, schema_editor):
    CTFEvent = apps.get_model("ctf", "CTFEvent")
    CTFEvent.objects.filter(scoreboard_visible=False).update(scoreboard_visibility="hidden")


def _backward(apps, schema_editor):
    CTFEvent = apps.get_model("ctf", "CTFEvent")
    CTFEvent.objects.filter(scoreboard_visibility="hidden").update(scoreboard_visible=False)


class Migration(migrations.Migration):
    dependencies = [
        ("ctf", "0033_isolated_participant_accounts"),
    ]

    operations = [
        migrations.AddField(
            model_name="ctfevent",
            name="scoreboard_visibility",
            field=models.CharField(
                choices=[("public", "Public"), ("participants", "Participants"), ("hidden", "Hidden")],
                default="public",
                help_text=(
                    "Who can view the scoreboard: public (anyone), participants (registered only), "
                    "or hidden (organizers only)."
                ),
                max_length=20,
            ),
        ),
        migrations.RunPython(_forward, _backward),
        migrations.RemoveField(
            model_name="ctfevent",
            name="scoreboard_visible",
        ),
    ]
