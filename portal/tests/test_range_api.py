"""Tests for Range API endpoints."""

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from mission_control.models import AgentConfig, OperatingSystem, Range, StrataConfig

User = get_user_model()


@pytest.fixture
def windows_os(db):
    return OperatingSystem.objects.get(slug="windows")


@pytest.fixture
def linux_os(db):
    return OperatingSystem.objects.get(slug="linux-debian")


@pytest.fixture
def test_agent(db, django_user_model, windows_os):
    user = django_user_model.objects.create_user(
        username="rangetest", email="rangetest@example.com", password="testpass"
    )
    agent = AgentConfig.objects.create(
        user=user,
        os=windows_os,
        name="Test XDR Agent",
        s3_key="agents/test/fake.msi",
        original_filename="agent.msi",
        file_size_bytes=50000000,
        sha256_hash="abc123",
    )
    return agent


@pytest.fixture
def mock_provisioner():
    """Mock the engine service to avoid AWS calls."""
    with (
        patch("mission_control.services.engine.start_provisioning") as mock_provision,
        patch("mission_control.services.engine.start_teardown") as mock_teardown,
    ):
        mock_provision.return_value = None  # No ARN in test mode
        mock_teardown.return_value = None
        yield {"provision": mock_provision, "teardown": mock_teardown}


@pytest.mark.django_db
class TestRangeStatus:
    def test_requires_login(self, client):
        response = client.get(reverse("mission_control:range_status"))
        assert response.status_code == 302  # Redirect to login

    def test_returns_no_range_when_none_exists(self, client, test_agent):
        client.force_login(test_agent.user)
        response = client.get(reverse("mission_control:range_status"))
        assert response.status_code == 200
        data = response.json()
        assert data["has_range"] is False
        assert data["range"] is None

    def test_returns_active_range(self, client, test_agent):
        client.force_login(test_agent.user)

        # Create an active range
        range_obj = Range.objects.create(
            user=test_agent.user,
            agent=test_agent,
            status=Range.Status.READY,
            victim_ip="10.0.1.100",  # Stored in DB but not exposed to client
            chat_url="http://localhost:3000/chat/1",
        )

        response = client.get(reverse("mission_control:range_status"))
        assert response.status_code == 200
        data = response.json()
        assert data["has_range"] is True
        assert data["range"]["id"] == range_obj.id
        assert data["range"]["status"] == "ready"
        assert data["range"]["chat_url"] == "http://localhost:3000/chat/1"
        # victim_ip intentionally not exposed to client (internal infra detail)
        assert "victim_ip" not in data["range"]


@pytest.mark.django_db
class TestLaunchRange:
    def test_requires_login(self, client):
        response = client.post(reverse("mission_control:launch_range"))
        assert response.status_code == 302

    def test_requires_agent_id(self, client, test_agent):
        client.force_login(test_agent.user)
        response = client.post(
            reverse("mission_control:launch_range"),
            data={},
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "agent_id" in response.json()["error"]

    def test_rejects_nonexistent_agent(self, client, test_agent):
        client.force_login(test_agent.user)
        response = client.post(
            reverse("mission_control:launch_range"),
            data={"agent_id": 99999},
            content_type="application/json",
        )
        assert response.status_code == 404

    def test_successful_launch(self, client, test_agent, settings):
        # Ensure ECS is not configured (local dev mode)
        settings.PULUMI_ECS_CLUSTER_ARN = ""

        client.force_login(test_agent.user)
        response = client.post(
            reverse("mission_control:launch_range"),
            data={"agent_id": test_agent.id},
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["range"]["status"] == "provisioning"
        assert data["range"]["agent_id"] == test_agent.id

    def test_successful_launch_with_ecs(self, client, test_agent):
        """Test launch with mocked ECS."""
        mock_path = "mission_control.services.engine._get_ecs_client"
        with patch(mock_path) as mock_client:
            task_arn = "arn:aws:ecs:us-east-2:123:task/test/abc123"
            mock_client.return_value.run_task.return_value = {
                "tasks": [{"taskArn": task_arn}],
                "failures": [],
            }

            client.force_login(test_agent.user)
            from django.conf import settings

            # Set ECS config
            orig_cluster = getattr(settings, "PULUMI_ECS_CLUSTER_ARN", "")
            orig_task_def = getattr(settings, "PULUMI_TASK_DEFINITION_ARN", "")
            orig_sg = getattr(settings, "PULUMI_ECS_SECURITY_GROUP_ID", "")
            orig_subnets = getattr(settings, "PULUMI_PRIVATE_SUBNET_IDS", "")

            settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123:cluster/test"
            settings.PULUMI_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123:task-definition/test:1"
            settings.PULUMI_ECS_SECURITY_GROUP_ID = "sg-12345678"
            settings.PULUMI_PRIVATE_SUBNET_IDS = "subnet-abc123"

            try:
                response = client.post(
                    reverse("mission_control:launch_range"),
                    data={"agent_id": test_agent.id},
                    content_type="application/json",
                )

                assert response.status_code == 200
                data = response.json()
                assert data["success"] is True
                assert data["range"]["status"] == "provisioning"

                # Verify task ARN was stored
                range_obj = Range.objects.get(id=data["range"]["id"])
                assert range_obj.step_function_execution_arn == task_arn
            finally:
                settings.PULUMI_ECS_CLUSTER_ARN = orig_cluster
                settings.PULUMI_TASK_DEFINITION_ARN = orig_task_def
                settings.PULUMI_ECS_SECURITY_GROUP_ID = orig_sg
                settings.PULUMI_PRIVATE_SUBNET_IDS = orig_subnets

    def test_rejects_when_range_exists(self, client, test_agent, settings):
        settings.PULUMI_ECS_CLUSTER_ARN = ""
        client.force_login(test_agent.user)

        # Create existing range
        Range.objects.create(
            user=test_agent.user,
            agent=test_agent,
            status=Range.Status.READY,
        )

        response = client.post(
            reverse("mission_control:launch_range"),
            data={"agent_id": test_agent.id},
            content_type="application/json",
        )

        assert response.status_code == 409
        assert "already have an active range" in response.json()["error"]

    def test_ad_scenario_rejects_linux_agent(self, client, test_agent, linux_os, settings):
        """AD scenario requires Windows agent (used for both DC and victim)."""
        settings.PULUMI_ECS_CLUSTER_ARN = ""
        client.force_login(test_agent.user)

        # Create a Linux agent (invalid for AD scenario)
        linux_agent = AgentConfig.objects.create(
            user=test_agent.user,
            os=linux_os,
            name="Linux Agent",
            s3_key="agents/test/fake.deb",
            original_filename="agent.deb",
            file_size_bytes=25000000,
            sha256_hash="def456",
        )

        response = client.post(
            reverse("mission_control:launch_range"),
            data={
                "agent_id": linux_agent.id,
                "scenario": "ad_attack_lab",
            },
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "Windows" in response.json()["error"]

    def test_ad_scenario_success_with_windows_agent(self, client, test_agent, settings):
        """AD scenario succeeds with Windows agent (used for both DC and victim)."""
        settings.PULUMI_ECS_CLUSTER_ARN = ""
        client.force_login(test_agent.user)

        # test_agent uses windows_os fixture
        response = client.post(
            reverse("mission_control:launch_range"),
            data={
                "agent_id": test_agent.id,
                "scenario": "ad_attack_lab",
            },
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["range"]["status"] == "provisioning"
        # dc_agent should be same as agent for AD scenario
        assert data["range"]["dc_agent_id"] == test_agent.id

    def test_basic_scenario_allows_any_agent(self, client, test_agent, linux_os, settings):
        """Basic scenario works with any agent OS."""
        settings.PULUMI_ECS_CLUSTER_ARN = ""
        client.force_login(test_agent.user)

        # Create a Linux agent
        linux_agent = AgentConfig.objects.create(
            user=test_agent.user,
            os=linux_os,
            name="Linux Agent",
            s3_key="agents/test/fake.deb",
            original_filename="agent.deb",
            file_size_bytes=25000000,
            sha256_hash="def456",
        )

        response = client.post(
            reverse("mission_control:launch_range"),
            data={"agent_id": linux_agent.id, "scenario": "basic"},
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["range"]["dc_agent_id"] is None


@pytest.mark.django_db
class TestCancelRange:
    def test_requires_login(self, client):
        response = client.post(reverse("mission_control:cancel_range"))
        assert response.status_code == 302

    def test_returns_404_when_no_range(self, client, test_agent):
        client.force_login(test_agent.user)
        response = client.post(reverse("mission_control:cancel_range"))
        assert response.status_code == 404

    def test_successful_cancel_provisioning(self, client, test_agent):
        client.force_login(test_agent.user)

        # Create a provisioning range
        range_obj = Range.objects.create(
            user=test_agent.user,
            agent=test_agent,
            status=Range.Status.PROVISIONING,
        )

        response = client.post(reverse("mission_control:cancel_range"))
        assert response.status_code == 200
        assert response.json()["success"] is True

        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.DESTROYED
        assert range_obj.destroyed_at is not None

    def test_cannot_cancel_ready_range(self, client, test_agent):
        client.force_login(test_agent.user)

        # Create a ready range (can't cancel, must destroy)
        Range.objects.create(
            user=test_agent.user,
            agent=test_agent,
            status=Range.Status.READY,
        )

        response = client.post(reverse("mission_control:cancel_range"))
        assert response.status_code == 400
        assert "Cannot cancel" in response.json()["error"]


@pytest.mark.django_db
class TestDestroyRange:
    def test_requires_login(self, client):
        response = client.post(reverse("mission_control:destroy_range"))
        assert response.status_code == 302

    def test_returns_404_when_no_range(self, client, test_agent):
        client.force_login(test_agent.user)
        response = client.post(reverse("mission_control:destroy_range"))
        assert response.status_code == 404

    def test_successful_destroy(self, client, test_agent, settings):
        settings.PULUMI_ECS_CLUSTER_ARN = ""
        client.force_login(test_agent.user)

        # Create a ready range
        range_obj = Range.objects.create(
            user=test_agent.user,
            agent=test_agent,
            status=Range.Status.READY,
        )

        response = client.post(reverse("mission_control:destroy_range"))
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        # Verify range was marked as DESTROYING (async cleanup will set DESTROYED)
        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.DESTROYING

    def test_can_destroy_failed_range(self, client, test_agent, settings):
        """Failed ranges can be destroyed to clean up."""
        settings.PULUMI_ECS_CLUSTER_ARN = ""
        client.force_login(test_agent.user)

        # Create a failed range
        range_obj = Range.objects.create(
            user=test_agent.user,
            agent=test_agent,
            status=Range.Status.FAILED,
            error_message="Provisioning timed out",
        )

        response = client.post(reverse("mission_control:destroy_range"))
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        # Verify range was marked as DESTROYING (async cleanup will set DESTROYED)
        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.DESTROYING


@pytest.mark.django_db
class TestLaunchRangeWhileDestroying:
    """Test that users CAN launch while a range is being destroyed."""

    def test_can_launch_while_destroying(self, client, test_agent, settings):
        """User can launch a new range while old one is being cleaned up."""
        settings.PULUMI_ECS_CLUSTER_ARN = ""
        client.force_login(test_agent.user)

        # Create a range being destroyed
        Range.objects.create(
            user=test_agent.user,
            agent=test_agent,
            status=Range.Status.DESTROYING,
            subnet_index=1,
        )

        # User can launch a new range (gets different subnet)
        response = client.post(
            reverse("mission_control:launch_range"),
            data={"agent_id": test_agent.id},
            content_type="application/json",
        )

        assert response.status_code == 200
        # New range should get subnet_index=2 (1 is reserved by DESTROYING range)
        new_range = Range.objects.filter(status=Range.Status.PROVISIONING).first()
        assert new_range is not None
        assert new_range.subnet_index == 2


@pytest.mark.django_db
class TestListAgents:
    def test_requires_login(self, client):
        response = client.get(reverse("mission_control:list_agents"))
        assert response.status_code == 302

    def test_returns_user_agents(self, client, test_agent):
        client.force_login(test_agent.user)
        response = client.get(reverse("mission_control:list_agents"))

        assert response.status_code == 200
        data = response.json()
        assert len(data["agents"]) == 1
        assert data["agents"][0]["id"] == test_agent.id
        assert data["agents"][0]["name"] == "Test XDR Agent"

    def test_includes_os_slug_for_filtering(self, client, test_agent):
        """Agent list should include os_slug for frontend filtering."""
        client.force_login(test_agent.user)
        response = client.get(reverse("mission_control:list_agents"))

        assert response.status_code == 200
        data = response.json()
        agent = data["agents"][0]
        assert "os_slug" in agent
        assert agent["os_slug"] == "windows"  # test_agent uses windows_os fixture


@pytest.mark.django_db
class TestSubnetIndexAllocation:
    """Tests for subnet_index allocation in Range model."""

    def test_allocates_index_on_launch(self, client, test_agent, settings):
        """Launch should allocate a subnet_index."""
        settings.PULUMI_ECS_CLUSTER_ARN = ""
        client.force_login(test_agent.user)

        response = client.post(
            reverse("mission_control:launch_range"),
            data={"agent_id": test_agent.id},
            content_type="application/json",
        )

        assert response.status_code == 200
        range_obj = Range.objects.get(id=response.json()["range"]["id"])
        assert range_obj.subnet_index is not None
        assert 1 <= range_obj.subnet_index <= 254

    def test_first_allocation_returns_one(self, test_agent):
        """First allocation should return index 1."""
        index = Range.allocate_subnet_index()
        assert index == 1

    def test_allocates_sequential_indices(self, test_agent):
        """Allocations should fill gaps."""
        # Create range with index 1
        Range.objects.create(
            user=test_agent.user,
            agent=test_agent,
            status=Range.Status.PROVISIONING,
            subnet_index=1,
        )

        # Next allocation should be 2
        index = Range.allocate_subnet_index()
        assert index == 2

    def test_reuses_destroyed_indices(self, test_agent):
        """Destroyed ranges should free up their indices."""
        # Create and destroy a range with index 1
        Range.objects.create(
            user=test_agent.user,
            agent=test_agent,
            status=Range.Status.DESTROYED,
            subnet_index=1,
        )

        # Should reuse index 1
        index = Range.allocate_subnet_index()
        assert index == 1

    def test_fills_gaps(self, test_agent):
        """Should fill gaps in index sequence."""
        # Create ranges with indices 1 and 3 (gap at 2)
        Range.objects.create(
            user=test_agent.user,
            agent=test_agent,
            status=Range.Status.READY,
            subnet_index=1,
        )
        Range.objects.create(
            user=test_agent.user,
            agent=test_agent,
            status=Range.Status.READY,
            subnet_index=3,
        )

        # Should fill gap at index 2
        index = Range.allocate_subnet_index()
        assert index == 2

    def test_skips_active_indices(self, test_agent):
        """Should not reuse indices from active ranges (excludes DESTROYED and FAILED)."""
        # Create ranges in various active states (FAILED is now excluded like DESTROYED)
        for i, status in enumerate(
            [
                Range.Status.PROVISIONING,
                Range.Status.READY,
                Range.Status.PAUSED,
                Range.Status.DESTROYING,
            ],
            start=1,
        ):
            Range.objects.create(
                user=test_agent.user,
                agent=test_agent,
                status=status,
                subnet_index=i,
            )

        # Next allocation should be 5
        index = Range.allocate_subnet_index()
        assert index == 5

    def test_reuses_failed_indices(self, test_agent):
        """Failed ranges should free up their indices (like destroyed ranges)."""
        # Create a failed range with index 1
        Range.objects.create(
            user=test_agent.user,
            agent=test_agent,
            status=Range.Status.FAILED,
            subnet_index=1,
        )

        # Should reuse index 1 since FAILED ranges are excluded from allocation
        index = Range.allocate_subnet_index()
        assert index == 1

    def test_raises_when_exhausted(self, test_agent):
        """Should raise ValueError when all indices are used."""
        # Create ranges for all 254 indices
        for i in range(1, 255):
            Range.objects.create(
                user=test_agent.user,
                agent=test_agent,
                status=Range.Status.READY,
                subnet_index=i,
            )

        with pytest.raises(ValueError, match="No subnet indices available"):
            Range.allocate_subnet_index()

    def test_capacity_error_returns_503(self, client, test_agent, settings, django_user_model):
        """API should return 503 when no capacity available."""
        settings.PULUMI_ECS_CLUSTER_ARN = ""
        client.force_login(test_agent.user)

        # Create a different user to hold the 254 ranges (so test_agent.user has no active range)
        other_user = django_user_model.objects.create_user(
            username="capacitytest",
            email="capacitytest@example.com",
            password="testpass",
        )

        # Create ranges for all 254 indices (owned by other_user, all DESTROYED so they don't block)
        # Actually we need ACTIVE ranges to block the indices
        for i in range(1, 255):
            Range.objects.create(
                user=other_user,
                agent=test_agent,
                status=Range.Status.READY,
                subnet_index=i,
            )

        response = client.post(
            reverse("mission_control:launch_range"),
            data={"agent_id": test_agent.id},
            content_type="application/json",
        )

        assert response.status_code == 503
        assert "No capacity available" in response.json()["error"]


@pytest.mark.django_db
class TestLaunchRangeNGFW:
    """Tests for NGFW support in range launch."""

    def test_launch_range_ngfw_disabled_by_default(self, client, test_agent, settings):
        """Launching without ngfw_enabled should default to False in both response and DB."""
        settings.PULUMI_ECS_CLUSTER_ARN = ""
        client.force_login(test_agent.user)

        response = client.post(
            reverse("mission_control:launch_range"),
            data={"agent_id": test_agent.id},
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        # Verify response includes ngfw_enabled=False
        assert data["range"]["ngfw_enabled"] is False
        # Verify DB was updated correctly
        range_obj = Range.objects.get(id=data["range"]["id"])
        assert range_obj.ngfw_enabled is False

    def test_launch_range_with_ngfw_enabled(self, client, test_agent, settings):
        """Launching with ngfw_enabled=True requires ngfw_config_id and sets both on Range."""
        settings.PULUMI_ECS_CLUSTER_ARN = ""
        client.force_login(test_agent.user)

        # Create Strata config (required when NGFW is enabled)
        strata_config = StrataConfig.objects.create(
            user=test_agent.user,
            name="Test SCM Config",
            scm_folder_name="Test-Folder",
            scm_pin_id="test-pin-id",
            scm_pin_value="test-pin-value",
        )

        response = client.post(
            reverse("mission_control:launch_range"),
            data={
                "agent_id": test_agent.id,
                "ngfw_enabled": True,
                "ngfw_config_id": strata_config.id,
            },
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        # Verify response includes ngfw_enabled
        assert data["range"]["ngfw_enabled"] is True
        # Verify DB was updated
        range_obj = Range.objects.get(id=data["range"]["id"])
        assert range_obj.ngfw_enabled is True
        assert range_obj.strata_config_id == strata_config.id

    def test_launch_range_with_ngfw_disabled_explicit(self, client, test_agent, settings):
        """Launching with ngfw_enabled=False should set it to False in both response and DB."""
        settings.PULUMI_ECS_CLUSTER_ARN = ""
        client.force_login(test_agent.user)

        response = client.post(
            reverse("mission_control:launch_range"),
            data={"agent_id": test_agent.id, "ngfw_enabled": False},
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        # Verify response includes ngfw_enabled=False
        assert data["range"]["ngfw_enabled"] is False
        # Verify DB was updated correctly
        range_obj = Range.objects.get(id=data["range"]["id"])
        assert range_obj.ngfw_enabled is False


@pytest.mark.django_db
class TestRangeStatusNGFW:
    """Tests for NGFW fields in range status response."""

    def test_range_status_includes_ngfw_when_disabled(self, client, test_agent):
        """Status response should include ngfw_enabled=False when disabled."""
        client.force_login(test_agent.user)

        Range.objects.create(
            user=test_agent.user,
            agent=test_agent,
            status=Range.Status.READY,
            ngfw_enabled=False,
        )

        response = client.get(reverse("mission_control:range_status"))
        assert response.status_code == 200
        data = response.json()
        assert data["range"]["ngfw_enabled"] is False
        assert data["range"]["ngfw_instance_id"] == ""
        assert data["range"]["ngfw_untrust_ip"] is None
        assert data["range"]["ngfw_trust_ip"] is None

    def test_range_status_includes_ngfw_when_enabled(self, client, test_agent):
        """Status response should include NGFW details when enabled."""
        client.force_login(test_agent.user)

        Range.objects.create(
            user=test_agent.user,
            agent=test_agent,
            status=Range.Status.READY,
            ngfw_enabled=True,
            ngfw_instance_id="i-ngfw12345",
            ngfw_untrust_ip="10.1.5.10",
            ngfw_trust_ip="10.1.5.11",
        )

        response = client.get(reverse("mission_control:range_status"))
        assert response.status_code == 200
        data = response.json()
        assert data["range"]["ngfw_enabled"] is True
        assert data["range"]["ngfw_instance_id"] == "i-ngfw12345"
        assert data["range"]["ngfw_untrust_ip"] == "10.1.5.10"
        assert data["range"]["ngfw_trust_ip"] == "10.1.5.11"


# --- Strata Config CRUD API (for NGFW) ---


@pytest.mark.django_db
class TestStrataConfigAPI:
    """Tests for Strata configuration CRUD API endpoints (for NGFW)."""

    @pytest.fixture
    def user(self):
        return User.objects.create_user(username="test@example.com", email="test@example.com")

    @pytest.fixture
    def other_user(self):
        return User.objects.create_user(username="other@example.com", email="other@example.com")

    @pytest.fixture
    def client(self, user):
        client = Client()
        client.force_login(user)
        return client

    @pytest.fixture
    def strata_config(self, user):
        return StrataConfig.objects.create(
            user=user,
            name="Test Config",
            scm_folder_name="Test-Folder",
            scm_pin_id="test-pin-id",
            scm_pin_value="test-pin-value-secret",
        )

    # --- List Configs ---

    def test_list_configs_returns_user_configs(self, client, strata_config):
        """list_ngfw_configs returns configs belonging to the authenticated user."""
        response = client.get(reverse("mission_control:list_ngfw_configs"))
        assert response.status_code == 200
        data = response.json()
        assert len(data["configs"]) == 1
        assert data["configs"][0]["id"] == strata_config.id
        assert data["configs"][0]["name"] == "Test Config"

    def test_list_configs_does_not_expose_pin_value(self, client, strata_config):
        """list_ngfw_configs does NOT expose scm_pin_value in response."""
        response = client.get(reverse("mission_control:list_ngfw_configs"))
        assert response.status_code == 200
        data = response.json()
        assert "scm_pin_value" not in data["configs"][0]
        # Verify the secret is really not there
        assert "test-pin-value-secret" not in str(data)

    def test_list_configs_excludes_other_users(self, client, user, other_user):
        """list_ngfw_configs does not return configs from other users."""
        # Create config for other user
        StrataConfig.objects.create(
            user=other_user,
            name="Other User Config",
            scm_folder_name="Other-Folder",
            scm_pin_id="other-pin",
            scm_pin_value="othersecret",
        )

        response = client.get(reverse("mission_control:list_ngfw_configs"))
        assert response.status_code == 200
        data = response.json()
        assert len(data["configs"]) == 0

    def test_list_configs_excludes_deleted(self, client, user):
        """list_ngfw_configs does not return soft-deleted configs."""
        # Create active and deleted configs
        active = StrataConfig.objects.create(
            user=user,
            name="Active",
            scm_folder_name="Active-Folder",
            scm_pin_id="pin1",
            scm_pin_value="secret1",
        )
        StrataConfig.objects.create(
            user=user,
            name="Deleted",
            scm_folder_name="Deleted-Folder",
            scm_pin_id="pin2",
            scm_pin_value="secret2",
            deleted_at=timezone.now(),
        )

        response = client.get(reverse("mission_control:list_ngfw_configs"))
        assert response.status_code == 200
        data = response.json()
        assert len(data["configs"]) == 1
        assert data["configs"][0]["id"] == active.id

    def test_list_configs_returns_display_fields(self, client, strata_config):
        """list_ngfw_configs returns display fields for table and dropdown."""
        response = client.get(reverse("mission_control:list_ngfw_configs"))
        data = response.json()
        config = data["configs"][0]

        # Should include fields needed for display (table and dropdown)
        assert "id" in config
        assert "name" in config
        assert "scm_folder_name" in config
        assert "scm_pin_id" in config  # PIN ID is an identifier (like username), safe to display
        assert "created_at" in config
        # PIN value is the actual secret - NEVER expose
        assert "scm_pin_value" not in config

    # --- Create Config ---

    def test_create_config_with_required_fields(self, client, user):
        """create_ngfw_config creates config with required fields."""
        response = client.post(
            reverse("mission_control:create_ngfw_config"),
            data={
                "name": "New Config",
                "scm_folder_name": "New-Folder",
                "scm_pin_id": "new-pin-id",
                "scm_pin_value": "new-pin-value",
            },
            content_type="application/json",
        )
        assert response.status_code == 201
        data = response.json()
        assert data["success"] is True
        assert data["config"]["name"] == "New Config"
        assert data["config"]["scm_folder_name"] == "New-Folder"
        # PIN credentials should NOT be in response
        assert "scm_pin_value" not in data["config"]

    def test_create_config_stores_pin_value_in_db(self, client, user):
        """create_ngfw_config stores scm_pin_value in database (encrypted)."""
        response = client.post(
            reverse("mission_control:create_ngfw_config"),
            data={
                "name": "Config With PIN",
                "scm_folder_name": "PIN-Folder",
                "scm_pin_id": "pin123",
                "scm_pin_value": "my_secret_pin_789",
            },
            content_type="application/json",
        )
        assert response.status_code == 201

        config = StrataConfig.objects.get(name="Config With PIN")
        assert config.scm_pin_value == "my_secret_pin_789"

    def test_create_config_missing_name_fails(self, client):
        """create_ngfw_config fails when name is missing."""
        response = client.post(
            reverse("mission_control:create_ngfw_config"),
            data={
                "scm_folder_name": "folder",
                "scm_pin_id": "pin",
                "scm_pin_value": "value",
            },
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "name" in response.json()["error"].lower()

    def test_create_config_missing_folder_fails(self, client):
        """create_ngfw_config fails when scm_folder_name is missing."""
        response = client.post(
            reverse("mission_control:create_ngfw_config"),
            data={
                "name": "Config",
                "scm_pin_id": "pin",
                "scm_pin_value": "value",
            },
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "folder" in response.json()["error"].lower()

    def test_create_config_missing_pin_id_fails(self, client):
        """create_ngfw_config fails when scm_pin_id is missing."""
        response = client.post(
            reverse("mission_control:create_ngfw_config"),
            data={
                "name": "Config",
                "scm_folder_name": "folder",
                "scm_pin_value": "value",
            },
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "pin id" in response.json()["error"].lower()

    def test_create_config_missing_pin_value_fails(self, client):
        """create_ngfw_config fails when scm_pin_value is missing."""
        response = client.post(
            reverse("mission_control:create_ngfw_config"),
            data={
                "name": "Config",
                "scm_folder_name": "folder",
                "scm_pin_id": "pin",
            },
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "pin value" in response.json()["error"].lower()

    # --- Delete Config ---

    def test_delete_config_soft_deletes(self, client, strata_config):
        """delete_ngfw_config soft-deletes the config."""
        response = client.post(
            reverse("mission_control:delete_ngfw_config", args=[strata_config.id]),
            content_type="application/json",
        )
        assert response.status_code == 200
        assert response.json()["success"] is True

        # Config still exists in DB but has deleted_at set
        config = StrataConfig.objects.get(pk=strata_config.id)
        assert config.deleted_at is not None

    def test_delete_config_not_in_list_after_delete(self, client, strata_config):
        """Deleted config does not appear in list_ngfw_configs."""
        # Delete the config
        client.post(reverse("mission_control:delete_ngfw_config", args=[strata_config.id]))

        # List should be empty
        response = client.get(reverse("mission_control:list_ngfw_configs"))
        data = response.json()
        assert len(data["configs"]) == 0

    def test_delete_other_users_config_fails(self, client, other_user):
        """Cannot delete another user's config."""
        other_config = StrataConfig.objects.create(
            user=other_user,
            name="Other Config",
            scm_folder_name="Other-Folder",
            scm_pin_id="other-pin",
            scm_pin_value="othersecret",
        )

        response = client.post(reverse("mission_control:delete_ngfw_config", args=[other_config.id]))
        assert response.status_code == 404

        # Config should still exist and not be deleted
        other_config.refresh_from_db()
        assert other_config.deleted_at is None

    def test_delete_nonexistent_config_fails(self, client):
        """Deleting nonexistent config returns 404."""
        response = client.post(reverse("mission_control:delete_ngfw_config", args=[99999]))
        assert response.status_code == 404


@pytest.mark.django_db
class TestLaunchRangeWithStrataConfig:
    """Tests for launching ranges with Strata config selection (NGFW)."""

    @pytest.fixture
    def user(self):
        from mission_control.models import OperatingSystem

        OperatingSystem.objects.get_or_create(
            slug="linux-debian", defaults={"name": "Linux (Debian/Ubuntu)", "extensions": ".deb,.tar.gz"}
        )
        return User.objects.create_user(username="test@example.com", email="test@example.com")

    @pytest.fixture
    def other_user(self):
        return User.objects.create_user(username="other@example.com", email="other@example.com")

    @pytest.fixture
    def agent(self, user):
        from mission_control.models import AgentConfig, OperatingSystem

        os_obj = OperatingSystem.objects.get(slug="linux-debian")
        return AgentConfig.objects.create(
            user=user,
            name="Test Agent",
            os=os_obj,
            s3_key="agents/test.tar.gz",
            original_filename="test.tar.gz",
            file_size_bytes=50000000,
            sha256_hash="abc123",
        )

    @pytest.fixture
    def strata_config(self, user):
        return StrataConfig.objects.create(
            user=user,
            name="My SCM Config",
            scm_folder_name="My-Folder",
            scm_pin_id="my-pin-id",
            scm_pin_value="secret123",
        )

    @pytest.fixture
    def other_strata_config(self, other_user):
        return StrataConfig.objects.create(
            user=other_user,
            name="Other SCM Config",
            scm_folder_name="Other-Folder",
            scm_pin_id="other-pin-id",
            scm_pin_value="othersecret",
        )

    @pytest.fixture
    def client(self, user):
        client = Client()
        client.force_login(user)
        return client

    def test_launch_ngfw_enabled_requires_config_id(self, client, agent, settings):
        """Launching with ngfw_enabled=True without ngfw_config_id fails."""
        settings.PROVISIONER_TYPE = "local"

        response = client.post(
            reverse("mission_control:launch_range"),
            data={"agent_id": agent.id, "ngfw_enabled": True},
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "config" in response.json()["error"].lower()

    def test_launch_ngfw_enabled_with_valid_config(self, client, agent, strata_config, settings):
        """Launching with ngfw_enabled=True and valid strata_config_id succeeds."""
        settings.PROVISIONER_TYPE = "local"

        response = client.post(
            reverse("mission_control:launch_range"),
            data={
                "agent_id": agent.id,
                "ngfw_enabled": True,
                "ngfw_config_id": strata_config.id,
            },
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["range"]["ngfw_enabled"] is True

        # Verify the FK was set in DB
        range_obj = Range.objects.get(pk=data["range"]["id"])
        assert range_obj.strata_config == strata_config

    def test_launch_ngfw_enabled_with_invalid_config_id(self, client, agent, settings):
        """Launching with ngfw_enabled=True and nonexistent ngfw_config_id fails."""
        settings.PROVISIONER_TYPE = "local"

        response = client.post(
            reverse("mission_control:launch_range"),
            data={
                "agent_id": agent.id,
                "ngfw_enabled": True,
                "ngfw_config_id": 99999,
            },
            content_type="application/json",
        )
        assert response.status_code == 404
        assert "not found" in response.json()["error"].lower()

    def test_launch_ngfw_enabled_with_other_users_config(self, client, agent, other_strata_config, settings):
        """Cannot launch with another user's strata_config_id."""
        settings.PROVISIONER_TYPE = "local"

        response = client.post(
            reverse("mission_control:launch_range"),
            data={
                "agent_id": agent.id,
                "ngfw_enabled": True,
                "ngfw_config_id": other_strata_config.id,
            },
            content_type="application/json",
        )
        assert response.status_code == 404
        assert "not found" in response.json()["error"].lower()

    def test_launch_ngfw_enabled_with_deleted_config(self, client, agent, strata_config, settings):
        """Cannot launch with a soft-deleted strata_config."""

        settings.PROVISIONER_TYPE = "local"

        # Soft-delete the config
        strata_config.deleted_at = timezone.now()
        strata_config.save()

        response = client.post(
            reverse("mission_control:launch_range"),
            data={
                "agent_id": agent.id,
                "ngfw_enabled": True,
                "ngfw_config_id": strata_config.id,
            },
            content_type="application/json",
        )
        assert response.status_code == 404
        assert "not found" in response.json()["error"].lower()

    def test_launch_ngfw_disabled_no_config_required(self, client, agent, settings):
        """Launching with ngfw_enabled=False does not require ngfw_config_id."""
        settings.PROVISIONER_TYPE = "local"

        response = client.post(
            reverse("mission_control:launch_range"),
            data={
                "agent_id": agent.id,
                "ngfw_enabled": False,
            },
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["range"]["ngfw_enabled"] is False

        # Verify strata_config is None in DB
        range_obj = Range.objects.get(pk=data["range"]["id"])
        assert range_obj.strata_config is None

    def test_launch_ngfw_disabled_ignores_config_id(self, client, agent, strata_config, settings):
        """When ngfw_enabled=False, ngfw_config_id is ignored."""
        settings.PROVISIONER_TYPE = "local"

        response = client.post(
            reverse("mission_control:launch_range"),
            data={
                "agent_id": agent.id,
                "ngfw_enabled": False,
                "ngfw_config_id": strata_config.id,  # Should be ignored
            },
            content_type="application/json",
        )
        assert response.status_code == 200

        # strata_config should NOT be set since ngfw_enabled is False
        range_obj = Range.objects.get(pk=response.json()["range"]["id"])
        assert range_obj.strata_config is None
