"""Backfill Request records for legacy RangeInstances.

Creates Request records for existing RangeInstances that don't have a request FK,
ensuring all ranges have a proper request_id for the new Request-based pattern.
"""

import uuid

from django.db import migrations


def backfill_requests(apps, schema_editor):
    """Create Request records for RangeInstances without request FK."""
    Request = apps.get_model("cms", "Request")
    RangeInstance = apps.get_model("cms", "RangeInstance")
    User = apps.get_model("auth", "User")

    # Find RangeInstances without a request FK
    orphan_instances = RangeInstance.objects.filter(request__isnull=True)

    for instance in orphan_instances:
        # Get user - RangeInstance has user_id (int), we need User object
        try:
            user = User.objects.get(id=instance.user_id)
        except User.DoesNotExist:
            # Skip if user doesn't exist (shouldn't happen in practice)
            continue

        # Create Request record
        request = Request.objects.create(
            request_id=uuid.uuid4(),
            request_type="range",
            user=user,
        )

        # Link RangeInstance to Request
        instance.request = request
        instance.save(update_fields=["request"])


def reverse_backfill(apps, schema_editor):
    """Remove backfilled Request records.

    Note: This only removes the FK link, not the Request records themselves,
    to avoid accidentally deleting manually created Requests.
    """
    RangeInstance = apps.get_model("cms", "RangeInstance")

    # Clear request FK on all RangeInstances (safe operation)
    RangeInstance.objects.filter(request__isnull=False).update(request=None)


class Migration(migrations.Migration):
    dependencies = [
        ("cms", "0020_add_rangeinstance_request_fk"),
    ]

    operations = [
        migrations.RunPython(backfill_requests, reverse_backfill),
    ]
