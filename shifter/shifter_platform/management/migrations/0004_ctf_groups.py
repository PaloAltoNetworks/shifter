"""Data migration: create CTF Organizer and CTF Participant groups.

Migrates existing UserProfile.user_type values to Django Groups.
"""

from django.db import migrations


def create_groups_and_migrate(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    UserProfile = apps.get_model("management", "UserProfile")

    organizer_group, _ = Group.objects.get_or_create(name="CTF Organizer")
    participant_group, _ = Group.objects.get_or_create(name="CTF Participant")

    # Migrate existing organizers
    for profile in UserProfile.objects.filter(user_type="ctf_organizer"):
        profile.user.groups.add(organizer_group)

    # Migrate existing participants
    for profile in UserProfile.objects.filter(user_type="ctf_participant"):
        profile.user.groups.add(participant_group)


def delete_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name__in=["CTF Organizer", "CTF Participant"]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("management", "0003_userprofile_ctf_fields"),
    ]

    operations = [
        migrations.RunPython(create_groups_and_migrate, delete_groups),
    ]
