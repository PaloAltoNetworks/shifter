"""Tests for GCP task-runner configuration in engine.ecs."""

import os
from unittest.mock import MagicMock, patch


class TestStartEcsTaskGCP:
    """GCP uses Kubernetes namespace/image settings and omits AWS network config."""

    def test_uses_generic_task_settings_for_gcp(self, settings):
        from engine.ecs import _start_ecs_task

        settings.CLOUD_PROVIDER = "gcp"
        settings.ENGINE_TASK_CLUSTER = "shifter-jobs"
        settings.ENGINE_TASK_DEFINITION = (
            "us-central1-docker.pkg.dev/shifter-gcp-dev/shifter-gcp-dev-pulumi-provisioner:latest"
        )
        settings.ENGINE_ECS_CLUSTER_ARN = ""
        settings.ENGINE_TASK_DEFINITION_ARN = ""
        settings.ENGINE_TASK_NETWORK_SECURITY_GROUP_ID = ""
        settings.ENGINE_TASK_NETWORK_SUBNET_IDS = ""

        env_overrides = {
            "ENVIRONMENT": "gcp-dev",
            "CLOUD_PROVIDER": "gcp",
            "CLOUD_REGION": "us-central1",
            "GCP_REGION": "us-central1",
            "GCP_PROJECT_ID": "shifter-gcp-dev",
            "GOOGLE_CLOUD_PROJECT": "shifter-gcp-dev",
            "DB_HOST": "10.0.0.10",
            "DB_PORT": "5432",
            "DB_NAME": "shifter",
            "DB_USER": "shifter",
            "DB_PASSWORD": "secret",
            "FIELD_ENCRYPTION_KEY": "fernet-key",
            "RANGE_EVENTS_TOPIC_ID": "projects/shifter-gcp-dev/topics/shifter-gcp-dev-events",
            "AGENT_STORAGE_BUCKET": "shifter-gcp-dev-gcp-dev-assets",
            "RANGE_NETWORK_ID": "projects/shifter-gcp-dev/global/networks/shifter-gcp-dev-range",
            "RANGE_NETWORK_CIDR": "10.50.0.0/16",
            "RANGE_NETWORK_REGION": "us-central1",
            "PORTAL_NETWORK_CIDRS": "10.40.0.0/20,10.44.0.0/16",
        }

        with (
            patch.dict(os.environ, env_overrides, clear=False),
            patch("engine.ecs.get_task_runner") as mock_get_runner,
        ):
            mock_runner = MagicMock()
            mock_runner.run_task.return_value = "shifter-jobs/pulumi-provisioner-range-provision-abc123"
            mock_get_runner.return_value = mock_runner

            result = _start_ecs_task(range_id=42, user_id=7, command="provision")

            assert result == "shifter-jobs/pulumi-provisioner-range-provision-abc123"
            call_kwargs = mock_runner.run_task.call_args.kwargs
            assert call_kwargs["cluster"] == "shifter-jobs"
            assert (
                call_kwargs["task_definition"]
                == "us-central1-docker.pkg.dev/shifter-gcp-dev/shifter-gcp-dev-pulumi-provisioner:latest"
            )
            assert call_kwargs["network_config"] is None
            assert call_kwargs["env_overrides"]["RANGE_NETWORK_ID"] == env_overrides["RANGE_NETWORK_ID"]
            assert call_kwargs["env_overrides"]["RANGE_NETWORK_CIDR"] == env_overrides["RANGE_NETWORK_CIDR"]
            assert call_kwargs["env_overrides"]["PORTAL_NETWORK_CIDRS"] == env_overrides["PORTAL_NETWORK_CIDRS"]
            assert call_kwargs["env_overrides"]["DB_HOST"] == env_overrides["DB_HOST"]
