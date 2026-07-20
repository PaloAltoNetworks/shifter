"""Behavior tests for the agent list/upload page and agent deletion.

Drives the real ``mission_control:agents`` and ``mission_control:delete_agent``
URLs with database-backed agents. Auth/ownership rejections run entirely
first-party; the successful-delete path removes the S3 object first, so it
mocks the AWS SDK (a real cloud boundary) and sets a bucket name via
``override_settings`` rather than patching first-party services.
"""

from unittest.mock import patch

import pytest
from django.test import Client, override_settings
from django.urls import reverse

from cms.models import AgentConfig

pytestmark = pytest.mark.django_db

AGENTS_URL = reverse("mission_control:agents")


def _delete_url(agent_id):
    return reverse("mission_control:delete_agent", args=[agent_id])


class TestAgentsView:
    def test_requires_login(self):
        assert Client().get(AGENTS_URL).status_code == 302

    def test_shows_user_agents(self, authenticated_client, make_agent):
        client, user = authenticated_client(email="agentlist@example.com")
        make_agent(user, name="Acme Sensor")

        response = client.get(AGENTS_URL)
        assert response.status_code == 200
        assert b"Acme Sensor" in response.content

    def test_shows_empty_state(self, authenticated_client):
        client, _user = authenticated_client(email="noagents@example.com")
        response = client.get(AGENTS_URL)
        assert response.status_code == 200

    def test_does_not_show_other_users_agents(self, authenticated_client, make_agent):
        viewer_client, _viewer = authenticated_client(email="viewer@example.com")
        _other_client, other = authenticated_client(email="agentowner@example.com")
        make_agent(other, name="Private Sensor")

        response = viewer_client.get(AGENTS_URL)
        assert response.status_code == 200
        assert b"Private Sensor" not in response.content


class TestDeleteAgent:
    def test_requires_login(self, make_agent, authenticated_client):
        _client, user = authenticated_client(email="delowner@example.com")
        agent = make_agent(user)
        assert Client().post(_delete_url(agent.id)).status_code == 302

    def test_requires_post(self, authenticated_client, make_agent):
        client, user = authenticated_client(email="delget@example.com")
        agent = make_agent(user)
        assert client.get(_delete_url(agent.id)).status_code == 405

    @override_settings(AWS_S3_BUCKET_NAME="test-bucket")
    def test_successful_delete(self, authenticated_client, make_agent):
        client, user = authenticated_client(email="delok@example.com")
        agent = make_agent(user)

        with patch("boto3.client"):  # cloud boundary: S3 object removal is a no-op
            response = client.post(_delete_url(agent.id))

        assert response.status_code == 302
        assert response.url == AGENTS_URL
        # Soft-deleted: hidden from the default manager.
        assert not AgentConfig.objects.filter(id=agent.id).exists()

    def test_cannot_delete_other_users_agent(self, authenticated_client, make_agent):
        client, _user = authenticated_client(email="attacker@example.com")
        _owner_client, owner = authenticated_client(email="victim@example.com")
        agent = make_agent(owner)

        response = client.post(_delete_url(agent.id), follow=True)
        assert response.status_code == 200
        assert any(
            "not found" in str(m).lower() or "permission" in str(m).lower() for m in response.context["messages"]
        )
        # The agent is untouched.
        assert AgentConfig.objects.filter(id=agent.id).exists()

    def test_delete_nonexistent_agent(self, authenticated_client):
        client, _user = authenticated_client(email="delghost@example.com")
        response = client.post(_delete_url(999999))
        assert response.status_code == 302
        assert response.url == AGENTS_URL
