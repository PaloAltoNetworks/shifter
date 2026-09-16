"""Add runtime Mission Control tenant/group lease policies (#2169)."""

from __future__ import annotations

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cms", "0044_rangeinstance_extension_days"),
    ]

    operations = [
        migrations.AddField(
            model_name="rangeinstance",
            name="lease_initial_days",
            field=models.PositiveIntegerField(
                blank=True,
                help_text="Initial lease duration snapshotted for this range generation.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="rangeinstance",
            name="lease_maximum_days",
            field=models.PositiveIntegerField(
                blank=True,
                help_text="Maximum lease duration snapshotted for this range generation.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="rangeinstance",
            name="lease_policy_group_revisions",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Bounded group id/revision provenance used for this generation's lease.",
            ),
        ),
        migrations.AddField(
            model_name="rangeinstance",
            name="lease_policy_source",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Bounded policy source used when this generation's lease was assigned.",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="rangeinstance",
            name="lease_policy_tenant_revision",
            field=models.PositiveIntegerField(
                blank=True,
                help_text="Runtime tenant-policy revision used for this generation, or zero for deployment fallback.",
                null=True,
            ),
        ),
        migrations.CreateModel(
            name="MissionControlTenantLeasePolicyRevision",
            fields=[
                ("revision", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "id",
                    models.PositiveSmallIntegerField(default=1, editable=False, primary_key=True, serialize=False),
                ),
            ],
            options={
                "verbose_name": "Mission Control tenant lease revision",
                "constraints": [
                    models.CheckConstraint(condition=models.Q(("id", 1)), name="ck_mc_tenant_lease_rev_singleton"),
                    models.CheckConstraint(
                        condition=models.Q(("revision__gt", 0)), name="ck_mc_tenant_lease_rev_positive"
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="MissionControlGroupLeasePolicyRevision",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("revision", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "group",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="mission_control_lease_policy_revision",
                        to="auth.group",
                    ),
                ),
            ],
            options={
                "verbose_name": "Mission Control group lease revision",
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("revision__gt", 0)), name="ck_mc_group_lease_rev_positive"
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="MissionControlTenantLeasePolicy",
            fields=[
                ("initial_days", models.PositiveIntegerField()),
                ("extension_days", models.PositiveIntegerField()),
                ("maximum_days", models.PositiveIntegerField()),
                ("extensions_enabled", models.BooleanField(default=True)),
                ("revision", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.PositiveSmallIntegerField(default=1, editable=False, primary_key=True, serialize=False)),
            ],
            options={
                "verbose_name": "Mission Control tenant lease policy",
                "constraints": [
                    models.CheckConstraint(condition=models.Q(("id", 1)), name="ck_mc_tenant_lease_singleton"),
                    models.CheckConstraint(
                        condition=models.Q(("initial_days__gt", 0)), name="ck_mc_tenant_lease_initial_positive"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("extension_days__gt", 0)), name="ck_mc_tenant_lease_extension_positive"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("maximum_days__gt", 0)), name="ck_mc_tenant_lease_maximum_positive"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("revision__gt", 0)), name="ck_mc_tenant_lease_revision_positive"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("initial_days__lte", 36500)), name="ck_mc_tenant_lease_initial_limit"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("extension_days__lte", 36500)), name="ck_mc_tenant_lease_extension_limit"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("maximum_days__lte", 36500)), name="ck_mc_tenant_lease_maximum_limit"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("initial_days__lte", models.F("maximum_days"))),
                        name="ck_mc_tenant_lease_initial_maximum",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="MissionControlGroupLeasePolicy",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("initial_days", models.PositiveIntegerField()),
                ("extension_days", models.PositiveIntegerField()),
                ("maximum_days", models.PositiveIntegerField()),
                ("extensions_enabled", models.BooleanField(default=True)),
                ("revision", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "group",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="mission_control_lease_policy",
                        to="auth.group",
                    ),
                ),
            ],
            options={
                "verbose_name": "Mission Control group lease policy",
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("initial_days__gt", 0)), name="ck_mc_group_lease_initial_positive"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("extension_days__gt", 0)), name="ck_mc_group_lease_extension_positive"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("maximum_days__gt", 0)), name="ck_mc_group_lease_maximum_positive"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("revision__gt", 0)), name="ck_mc_group_lease_revision_positive"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("initial_days__lte", 36500)), name="ck_mc_group_lease_initial_limit"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("extension_days__lte", 36500)), name="ck_mc_group_lease_extension_limit"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("maximum_days__lte", 36500)), name="ck_mc_group_lease_maximum_limit"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("initial_days__lte", models.F("maximum_days"))),
                        name="ck_mc_group_lease_initial_maximum",
                    ),
                ],
            },
        ),
    ]
