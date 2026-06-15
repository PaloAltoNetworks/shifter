"""Behavior tests for the agent-list API and Range subnet-index allocation.

Drives the real ``/api/agents/`` endpoint with database-backed agents and
exercises ``Range.allocate_subnet_index`` against real ``Range`` rows instead
of mocking the ORM/transaction. ``SUBNET_INDEX_MAX`` is lowered with pytest's
``monkeypatch`` (a plain attribute set, not a ``mock.patch`` of call topology)
so the exhaustion path is reachable without creating thousands of rows.
"""

import json

import pytest
from django.test import Client
from django.urls import reverse

from engine.models import Range

pytestmark = pytest.mark.django_db


def _json(response):
    return json.loads(response.content)


class TestListAgents:
    def test_requires_login(self):
        response = Client().get(reverse("mission_control:list_agents"))
        assert response.status_code == 302

    def test_returns_user_agents(self, authenticated_client, make_agent):
        client, user = authenticated_client(email="agents@example.com")
        make_agent(user, name="Test XDR Agent")

        response = client.get(reverse("mission_control:list_agents"))
        assert response.status_code == 200
        agents = _json(response)["agents"]
        assert len(agents) == 1
        assert agents[0]["name"] == "Test XDR Agent"

    def test_includes_os_slug_for_filtering(self, authenticated_client, make_agent, windows_os):
        client, user = authenticated_client(email="osslug@example.com")
        make_agent(user, os=windows_os)

        response = client.get(reverse("mission_control:list_agents"))
        assert response.status_code == 200
        agent = _json(response)["agents"][0]
        assert agent["os_slug"] == "windows"

    def test_only_returns_own_agents(self, authenticated_client, make_agent):
        owner_client, owner = authenticated_client(email="owner-a@example.com")
        make_agent(owner, name="Owned")
        _other_client, other = authenticated_client(email="other-a@example.com")
        make_agent(other, name="Someone Else")

        response = owner_client.get(reverse("mission_control:list_agents"))
        names = [a["name"] for a in _json(response)["agents"]]
        assert names == ["Owned"]


class TestSubnetIndexAllocation:
    """Exercises Range.allocate_subnet_index against real rows."""

    @pytest.fixture
    def user(self, django_user_model):
        return django_user_model.objects.create_user(username="subnet@example.com", email="subnet@example.com")

    def _range(self, user, *, subnet_index, status=Range.Status.READY):
        return Range.objects.create(user=user, subnet_index=subnet_index, status=status)

    def test_first_allocation_returns_one(self, user):
        assert Range.allocate_subnet_index() == 1

    def test_allocates_next_after_existing(self, user):
        self._range(user, subnet_index=1)
        assert Range.allocate_subnet_index() == 2

    def test_fills_gaps(self, user):
        self._range(user, subnet_index=1)
        self._range(user, subnet_index=3)
        assert Range.allocate_subnet_index() == 2

    def test_skips_active_indices(self, user):
        for i in (1, 2, 3, 4):
            self._range(user, subnet_index=i)
        assert Range.allocate_subnet_index() == 5

    def test_reuses_destroyed_indices(self, user):
        self._range(user, subnet_index=1, status=Range.Status.DESTROYED)
        assert Range.allocate_subnet_index() == 1

    def test_reuses_failed_indices(self, user):
        self._range(user, subnet_index=1, status=Range.Status.FAILED)
        assert Range.allocate_subnet_index() == 1

    def test_raises_when_exhausted(self, user, monkeypatch):
        monkeypatch.setattr(Range, "SUBNET_INDEX_MAX", 3)
        for i in (1, 2, 3):
            self._range(user, subnet_index=i)
        with pytest.raises(ValueError, match="No subnet indices available"):
            Range.allocate_subnet_index()


class TestLaunchAllocatesSubnetIndex:
    def test_launched_range_has_subnet_index(self, authenticated_client, launch_range_via_api):
        client, user = authenticated_client(email="launchidx@example.com")
        response, _agent, _scenario = launch_range_via_api(client, user)
        assert response.status_code == 200

        range_obj = Range.objects.get()
        assert range_obj.subnet_index is not None
        assert range_obj.subnet_index >= Range.SUBNET_INDEX_MIN
