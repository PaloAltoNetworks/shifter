"""PostgreSQL proofs that a retry key arbitrates concurrent first use (#2086, ADR-063-R3).

Two callers racing the same retry key must converge on exactly one binding and one
operation; different-intent contenders must yield exactly one binding and a bounded
conflict. SQLite cannot prove the unique-insert race, so these run on the Postgres
lane only.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from django.db import connection

from engine.models import PublicOperationRetryBinding
from engine.retry_binding import MintedOperation, RetryKeyConflict, bind_public_operation

pytestmark = [pytest.mark.postgres, pytest.mark.django_db(transaction=True)]

DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
KEY = {
    "deployment_scope": "proj-race",
    "actor_key": "7",
    "action": "raes-range:provision",
    "caller_key": "race-1",
}


def _bind(digest, barrier):
    barrier.wait(timeout=10)
    try:
        result = bind_public_operation(
            **KEY,
            intent_digest=digest,
            mint=lambda: MintedOperation(request_id=str(uuid4()), operation_id=str(uuid4())),
        )
        return ("created" if result.created else "recovered", str(result.binding.operation_id))
    except RetryKeyConflict:
        return ("conflict", None)
    finally:
        connection.close()


def test_same_key_same_intent_race_converges_on_one_binding():
    barrier = threading.Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: _bind(DIGEST_A, barrier), range(2)))

    assert sorted(outcome[0] for outcome in outcomes) == ["created", "recovered"]
    assert len({outcome[1] for outcome in outcomes}) == 1  # both converge on the winner's operation
    assert PublicOperationRetryBinding.objects.filter(**KEY).count() == 1


def test_same_key_different_intent_race_yields_one_binding_and_a_conflict():
    barrier = threading.Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda digest: _bind(digest, barrier), [DIGEST_A, DIGEST_B]))

    assert sorted(outcome[0] for outcome in outcomes) == ["conflict", "created"]
    assert PublicOperationRetryBinding.objects.filter(**KEY).count() == 1
