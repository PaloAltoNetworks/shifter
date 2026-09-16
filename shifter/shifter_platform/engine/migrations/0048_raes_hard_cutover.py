from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("engine", "0047_revoke_residual_grants_from_provisioner")]

    operations = [
        migrations.RenameModel(old_name="AcesImageMapping", new_name="RaesImageMapping"),
        migrations.AlterModelTable(name="raesimagemapping", table="engine_raes_image_mapping"),
        migrations.RemoveConstraint(
            model_name="raesimagemapping",
            name="unique_aces_image_mapping",
        ),
        migrations.AddConstraint(
            model_name="raesimagemapping",
            constraint=models.UniqueConstraint(
                fields=("provider", "source_name", "source_version"),
                name="unique_raes_image_mapping",
            ),
        ),
        migrations.AlterField(
            model_name="raesimagemapping",
            name="source_name",
            field=models.CharField(
                help_text="Authored RAES image source name (for example 'kali').",
                max_length=200,
            ),
        ),
        migrations.RenameModel(
            old_name="AcesContentDeliveryBinding",
            new_name="RaesContentDeliveryBinding",
        ),
        migrations.AlterModelTable(
            name="raescontentdeliverybinding",
            table="engine_raes_content_delivery_binding",
        ),
        migrations.RemoveConstraint(
            model_name="raescontentdeliverybinding",
            name="unique_aces_content_delivery_binding",
        ),
        migrations.RemoveConstraint(
            model_name="raescontentdeliverybinding",
            name="unique_aces_resource_delivery_binding",
        ),
        migrations.RemoveConstraint(
            model_name="raescontentdeliverybinding",
            name="valid_aces_delivery_binding_identity",
        ),
        migrations.AddConstraint(
            model_name="raescontentdeliverybinding",
            constraint=models.UniqueConstraint(
                condition=~models.Q(content_address=""),
                fields=("range", "content_address"),
                name="unique_raes_content_delivery_binding",
            ),
        ),
        migrations.AddConstraint(
            model_name="raescontentdeliverybinding",
            constraint=models.UniqueConstraint(
                condition=models.Q(resource_type="feature-binding"),
                fields=("range", "resource_type", "resource_address"),
                name="unique_raes_resource_delivery_binding",
            ),
        ),
        migrations.AddConstraint(
            model_name="raescontentdeliverybinding",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(binding_version=1) & ~models.Q(content_address="")
                    | models.Q(
                        binding_version=2,
                        content_address="",
                        resource_type="feature-binding",
                    )
                    & ~models.Q(resource_address="")
                    & ~models.Q(payload_kind="")
                    & ~models.Q(install_policy="")
                ),
                name="valid_raes_delivery_binding_identity",
            ),
        ),
        migrations.AlterField(
            model_name="raescontentdeliverybinding",
            name="content_address",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Compiled RAES content resource address this binding identifies.",
                max_length=500,
            ),
        ),
    ]
