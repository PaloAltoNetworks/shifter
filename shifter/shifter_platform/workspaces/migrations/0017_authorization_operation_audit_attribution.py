from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("workspaces", "0016_remove_authorizationoperation_uniq_authz_fence_generation_and_more")]

    operations = [
        migrations.AddField(
            model_name="authorizationoperation",
            name="audit_actor_id",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="authorizationoperation",
            name="audit_actor_type",
            field=models.CharField(blank=True, default="", max_length=16),
        ),
        migrations.AddField(
            model_name="authorizationoperation",
            name="audit_request_id",
            field=models.CharField(blank=True, default="", max_length=128),
        ),
        migrations.AddField(
            model_name="authorizationoperation",
            name="audit_source_ip",
            field=models.GenericIPAddressField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="authorizationoperation",
            name="audit_user_agent",
            field=models.CharField(blank=True, default="", max_length=500),
        ),
    ]
