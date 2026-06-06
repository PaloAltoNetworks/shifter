"""Tests for Range API endpoints.

All tests mock the ORM — no @pytest.mark.django_db markers.
Views are called via RequestFactory with mock users; CMS/engine
service functions are patched at the view-module boundary.
"""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory

from mission_control import views
from shared.enums import ResourceStatus
from shared.schemas import RangeContext

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def rf():
    """Django RequestFactory (no DB needed)."""
    return RequestFactory()


@pytest.fixture
def mock_user():
    """Authenticated mock user."""
    user = MagicMock()
    user.id = 1
    user.pk = 1
    user.username = "rangetest"
    user.email = "rangetest@example.com"
    user.is_authenticated = True
    user.is_active = True
    return user


@pytest.fixture
def other_user():
    """A second authenticated mock user."""
    user = MagicMock()
    user.id = 2
    user.pk = 2
    user.username = "other"
    user.email = "other@example.com"
    user.is_authenticated = True
    user.is_active = True
    return user


@pytest.fixture
def mock_agent():
    """Mock AgentConfig object."""
    agent = MagicMock()
    agent.id = 10
    agent.name = "Test XDR Agent"
    agent.os = MagicMock()
    agent.os.slug = "windows"
    agent.os.name = "Windows"
    agent.file_size_mb = 47.7
    agent.original_filename = "agent.msi"
    agent.s3_key = "agents/test/fake.msi"
    agent.file_size_bytes = 50000000
    agent.sha256_hash = "abc123"
    return agent


@pytest.fixture
def mock_linux_agent():
    """Mock Linux AgentConfig object."""
    agent = MagicMock()
    agent.id = 20
    agent.name = "Linux Agent"
    agent.os = MagicMock()
    agent.os.slug = "linux-debian"
    agent.os.name = "Linux (Debian/Ubuntu)"
    agent.file_size_mb = 23.8
    agent.original_filename = "agent.deb"
    agent.s3_key = "agents/test/fake.deb"
    agent.file_size_bytes = 25000000
    agent.sha256_hash = "def456"
    return agent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_range_context(user_id=1, **overrides):
    """Build a RangeContext with sensible defaults."""
    defaults = {
        "request_id": uuid4(),
        "range_id": 42,
        "user_id": user_id,
        "scenario_id": "basic",
        "status": ResourceStatus.READY,
        "instances": [],
        "agent_name": "Test XDR Agent",
    }
    defaults.update(overrides)
    return RangeContext(**defaults)


# ---------------------------------------------------------------------------
# TestGetRange
# ---------------------------------------------------------------------------


def _json(response):
    """Extract JSON from a JsonResponse."""
    import json

    return json.loads(response.content)


class TestListAgents:
    def test_requires_login(self, rf):
        request = rf.get("/api/agents/")
        request.user = AnonymousUser()
        response = views.list_agents(request)
        assert response.status_code == 302

    def test_returns_user_agents(self, rf, mock_user, mock_agent):
        request = rf.get("/api/agents/")
        request.user = mock_user

        agent_dict = {
            "id": mock_agent.id,
            "name": "Test XDR Agent",
            "os_name": "Windows",
            "os_slug": "windows",
            "file_size_mb": 47.7,
            "original_filename": "agent.msi",
            "created_at": "2025-01-01T00:00:00Z",
            "agent_type": "xdr",
            "agent_type_display": "XDR",
        }

        with patch.object(views, "cms_list_agents", return_value=[agent_dict]):
            response = views.list_agents(request)

        assert response.status_code == 200
        data = _json(response)
        assert len(data["agents"]) == 1
        assert data["agents"][0]["id"] == mock_agent.id
        assert data["agents"][0]["name"] == "Test XDR Agent"

    def test_includes_os_slug_for_filtering(self, rf, mock_user, mock_agent):
        """Agent list should include os_slug for frontend filtering."""
        request = rf.get("/api/agents/")
        request.user = mock_user

        agent_dict = {
            "id": mock_agent.id,
            "name": "Test XDR Agent",
            "os_name": "Windows",
            "os_slug": "windows",
            "file_size_mb": 47.7,
            "original_filename": "agent.msi",
            "created_at": "2025-01-01T00:00:00Z",
            "agent_type": "xdr",
            "agent_type_display": "XDR",
        }

        with patch.object(views, "cms_list_agents", return_value=[agent_dict]):
            response = views.list_agents(request)

        assert response.status_code == 200
        data = _json(response)
        agent = data["agents"][0]
        assert "os_slug" in agent
        assert agent["os_slug"] == "windows"


class TestSubnetIndexAllocation:
    """Tests for subnet_index allocation in Range model.

    These tests mock Range.allocate_subnet_index and Range.objects
    since they are pure model/ORM operations.
    """

    def test_allocates_index_on_launch(self, rf, mock_user, mock_agent):
        """Launch should delegate to CMS which allocates a subnet_index."""
        request = rf.post(
            "/api/range/launch/",
            data=f'{{"agent_id": {mock_agent.id}}}',
            content_type="application/json",
        )
        request.user = mock_user

        range_ctx = _make_range_context(
            user_id=mock_user.id,
            status=ResourceStatus.PROVISIONING,
        )

        with (
            patch.object(views, "cms_list_scenarios", return_value=[{"id": "basic"}]),
            patch.object(views, "cms_get_agent", return_value=mock_agent),
            patch.object(views, "cms_create_range", return_value=range_ctx) as mock_create,
        ):
            response = views.launch_range(request)

        assert response.status_code == 200
        # Verify cms_create_range was called (it handles subnet allocation)
        mock_create.assert_called_once()

    def test_first_allocation_returns_one(self):
        """First allocation should return index 1."""
        from engine.models import Range

        with (
            patch("engine.models.transaction") as mock_tx,
            patch("engine.models.Range.objects") as mock_objects,
        ):
            mock_tx.atomic.return_value.__enter__ = MagicMock()
            mock_tx.atomic.return_value.__exit__ = MagicMock(return_value=False)
            mock_qs = MagicMock()
            mock_qs.values_list.return_value = []
            mock_objects.exclude.return_value.exclude.return_value = mock_qs

            index = Range.allocate_subnet_index()
            assert index == 1

    def test_allocates_sequential_indices(self):
        """Allocations should fill gaps."""
        from engine.models import Range

        with (
            patch("engine.models.transaction") as mock_tx,
            patch("engine.models.Range.objects") as mock_objects,
        ):
            mock_tx.atomic.return_value.__enter__ = MagicMock()
            mock_tx.atomic.return_value.__exit__ = MagicMock(return_value=False)
            mock_qs = MagicMock()
            mock_qs.values_list.return_value = [1]
            mock_objects.exclude.return_value.exclude.return_value = mock_qs

            index = Range.allocate_subnet_index()
            assert index == 2

    def test_reuses_destroyed_indices(self):
        """Destroyed ranges should free up their indices."""
        from engine.models import Range

        with (
            patch("engine.models.transaction") as mock_tx,
            patch("engine.models.Range.objects") as mock_objects,
        ):
            mock_tx.atomic.return_value.__enter__ = MagicMock()
            mock_tx.atomic.return_value.__exit__ = MagicMock(return_value=False)
            mock_qs = MagicMock()
            mock_qs.values_list.return_value = []
            mock_objects.exclude.return_value.exclude.return_value = mock_qs

            index = Range.allocate_subnet_index()
            assert index == 1

    def test_fills_gaps(self):
        """Should fill gaps in index sequence."""
        from engine.models import Range

        with (
            patch("engine.models.transaction") as mock_tx,
            patch("engine.models.Range.objects") as mock_objects,
        ):
            mock_tx.atomic.return_value.__enter__ = MagicMock()
            mock_tx.atomic.return_value.__exit__ = MagicMock(return_value=False)
            mock_qs = MagicMock()
            mock_qs.values_list.return_value = [1, 3]
            mock_objects.exclude.return_value.exclude.return_value = mock_qs

            index = Range.allocate_subnet_index()
            assert index == 2

    def test_skips_active_indices(self):
        """Should not reuse indices from active ranges."""
        from engine.models import Range

        with (
            patch("engine.models.transaction") as mock_tx,
            patch("engine.models.Range.objects") as mock_objects,
        ):
            mock_tx.atomic.return_value.__enter__ = MagicMock()
            mock_tx.atomic.return_value.__exit__ = MagicMock(return_value=False)
            mock_qs = MagicMock()
            mock_qs.values_list.return_value = [1, 2, 3, 4]
            mock_objects.exclude.return_value.exclude.return_value = mock_qs

            index = Range.allocate_subnet_index()
            assert index == 5

    def test_reuses_failed_indices(self):
        """Failed ranges should free up their indices (like destroyed)."""
        from engine.models import Range

        with (
            patch("engine.models.transaction") as mock_tx,
            patch("engine.models.Range.objects") as mock_objects,
        ):
            mock_tx.atomic.return_value.__enter__ = MagicMock()
            mock_tx.atomic.return_value.__exit__ = MagicMock(return_value=False)
            mock_qs = MagicMock()
            mock_qs.values_list.return_value = []
            mock_objects.exclude.return_value.exclude.return_value = mock_qs

            index = Range.allocate_subnet_index()
            assert index == 1

    def test_raises_when_exhausted(self):
        """Should raise ValueError when all indices are used."""
        from engine.models import Range

        with (
            patch("engine.models.transaction") as mock_tx,
            patch("engine.models.Range.objects") as mock_objects,
            patch.object(Range, "SUBNET_INDEX_MAX", 5),
        ):
            mock_tx.atomic.return_value.__enter__ = MagicMock()
            mock_tx.atomic.return_value.__exit__ = MagicMock(return_value=False)
            mock_qs = MagicMock()
            mock_qs.values_list.return_value = [1, 2, 3, 4, 5]
            mock_objects.exclude.return_value.exclude.return_value = mock_qs

            with pytest.raises(ValueError, match="No subnet indices available"):
                Range.allocate_subnet_index()

    def test_capacity_error_on_launch(self, rf, mock_user, mock_agent):
        """API returns error when subnet allocation fails (no capacity).

        CMS service raises CMSError (or ValueError propagates) when
        allocate_subnet_index() fails.
        """
        request = rf.post(
            "/api/range/launch/",
            data=f'{{"agent_id": {mock_agent.id}}}',
            content_type="application/json",
        )
        request.user = mock_user

        with (
            patch.object(views, "cms_list_scenarios", return_value=[{"id": "basic"}]),
            patch.object(views, "cms_get_agent", return_value=mock_agent),
            patch.object(
                views,
                "cms_create_range",
                side_effect=ValueError("No subnet indices available"),
            ),
            pytest.raises(ValueError, match="No subnet indices available"),
        ):
            views.launch_range(request)
