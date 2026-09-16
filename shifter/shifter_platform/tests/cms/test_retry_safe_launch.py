"""Retry-safe range launch orchestration (#2086, ADR-063-R1/R2/R3).

``resolve_retry_recovery`` recovers a bound operation for a replay without minting
or catalog validation; ``bind_first_use_launch`` dispatches + binds on first use. A
replay with the same caller intent recovers the original operation; a different
caller intent conflicts before effects. The heavy RAES create path is mocked.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model

from cms.services import RetryKeyConflict, bind_first_use_launch, resolve_retry_recovery
from engine.models import PublicOperationRetryBinding

pytestmark = pytest.mark.django_db
User = get_user_model()

SELECTION = {"agent_id": 5}


class _FakeCtx:
    def __init__(self, request_id):
        self.request_id = request_id


@pytest.fixture
def actor(db):
    return User.objects.create_user(username="launcher@example.com", email="launcher@example.com")


def _patch_mint(monkeypatch, *, calls):
    def _dispatch(user, scenario, workspace_uuid=None):
        # RAES packages own topology post-PLAT-202; create_range_dispatch no
        # longer takes agents_by_os (see cms.services._retry_safe_launch).
        calls.append(scenario)
        return _FakeCtx(uuid4())

    monkeypatch.setattr("cms.services._retry_safe_launch.create_range_dispatch", _dispatch)
    monkeypatch.setattr("cms.services._retry_safe_launch.operation_id_for_request", lambda request_id: str(uuid4()))


def _bind(actor, scenario, caller_key):
    return bind_first_use_launch(
        actor,
        scenario=scenario,
        agents_selection=SELECTION,
        agents_by_os={"linux": 5},
        workspace_uuid=None,
        caller_key=caller_key,
    )


def test_unbound_key_has_no_recovery(actor, monkeypatch):
    calls: list = []
    _patch_mint(monkeypatch, calls=calls)
    assert (
        resolve_retry_recovery(
            actor, scenario="basic", agents_selection=SELECTION, workspace_uuid=None, caller_key="k1"
        )
        is None
    )
    assert calls == []


def test_first_use_dispatches_and_binds(actor, monkeypatch):
    calls: list = []
    _patch_mint(monkeypatch, calls=calls)
    outcome = _bind(actor, "basic", "k1")
    assert outcome.created is True
    assert calls == ["basic"]
    assert PublicOperationRetryBinding.objects.filter(actor_key=str(actor.id), caller_key="k1").count() == 1


def test_replay_same_intent_recovers_without_redispatch(actor, monkeypatch):
    calls: list = []
    _patch_mint(monkeypatch, calls=calls)
    first = _bind(actor, "basic", "k1")

    recovered = resolve_retry_recovery(
        actor, scenario="basic", agents_selection=SELECTION, workspace_uuid=None, caller_key="k1"
    )

    assert recovered is not None
    assert recovered.created is False
    assert recovered.request_id == first.request_id
    assert calls == ["basic"]  # dispatched exactly once


def test_replay_different_intent_conflicts_without_dispatch(actor, monkeypatch):
    calls: list = []
    _patch_mint(monkeypatch, calls=calls)
    _bind(actor, "basic", "k1")

    with pytest.raises(RetryKeyConflict):
        resolve_retry_recovery(
            actor, scenario="advanced", agents_selection=SELECTION, workspace_uuid=None, caller_key="k1"
        )

    assert calls == ["basic"]


def test_distinct_actors_do_not_share_a_key(actor, monkeypatch):
    other = User.objects.create_user(username="other@example.com", email="other@example.com")
    calls: list = []
    _patch_mint(monkeypatch, calls=calls)

    a = _bind(actor, "basic", "k1")
    b = _bind(other, "basic", "k1")

    assert a.created is True
    assert b.created is True
    assert a.request_id != b.request_id
