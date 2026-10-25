"""PostgreSQL proof that concurrent tenant edits have one publication winner."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.db import connection

from engine.models import ModelSourceRevision
from engine.services import create_model_source, update_model_source
from shared.model_access import ContractError
from tests.engine.services.test_model_sources import configuration, source_tenant

__all__ = ["source_tenant"]
pytestmark = [pytest.mark.postgres, pytest.mark.django_db(transaction=True)]


def test_concurrent_source_rotation_publishes_one_revision(source_tenant):
    admin, _, org, store = source_tenant
    source = create_model_source(admin, org.uuid, configuration(), credential={"api_key": "synthetic-initial"})
    barrier = Barrier(2)

    def rotate(index):
        try:
            barrier.wait(timeout=10)
            return update_model_source(
                admin,
                org.uuid,
                source.id,
                expected_revision=1,
                configuration=configuration(),
                credential={"api_key": f"synthetic-rotation-{index}"},
            ).revision
        except ContractError as exc:
            return exc.code
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(rotate, range(2)))
    assert results.count(2) == 1
    assert results.count("source.revision_conflict") == 1
    assert ModelSourceRevision.objects.filter(source_id=source.id).count() == 2
    assert ModelSourceRevision.objects.get(source_id=source.id, revision=2).state == "ready"
    assert store.create_owned_secret.call_count == 2
