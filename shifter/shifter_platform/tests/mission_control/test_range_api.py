"""Tests for Range API endpoints."""

from unittest.mock import patch

import pytest
from django.urls import reverse

from cms.models import AgentConfig, OperatingSystem
from engine.models import Range


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
        patch("engine.ecs.start_provisioning") as mock_provision,
        patch("engine.ecs.start_teardown") as mock_teardown,
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
        mock_path = "engine.ecs._get_ecs_client"
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
