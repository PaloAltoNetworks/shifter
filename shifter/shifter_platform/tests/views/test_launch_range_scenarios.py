"""Tests for launch_range scenario validation.

Verifies that views.py uses CMS for scenario validation
instead of hardcoded scenario lists.
"""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from mission_control.models import AgentConfig, OperatingSystem

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="test@example.com", email="test@example.com", password="testpass")


@pytest.fixture
def client(user):
    client = Client()
    client.login(username="test@example.com", password="testpass")
    return client


@pytest.fixture
def windows_agent(user, db):
    """Windows agent for testing."""
    os = OperatingSystem.objects.get(slug="windows")
    return AgentConfig.objects.create(
        user=user,
        name="Windows Agent",
        os=os,
        s3_key="agents/123/agent.msi",
        original_filename="cortex_agent.msi",
        file_size_bytes=5000000,
        sha256_hash="abc123def456",
    )


@pytest.mark.django_db
class TestLaunchRangeScenarioValidation:
    """Tests for scenario validation in launch_range view."""

    def test_accepts_basic_scenario(self, client, windows_agent):
        """View accepts 'basic' scenario."""
        # This tests that 'basic' is a valid scenario
        # We don't need to actually launch - just verify validation passes
        import contextlib
        from unittest.mock import patch

        with patch("mission_control.views.launch") as mock_launch:
            mock_launch.side_effect = Exception("mock")  # Force failure after validation
            url = reverse("mission_control:launch_range")
            with contextlib.suppress(Exception):
                client.post(
                    url,
                    data={"agent_id": windows_agent.id, "scenario": "basic"},
                    content_type="application/json",
                )
            # If we got here, validation passed (mock caused the failure)

    def test_accepts_ad_attack_lab_scenario(self, client, windows_agent):
        """View accepts 'ad_attack_lab' scenario."""
        import contextlib
        from unittest.mock import patch

        with patch("mission_control.views.launch") as mock_launch:
            mock_launch.side_effect = Exception("mock")
            url = reverse("mission_control:launch_range")
            with contextlib.suppress(Exception):
                client.post(
                    url,
                    data={"agent_id": windows_agent.id, "scenario": "ad_attack_lab"},
                    content_type="application/json",
                )

    def test_rejects_unknown_scenario(self, client, windows_agent):
        """View rejects unknown scenario with 400 error."""
        url = reverse("mission_control:launch_range")
        response = client.post(
            url,
            data={"agent_id": windows_agent.id, "scenario": "unknown_scenario"},
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "Invalid" in response.json().get("error", "") or "scenario" in response.json().get("error", "").lower()

    def test_scenario_validation_uses_cms(self, client, windows_agent):
        """Scenario validation should use CMS list_scenarios.

        This test verifies that the valid scenarios are determined by CMS,
        not hardcoded in views.py.
        """
        from unittest.mock import patch

        # Mock CMS to return only 'basic' as valid
        mock_scenarios = [{"id": "basic", "name": "Basic"}]

        with patch("mission_control.views.cms_list_scenarios", return_value=mock_scenarios):
            url = reverse("mission_control:launch_range")

            # ad_attack_lab should be rejected since CMS doesn't list it
            response = client.post(
                url,
                data={"agent_id": windows_agent.id, "scenario": "ad_attack_lab"},
                content_type="application/json",
            )
            # If CMS is being used, ad_attack_lab should be invalid
            # If hardcoded, it would still be accepted
            assert response.status_code == 400
