from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("engine", "0032_capacity_signaling")]

    operations = [
        migrations.AlterField(
            model_name="acescontentdeliverybinding",
            name="content_address",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Compiled ACES content resource address this binding identifies.",
                max_length=500,
            ),
        ),
        migrations.AddField(
            model_name="acescontentdeliverybinding",
            name="resource_type",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="acescontentdeliverybinding",
            name="resource_address",
            field=models.CharField(blank=True, default="", max_length=500),
        ),
        migrations.AddField(
            model_name="acescontentdeliverybinding",
            name="payload_kind",
            field=models.CharField(blank=True, default="", max_length=32),
        ),
        migrations.AddField(
            model_name="acescontentdeliverybinding",
            name="install_policy",
            field=models.CharField(blank=True, default="", max_length=32),
        ),
        migrations.RemoveConstraint(
            model_name="acescontentdeliverybinding",
            name="unique_aces_content_delivery_binding",
        ),
        migrations.AddConstraint(
            model_name="acescontentdeliverybinding",
            constraint=models.UniqueConstraint(
                condition=~models.Q(("content_address", "")),
                fields=("range", "content_address"),
                name="unique_aces_content_delivery_binding",
            ),
        ),
        migrations.AddConstraint(
            model_name="acescontentdeliverybinding",
            constraint=models.UniqueConstraint(
                condition=models.Q(("resource_type", "feature-binding")),
                fields=("range", "resource_type", "resource_address"),
                name="unique_aces_resource_delivery_binding",
            ),
        ),
        migrations.AddConstraint(
            model_name="acescontentdeliverybinding",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("binding_version", 1), models.Q(("content_address", ""), _negated=True)),
                    models.Q(
                        ("binding_version", 2),
                        ("content_address", ""),
                        ("resource_type", "feature-binding"),
                        models.Q(("resource_address", ""), _negated=True),
                        models.Q(("payload_kind", ""), _negated=True),
                        models.Q(("install_policy", ""), _negated=True),
                    ),
                    _connector="OR",
                ),
                name="valid_aces_delivery_binding_identity",
            ),
        ),
    ]
