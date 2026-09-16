"""Behavioral tests for the public-operation retry binding (#2086, ADR-063-R1/R2).

First use mints and binds; a same-intent replay recovers the original operation
without re-minting; a different-intent replay conflicts before any effect. The
real concurrency proofs live in ``test_retry_binding_postgres.py``.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from engine.models import PublicOperationRetryBinding, RetryBindingStatus
from engine.retry_binding import (
    MintedOperation,
    RetryKeyConflict,
    bind_public_operation,
    lookup_public_operation,
)

pytestmark = pytest.mark.django_db

DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
KEY = {
    "deployment_scope": "proj-x",
    "actor_key": "7",
    "action": "raes-range:provision",
    "caller_key": "k-1",
}


def _mint() -> MintedOperation:
    return MintedOperation(request_id=str(uuid4()), operation_id=str(uuid4()))


def test_first_use_mints_and_binds():
    calls: list[int] = []

    def mint() -> MintedOperation:
        calls.append(1)
        return _mint()

    result = bind_public_operation(**KEY, intent_digest=DIGEST_A, mint=mint)

    assert result.created is True
    assert len(calls) == 1
    assert result.binding.intent_digest == DIGEST_A
    assert result.binding.status == RetryBindingStatus.ACTIVE
    assert PublicOperationRetryBinding.objects.filter(**KEY).count() == 1


def test_replay_same_intent_recovers_without_reminting():
    first = bind_public_operation(**KEY, intent_digest=DIGEST_A, mint=_mint)
    calls: list[int] = []

    def mint() -> MintedOperation:
        calls.append(1)
        return _mint()

    second = bind_public_operation(**KEY, intent_digest=DIGEST_A, mint=mint)

    assert second.created is False
    assert calls == []
    assert str(second.binding.operation_id) == str(first.binding.operation_id)
    assert PublicOperationRetryBinding.objects.filter(**KEY).count() == 1


def test_replay_different_intent_conflicts_without_reminting():
    bind_public_operation(**KEY, intent_digest=DIGEST_A, mint=_mint)
    calls: list[int] = []

    def mint() -> MintedOperation:
        calls.append(1)
        return _mint()

    with pytest.raises(RetryKeyConflict):
        bind_public_operation(**KEY, intent_digest=DIGEST_B, mint=mint)

    assert calls == []
    assert PublicOperationRetryBinding.objects.filter(**KEY).count() == 1


def test_different_caller_key_is_a_separate_binding():
    bind_public_operation(**KEY, intent_digest=DIGEST_A, mint=_mint)
    other = {**KEY, "caller_key": "k-2"}

    result = bind_public_operation(**other, intent_digest=DIGEST_A, mint=_mint)

    assert result.created is True
    assert PublicOperationRetryBinding.objects.count() == 2


def test_lookup_returns_none_when_absent():
    assert lookup_public_operation(**KEY) is None


def _seed_winner(intent_digest: str) -> PublicOperationRetryBinding:
    """Commit a winner binding for ``KEY`` (the concurrent contender that won)."""
    from datetime import timedelta

    from django.utils import timezone

    return PublicOperationRetryBinding.objects.create(
        **KEY,
        request_id=uuid4(),
        operation_id=uuid4(),
        intent_digest=intent_digest,
        intent_projection_version="1",
        status=RetryBindingStatus.ACTIVE,
        expires_at=timezone.now() + timedelta(hours=1),
    )


def _lose_the_insert_race(monkeypatch) -> None:
    """Make our own lookup miss the winner and our INSERT lose the unique-key race.

    Reproduces the ADR-063-R3 window the SQLite lane cannot race for real: the
    lookup ran before the winner committed (sees nothing), then the create raises
    ``IntegrityError`` so the ``except`` path reads the committed winner instead.
    """
    from django.db import IntegrityError

    monkeypatch.setattr("engine.retry_binding.lookup_public_operation", lambda **_key: None)

    def _raise_on_create(**_kwargs):
        raise IntegrityError("duplicate key value violates unique constraint")

    monkeypatch.setattr(PublicOperationRetryBinding.objects, "create", _raise_on_create)


def test_integrity_error_race_recovers_the_committed_winner(monkeypatch):
    winner = _seed_winner(DIGEST_A)
    _lose_the_insert_race(monkeypatch)

    result = bind_public_operation(**KEY, intent_digest=DIGEST_A, mint=_mint)

    assert result.created is False
    assert result.binding.pk == winner.pk
    assert str(result.binding.operation_id) == str(winner.operation_id)


def test_integrity_error_race_conflicts_when_winner_intent_differs(monkeypatch):
    _seed_winner(DIGEST_A)
    _lose_the_insert_race(monkeypatch)

    with pytest.raises(RetryKeyConflict):
        bind_public_operation(**KEY, intent_digest=DIGEST_B, mint=_mint)


def test_retry_binding_str_names_action_key_and_operation():
    operation_id = uuid4()
    binding = PublicOperationRetryBinding(action="raes-range:provision", caller_key="k-str", operation_id=operation_id)
    rendered = str(binding)
    assert "raes-range:provision" in rendered
    assert "k-str" in rendered
    assert str(operation_id) in rendered
