from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("engine", "0084_reconcile_range_ngfw_instance_grant")]

    operations = [
        migrations.AddField(
            model_name="raesimagemapping",
            name="image_kind",
            field=models.CharField(default="image", help_text="Provider image contract: image or machine-image.", max_length=32),
        ),
        migrations.AddField(
            model_name="raesimagemapping",
            name="bootstrap_capability",
            field=models.CharField(default="standard", help_text="Generic realization capability required by the selected image.", max_length=64),
        ),
        migrations.AddField(model_name="raesimagemapping", name="participant_container_name", field=models.CharField(blank=True, default="", max_length=128)),
        migrations.AddField(model_name="raesimagemapping", name="participant_username", field=models.CharField(blank=True, default="", max_length=32)),
        migrations.AddField(model_name="raesimagemapping", name="participant_readiness_contract", field=models.CharField(blank=True, default="", max_length=64)),
        migrations.AddField(model_name="raesimagemapping", name="participant_readiness_manifest_sha256", field=models.CharField(blank=True, default="", max_length=64)),
    ]
