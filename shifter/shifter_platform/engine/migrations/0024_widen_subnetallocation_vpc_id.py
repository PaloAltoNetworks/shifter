from django.db import migrations, models


class Migration(migrations.Migration):
    """Widen SubnetAllocation.vpc_id for GCE network self-links.

    GCE range cells key subnet allocations by the network self-link
    (projects/<project>/global/networks/<name>), which exceeds the previous
    max_length=30 sized for AWS vpc-ids. Widen to 255.
    """

    dependencies = [
        ("engine", "0023_range_event_outbox"),
    ]

    operations = [
        migrations.AlterField(
            model_name="subnetallocation",
            name="vpc_id",
            field=models.CharField(
                help_text=("AWS vpc-id, GDC network name, or GCE network self-link (projects/<p>/global/networks/<n>)"),
                max_length=255,
            ),
        ),
    ]
