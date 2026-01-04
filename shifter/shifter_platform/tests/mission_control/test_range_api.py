"""Tests for Range API endpoints."""

from unittest.mock import patch

import pytest
from django.urls import reverse

from cms.models import AgentConfig, OperatingSystem
from engine.models import Range
from shared.enums import RangeStatus
from shared.schemas import RangeContext


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
class TestGetRange:
    """Tests for get_range view.

    The view now consumes RangeContext from cms.get_active_range().
    Tests mock the CMS service layer to return RangeContext projections.
    """

    def test_requires_login(self, client):
        response = client.get(reverse("mission_control:get_range"))
        assert response.status_code == 302  # Redirect to login

    def test_returns_no_range_when_none_exists(self, client, test_agent):
        client.force_login(test_agent.user)

        with patch("mission_control.views.get_active_range", return_value=None):
            response = client.get(reverse("mission_control:get_range"))

        assert response.status_code == 200
        data = response.json()
        assert data["has_range"] is False
        assert data["range"] is None

    def test_returns_active_range(self, client, test_agent):
        client.force_login(test_agent.user)

        # Create a RangeContext projection (what CMS service returns)
        mock_range_context = RangeContext(
            range_id=42,
            user_id=test_agent.user.id,
            scenario_id="basic",
            status=RangeStatus.READY,
            instances=[],
            agent_name="Test XDR Agent",
        )

        with patch(
            "mission_control.views.get_active_range",
            return_value=mock_range_context,
        ):
            response = client.get(reverse("mission_control:get_range"))

        assert response.status_code == 200
        data = response.json()
        assert data["has_range"] is True
        assert data["range"]["range_id"] == 42
        assert data["range"]["status"] == "ready"
        assert data["range"]["agent_name"] == "Test XDR Agent"
        assert data["range"]["scenario_id"] == "basic"
        # Computed properties are included in model_dump
        assert data["range"]["is_ready"] is True
        assert data["range"]["is_terminal"] is False
        assert data["range"]["is_active"] is True

    def test_returns_provisioning_range(self, client, test_agent):
        """Test range in provisioning state has correct computed properties."""
        client.force_login(test_agent.user)

        mock_range_context = RangeContext(
            range_id=42,
            user_id=test_agent.user.id,
            scenario_id="basic",
            status=RangeStatus.PROVISIONING,
            instances=[],
            agent_name="Test Agent",
        )

        with patch(
            "mission_control.views.get_active_range",
            return_value=mock_range_context,
        ):
            response = client.get(reverse("mission_control:get_range"))

        assert response.status_code == 200
        data = response.json()
        assert data["has_range"] is True
        assert data["range"]["status"] == "provisioning"
        assert data["range"]["is_ready"] is False
        assert data["range"]["is_terminal"] is False
        assert data["range"]["is_active"] is True

    def test_returns_destroying_range(self, client, test_agent):
        """Test range in destroying state has correct computed properties."""
        client.force_login(test_agent.user)

        mock_range_context = RangeContext(
            range_id=42,
            user_id=test_agent.user.id,
            scenario_id="basic",
            status=RangeStatus.DESTROYING,
            instances=[],
            agent_name="Test Agent",
        )

        with patch(
            "mission_control.views.get_active_range",
            return_value=mock_range_context,
        ):
            response = client.get(reverse("mission_control:get_range"))

        assert response.status_code == 200
        data = response.json()
        assert data["has_range"] is True
        assert data["range"]["status"] == "destroying"
        assert data["range"]["is_ready"] is False
        assert data["range"]["is_terminal"] is False
        assert data["range"]["is_active"] is True


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
        # CMS returns 400 (CMSError) for agent not found, not 404
        assert response.status_code == 400

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
        assert data["range"]["agent_name"] == test_agent.name

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
                range_obj = Range.objects.get(id=data["range"]["range_id"])
                assert range_obj.step_function_execution_arn == task_arn
            finally:
                settings.PULUMI_ECS_CLUSTER_ARN = orig_cluster
                settings.PULUMI_TASK_DEFINITION_ARN = orig_task_def
                settings.PULUMI_ECS_SECURITY_GROUP_ID = orig_sg
                settings.PULUMI_PRIVATE_SUBNET_IDS = orig_subnets

    def test_rejects_when_range_exists(self, client, test_agent, settings):
        from cms.models import RangeInstance

        settings.PULUMI_ECS_CLUSTER_ARN = ""
        client.force_login(test_agent.user)

        # Create existing range (both Engine Range and CMS RangeInstance)
        range_obj = Range.objects.create(
            user=test_agent.user,
            status=Range.Status.READY,
        )
        # CMS tracks ranges via RangeInstance - get_active_range queries this
        RangeInstance.objects.create(
            range_id=range_obj.id,
            user_id=test_agent.user.id,
            scenario_id="basic",
            agent=test_agent,
            status="ready",
        )

        response = client.post(
            reverse("mission_control:launch_range"),
            data={"agent_id": test_agent.id},
            content_type="application/json",
        )

        # CMS returns 400 for "already have active range" (CMSError)
        assert response.status_code == 400
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
        assert data["range"]["scenario_id"] == "ad_attack_lab"

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
        assert data["range"]["scenario_id"] == "basic"


@pytest.mark.django_db
class TestCancelRange:
    """Tests for cancel_range view.

    The view now requires range_id in the request body and delegates to
    cms.cancel_range() which updates status to DESTROYED and calls engine.
    """

    def test_requires_login(self, client):
        response = client.post(reverse("mission_control:cancel_range"))
        assert response.status_code == 302

    def test_requires_range_id_in_body(self, client, test_agent):
        """Request must include range_id in JSON body."""
        client.force_login(test_agent.user)
        response = client.post(
            reverse("mission_control:cancel_range"),
            data={},
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "range_id" in response.json()["error"]

    def test_returns_error_when_range_not_found(self, client, test_agent):
        """Returns error when range_id doesn't exist."""
        client.force_login(test_agent.user)
        response = client.post(
            reverse("mission_control:cancel_range"),
            data={"range_id": 99999},
            content_type="application/json",
        )
        assert response.status_code == 400
        # CMS returns CMSError which is converted to 400

    def test_successful_cancel(self, client, test_agent):
        """Successfully cancels a range by setting status to DESTROYED."""
        from cms.models import RangeInstance

        client.force_login(test_agent.user)

        # Create a provisioning range (both Engine Range and CMS RangeInstance)
        range_obj = Range.objects.create(
            user=test_agent.user,
            status=Range.Status.PROVISIONING,
        )
        RangeInstance.objects.create(
            range_id=range_obj.id,
            user_id=test_agent.user.id,
            scenario_id="basic",
            agent=test_agent,
            status="provisioning",
        )

        # Mock engine cancel to avoid AWS calls
        with patch("cms.services.engine_cancel_range") as mock_engine:
            response = client.post(
                reverse("mission_control:cancel_range"),
                data={"range_id": range_obj.id},
                content_type="application/json",
            )
            assert response.status_code == 200
            assert response.json()["success"] is True

            # Verify engine was called with RangeContext
            mock_engine.assert_called_once()
            call_arg = mock_engine.call_args[0][0]
            assert call_arg.range_id == range_obj.id

    def test_cancel_sets_status_to_destroyed(self, client, test_agent):
        """Cancel updates CMS status to DESTROYED before calling engine."""
        from cms.models import RangeInstance

        client.force_login(test_agent.user)

        range_obj = Range.objects.create(
            user=test_agent.user,
            status=Range.Status.PROVISIONING,
        )
        RangeInstance.objects.create(
            range_id=range_obj.id,
            user_id=test_agent.user.id,
            scenario_id="basic",
            agent=test_agent,
            status="provisioning",
        )

        with patch("cms.services.engine_cancel_range"):
            client.post(
                reverse("mission_control:cancel_range"),
                data={"range_id": range_obj.id},
                content_type="application/json",
            )

        # Verify CMS RangeInstance was updated (via model invariant)
        ri = RangeInstance.objects.get(range_id=range_obj.id)
        assert ri.status == "destroyed"
        assert ri.deleted_at is not None  # Terminal status invariant

    def test_cannot_cancel_other_users_range(self, client, test_agent, django_user_model):
        """Users cannot cancel ranges they don't own."""
        from cms.models import RangeInstance

        other_user = django_user_model.objects.create_user(
            username="other", email="other@example.com", password="testpass"
        )
        client.force_login(other_user)

        # Create range owned by test_agent.user (both Engine Range and CMS RangeInstance)
        range_obj = Range.objects.create(
            user=test_agent.user,
            status=Range.Status.PROVISIONING,
        )
        RangeInstance.objects.create(
            range_id=range_obj.id,
            user_id=test_agent.user.id,
            scenario_id="basic",
            agent=test_agent,
            status="provisioning",
        )

        response = client.post(
            reverse("mission_control:cancel_range"),
            data={"range_id": range_obj.id},
            content_type="application/json",
        )
        assert response.status_code == 400  # CMSError for not found/not owned


@pytest.mark.django_db
class TestDestroyRange:
    def test_requires_login(self, client):
        response = client.post(reverse("mission_control:destroy_range"))
        assert response.status_code == 302

    def test_returns_404_when_no_range(self, client, test_agent):
        client.force_login(test_agent.user)
        response = client.post(
            reverse("mission_control:destroy_range"),
            data={"range_id": 99999},
            content_type="application/json",
        )
        # CMS returns 400 (CMSError) for range not found, not 404
        assert response.status_code == 400

    def test_successful_destroy(self, client, test_agent, settings):
        from cms.models import RangeInstance

        settings.PULUMI_ECS_CLUSTER_ARN = ""
        client.force_login(test_agent.user)

        # Create a ready range (both Engine Range and CMS RangeInstance)
        range_obj = Range.objects.create(
            user=test_agent.user,
            status=Range.Status.READY,
        )
        RangeInstance.objects.create(
            range_id=range_obj.id,
            user_id=test_agent.user.id,
            scenario_id="basic",
            agent=test_agent,
            status="ready",
        )

        response = client.post(
            reverse("mission_control:destroy_range"),
            data={"range_id": range_obj.id},
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        # Verify range was marked as DESTROYING (async cleanup will set DESTROYED)
        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.DESTROYING

    def test_can_destroy_failed_range(self, client, test_agent, settings):
        """Failed ranges can be destroyed to clean up."""
        from cms.models import RangeInstance

        settings.PULUMI_ECS_CLUSTER_ARN = ""
        client.force_login(test_agent.user)

        # Create a failed range (both Engine Range and CMS RangeInstance)
        range_obj = Range.objects.create(
            user=test_agent.user,
            status=Range.Status.FAILED,
            error_message="Provisioning timed out",
        )
        RangeInstance.objects.create(
            range_id=range_obj.id,
            user_id=test_agent.user.id,
            scenario_id="basic",
            agent=test_agent,
            status="failed",
        )

        response = client.post(
            reverse("mission_control:destroy_range"),
            data={"range_id": range_obj.id},
            content_type="application/json",
        )
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
        range_obj = Range.objects.get(id=response.json()["range"]["range_id"])
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
            status=Range.Status.READY,
            subnet_index=1,
        )
        Range.objects.create(
            user=test_agent.user,
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
                status=Range.Status.READY,
                subnet_index=i,
            )

        with pytest.raises(ValueError, match="No subnet indices available"):
            Range.allocate_subnet_index()

    def test_capacity_error_raises_value_error(self, client, test_agent, settings, django_user_model):
        """API raises ValueError when subnet allocation fails (no capacity).

        Note: This currently raises an uncaught ValueError because the error
        from allocate_subnet_index() isn't caught and converted to a user-friendly
        response. A future improvement would be to catch this and return 503
        with a proper error message.
        """
        settings.PULUMI_ECS_CLUSTER_ARN = ""
        client.force_login(test_agent.user)

        # Create a different user to hold the 254 ranges (so test_agent.user has no active range)
        other_user = django_user_model.objects.create_user(
            username="capacitytest",
            email="capacitytest@example.com",
            password="testpass",
        )

        # Create ranges for all 254 indices (owned by other_user, all READY so they block)
        for i in range(1, 255):
            Range.objects.create(
                user=other_user,
                status=Range.Status.READY,
                subnet_index=i,
            )

        # Django test client propagates uncaught exceptions
        with pytest.raises(ValueError, match="No subnet indices available"):
            client.post(
                reverse("mission_control:launch_range"),
                data={"agent_id": test_agent.id},
                content_type="application/json",
            )
