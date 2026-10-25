from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("workspaces", "0017_authorization_operation_audit_attribution")]

    operations = [
        migrations.AddField(
            model_name="authorizationoperation",
            name="provider_store_id",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
    ]
