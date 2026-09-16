"""Real PostgreSQL serialization of preparation retries and shared scope capacity."""

from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from time import monotonic, sleep

import pytest
from django.contrib.auth.models import User
from django.db import connection, connections, transaction

from engine.models import PreparationAttempt, PreparationGrant, PreparationOperation, PreparationScopeLock
from engine.services import install_preparation_adapter, request_artifact_preparation
from shared.exceptions import ValidationError
from shared.preparation_grant import PreparationGrantConfiguration
from tests.engine.services.test_preparation_adapters import administrator, grant
from tests.engine.services.test_preparation_operations import operator, package_input
from tests.shared.raes.test_preparation_contract import manifest_payload

pytestmark = [pytest.mark.postgres, pytest.mark.django_db(transaction=True)]
__all__ = ["administrator", "grant", "operator"]


def _single_slot_adapters(administrator, grant):
    configuration = PreparationGrantConfiguration.model_validate(dict(grant.configuration, max_concurrent_operations=1))
    grant.configuration = configuration.model_dump(mode="json")
    grant.configuration_digest = configuration.digest
    grant.save()
    first = install_preparation_adapter(administrator, grant.pk, manifest_payload())
    replacement = PreparationGrantConfiguration.model_validate(dict(grant.configuration, max_duration_seconds=1800))
    second_grant = PreparationGrant.objects.create(
        scope_digest=replacement.scope_digest,
        configuration_digest=replacement.digest,
        configuration=replacement.model_dump(mode="json"),
        active=True,
    )
    second = install_preparation_adapter(administrator, second_grant.pk, dict(manifest_payload(), version="2"))
    assert first.grant_id != second.grant_id
    assert first.scope_digest == second.scope_digest
    return first, second


def _request(user_id, adapter_id, pids):
    try:
        actor = User.objects.get(pk=user_id)
        with connection.cursor() as cursor:
            cursor.execute("SET lock_timeout = '10s'")
            cursor.execute("SELECT pg_backend_pid()")
            pids.put(cursor.fetchone()[0])
        try:
            return request_artifact_preparation(actor, adapter_id, package_input())
        except ValidationError as exc:
            return exc
    finally:
        connections.close_all()


def _wait_for_database_lock_waiters(pids, futures):
    """Observe both sessions blocked by PostgreSQL, rather than assume scheduler timing."""
    deadline = monotonic() + 5
    while monotonic() < deadline:
        assert not any(future.done() for future in futures), "request bypassed the held scope lock"
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM pg_stat_activity WHERE pid = ANY(%s) AND wait_event_type = 'Lock'", [pids]
            )
            if cursor.fetchone()[0] == len(pids):
                return
        sleep(0.01)
    pytest.fail("concurrent preparation requests did not reach the database scope lock")


@pytest.mark.parametrize("same_request", [True, False])
def test_concurrent_requests_serialize_deduplication_and_cross_grant_capacity(
    administrator, grant, operator, same_request
):
    first, second = _single_slot_adapters(administrator, grant)
    selected = [first, first if same_request else second]
    PreparationScopeLock.objects.get_or_create(scope_digest=first.scope_digest)
    pids = Queue()
    with ThreadPoolExecutor(max_workers=2) as pool:
        with transaction.atomic():
            PreparationScopeLock.objects.select_for_update().get(pk=first.scope_digest)
            futures = [pool.submit(_request, operator.pk, adapter.id, pids) for adapter in selected]
            _wait_for_database_lock_waiters([pids.get(timeout=5) for _ in futures], futures)
            assert not PreparationOperation.objects.exists()
        results = [future.result(timeout=15) for future in futures]

    assert PreparationOperation.objects.count() == 1
    assert PreparationAttempt.objects.count() == 1
    operation = PreparationOperation.objects.get()
    winners = [result for result in results if not isinstance(result, ValidationError)]
    failures = [result for result in results if isinstance(result, ValidationError)]
    assert len(winners) == (2 if same_request else 1)
    assert all(result.id == operation.id and result.state == "queued" for result in winners)
    assert len(failures) == (0 if same_request else 1)
    assert all("capacity" in failure.message for failure in failures)
