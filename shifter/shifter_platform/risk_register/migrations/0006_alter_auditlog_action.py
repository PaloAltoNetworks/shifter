from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("risk_register", "0005_alter_auditlog_action")]

    operations = [
        migrations.AlterField(
            model_name="auditlog",
            name="action",
            field=models.CharField(
                choices=[
                    ("create", "Create"),
                    ("update", "Update"),
                    ("delete", "Delete"),
                    ("restore", "Restore"),
                    ("close", "Close"),
                    ("reopen", "Reopen"),
                    ("login", "Login"),
                    ("logout", "Logout"),
                    ("login_failed", "Login Failed"),
                    ("access_denied", "Access Denied"),
                    ("role_sync", "Role Sync"),
                    ("connect", "Connect"),
                    ("disconnect", "Disconnect"),
                    ("download", "Download"),
                    ("provision", "Provision"),
                    ("deprovision", "Deprovision"),
                    ("ready", "Ready"),
                    ("failed", "Failed"),
                    ("pause", "Pause"),
                    ("resume", "Resume"),
                    ("cancel", "Cancel"),
                    ("recover", "Recover"),
                    ("spare_provision", "Spare Provision"),
                ],
                max_length=20,
            ),
        )
    ]
