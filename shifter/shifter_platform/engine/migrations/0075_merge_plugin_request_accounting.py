"""Join independent adapter and model-request persistence branches."""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("engine", "0074_runtime_plugin_invocation"),
        ("engine", "0073_model_request_accounting"),
    ]

    operations = []
