from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("cms", "0040_workspace_binding_required")]

    operations = [
        migrations.RenameModel(old_name="AcesPackageSource", new_name="RaesPackageSource"),
        migrations.AlterModelOptions(
            name="raespackagesource",
            options={
                "ordering": ["scenario_id"],
                "verbose_name": "RAES Package Source",
                "verbose_name_plural": "RAES Package Sources",
            },
        ),
        migrations.AlterField(
            model_name="raespackagesource",
            name="scenario_id",
            field=models.SlugField(
                help_text="Catalog id for this RAES package-source entry",
                max_length=100,
                unique=True,
            ),
        ),
        migrations.AlterField(
            model_name="raespackagesource",
            name="contract_kind",
            field=models.CharField(
                help_text="Package contract discriminator (e.g. 'raes')",
                max_length=32,
            ),
        ),
    ]
