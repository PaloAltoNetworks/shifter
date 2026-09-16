"""API-level retry-safe launch behavior (#2086, ADR-063).

Drives the real launch endpoint with an ``Idempotency-Key`` header: a replay with
the same key + selections recovers the original range without a duplicate; a
replay with different selections conflicts (409); an oversized key is rejected.
"""

from __future__ import annotations

import json

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def _launch(client, agent_id, scenario, key=None):
    extra = {"HTTP_IDEMPOTENCY_KEY": key} if key is not None else {}
    return client.post(
        reverse("v1:mission_control:range-launch"),
        data=json.dumps({"agent_id": agent_id, "scenario": scenario}),
        content_type="application/json",
        **extra,
    )


def test_replay_same_key_recovers_without_duplicate(authenticated_client, make_agent, hydratable_scenario):
    from engine.models import PublicOperationRetryBinding

    client, user = authenticated_client(email="retry-api@example.com")
    agent = make_agent(user)
    scenario = hydratable_scenario.scenario_id

    first = _launch(client, agent.id, scenario, key="idem-1")
    assert first.status_code == 200, first.content
    assert first.json().get("recovered") is False

    second = _launch(client, agent.id, scenario, key="idem-1")
    assert second.status_code == 200, second.content
    assert second.json().get("recovered") is True
    # The replay must recover the ORIGINAL bound range, not a re-projected null or
    # a different active range (guards the _bound_range_response recovery path).
    assert second.json()["range"] is not None
    assert second.json()["range"]["request_id"] == first.json()["range"]["request_id"]

    assert PublicOperationRetryBinding.objects.filter(actor_key=str(user.id)).count() == 1


def test_same_key_different_selection_conflicts(authenticated_client, make_agent, hydratable_scenario):
    client, user = authenticated_client(email="retry-conflict@example.com")
    agent_one = make_agent(user)
    agent_two = make_agent(user)
    scenario = hydratable_scenario.scenario_id

    first = _launch(client, agent_one.id, scenario, key="idem-2")
    assert first.status_code == 200, first.content

    conflict = _launch(client, agent_two.id, scenario, key="idem-2")
    assert conflict.status_code == 409, conflict.content


def test_oversized_key_rejected(authenticated_client, make_agent, hydratable_scenario):
    client, user = authenticated_client(email="retry-oversized@example.com")
    agent = make_agent(user)
    scenario = hydratable_scenario.scenario_id

    response = _launch(client, agent.id, scenario, key="x" * 201)
    assert response.status_code == 400, response.content


def test_launch_without_key_is_unchanged(authenticated_client, make_agent, hydratable_scenario):
    from engine.models import PublicOperationRetryBinding

    client, user = authenticated_client(email="retry-none@example.com")
    agent = make_agent(user)
    scenario = hydratable_scenario.scenario_id

    response = _launch(client, agent.id, scenario, key=None)
    assert response.status_code == 200, response.content
    assert "recovered" not in response.json()
    assert PublicOperationRetryBinding.objects.count() == 0


def test_first_use_key_conflict_returns_409(authenticated_client, make_agent, hydratable_scenario, monkeypatch):
    """A concurrent contender winning the key at first-use dispatch maps to 409.

    ``bind_first_use_launch`` raises ``RetryKeyConflict`` when the loser reads the
    winner's differing intent after the unique-key race; the view must translate
    that into the ``retry_key_conflict`` 409 without leaving a binding behind.
    """
    from cms.services import RetryKeyConflict
    from engine.models import PublicOperationRetryBinding

    def _raise(*_args, **_kwargs):
        raise RetryKeyConflict("retry key is already bound to a different operation intent")

    monkeypatch.setattr("mission_control.api._retry_launch.bind_first_use_launch", _raise)
    client, user = authenticated_client(email="retry-firstuse-conflict@example.com")
    agent = make_agent(user)

    response = _launch(client, agent.id, hydratable_scenario.scenario_id, key="race-first-use")

    assert response.status_code == 409, response.content
    assert PublicOperationRetryBinding.objects.count() == 0


def test_first_use_cms_error_maps_to_launch_failure(authenticated_client, make_agent, hydratable_scenario, monkeypatch):
    """A CMS failure during first-use dispatch routes through ``_launch_failure_response``.

    A generic ``CMSError`` from ``bind_first_use_launch`` is a bad request (400),
    and no retry binding is persisted for the failed dispatch.
    """
    from engine.models import PublicOperationRetryBinding
    from shared.exceptions import CMSError

    def _raise(*_args, **_kwargs):
        raise CMSError("catalog validation failed")

    monkeypatch.setattr("mission_control.api._retry_launch.bind_first_use_launch", _raise)
    client, user = authenticated_client(email="retry-firstuse-cms@example.com")
    agent = make_agent(user)

    response = _launch(client, agent.id, hydratable_scenario.scenario_id, key="first-use-cms")

    assert response.status_code == 400, response.content
    assert PublicOperationRetryBinding.objects.count() == 0


def test_agents_selection_normalizes_agents_dict():
    """The agents-map selection is projected with string keys, int values, sorted."""
    from mission_control.api._retry_launch import RetrySafeLaunchMixin

    selection = RetrySafeLaunchMixin._agents_selection({"agents": {"windows": 1, "linux": "2"}})

    assert selection == {"agents": {"linux": 2, "windows": 1}}


def test_bound_range_response_falls_back_to_null_range_on_cms_error(monkeypatch):
    """When the bound range cannot be projected, the payload carries ``range=None``.

    ``get_range_by_request_id`` raising ``CMSError`` (e.g. a terminal/absent bound
    range) must not fail the response; it degrades to a null range while still
    reporting success and the recovered flag.
    """
    from types import SimpleNamespace
    from uuid import uuid4

    from mission_control.api._retry_launch import RetrySafeLaunchMixin
    from shared.exceptions import CMSError

    def _raise(*_args, **_kwargs):
        raise CMSError("bound range no longer projectable")

    monkeypatch.setattr("mission_control.api._retry_launch.get_range_by_request_id", _raise)
    outcome = SimpleNamespace(request_id=str(uuid4()))

    response = RetrySafeLaunchMixin._bound_range_response(None, outcome, recovered=True)

    assert response.data["success"] is True
    assert response.data["recovered"] is True
    assert response.data["range"] is None
