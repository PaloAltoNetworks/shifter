"""Add SubnetAllocation model for CIDR reservation during concurrent provisioning.

Prevents race condition where multiple ranges pick the same CIDR because
Terraform hasn't created the AWS subnet yet (TOCTOU gap of ~30-90s).
"""

from django.db import migrations, models


def grant_permissions(apps, schema_editor):
    """Grant provisioner_lambda access to engine_subnetallocation."""
    if schema_editor.connection.vendor != "postgresql":
        return

    schema_editor.execute(
        """
        GRANT SELECT, INSERT, UPDATE ON engine_subnetallocation TO provisioner_lambda;
        GRANT USAGE, SELECT ON SEQUENCE engine_subnetallocation_id_seq TO provisioner_lambda;
        """
    )


def revoke_permissions(apps, schema_editor):
    """Revoke provisioner_lambda access from engine_subnetallocation."""
    if schema_editor.connection.vendor != "postgresql":
        return

    schema_editor.execute(
        """
        REVOKE SELECT, INSERT, UPDATE ON engine_subnetallocation FROM provisioner_lambda;
        REVOKE USAGE, SELECT ON SEQUENCE engine_subnetallocation_id_seq FROM provisioner_lambda;
        """
    )


class Migration(migrations.Migration):
    """Add SubnetAllocation table for CIDR reservation."""

    dependencies = [
        ("engine", "0017_normalize_ngfw_app_statuses"),
    ]

    operations = [
        migrations.CreateModel(
            name="SubnetAllocation",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("vpc_id", models.CharField(max_length=30)),
                ("cidr", models.CharField(help_text="e.g. 10.1.2.16/28", max_length=20)),
                ("subnet_size", models.IntegerField(help_text="Prefix length: 24 or 28")),
                ("range_id", models.IntegerField()),
                ("request_id", models.CharField(max_length=64)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("reserved", "Reserved"),
                            ("active", "Active"),
                            ("released", "Released"),
                        ],
                        default="reserved",
                        max_length=10,
                    ),
                ),
                ("reserved_at", models.DateTimeField(auto_now_add=True)),
                ("confirmed_at", models.DateTimeField(blank=True, null=True)),
                ("released_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "db_table": "engine_subnetallocation",
            },
        ),
        migrations.AddIndex(
            model_name="subnetallocation",
            index=models.Index(
                fields=["vpc_id", "status"],
                name="engine_subn_vpc_id_d1c5a7_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="subnetallocation",
            constraint=models.UniqueConstraint(
                condition=models.Q(("status__in", ["reserved", "active"])),
                fields=("vpc_id", "cidr"),
                name="unique_active_cidr_per_vpc",
            ),
        ),
        migrations.RunPython(grant_permissions, revoke_permissions),
    ]
