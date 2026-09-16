"""A preparation worker endpoint accepts only its scoped attempt credential."""

import pytest
from rest_framework.test import APIClient

from engine.models import PreparationAttempt
from engine.services import request_artifact_preparation
from engine.services._preparation_worker import attempt_token
from tests.engine.services.test_preparation_operations import administrator, grant, installed, operator, package_input
from tests.engine.services.test_preparation_worker_boundary import result_for

pytestmark = pytest.mark.django_db
__all__ = ["administrator", "grant", "installed", "operator"]


@pytest.fixture
def attempt(operator, installed):
    operation = request_artifact_preparation(operator, installed.id, package_input())
    return PreparationAttempt.objects.get(operation_id=operation.id)


def endpoint(attempt):
    return f"/api/v1/cms/artifact-preparation/workers/{attempt.operation_id}/"


def test_worker_credential_reads_own_input_and_records_only_receipt(attempt):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {attempt_token(attempt)}")
    response = client.get(endpoint(attempt))
    assert response.status_code == 200
    assert response.json()["input_digest"] == attempt.input_digest
    result = client.post(endpoint(attempt), result_for(attempt), format="json")
    assert result.status_code == 202
    assert result.json() == {"status": "received"}
    assert attempt.operation.state == "queued"


def test_opaque_id_and_platform_session_do_not_confer_worker_authority(attempt, operator):
    client = APIClient()
    assert client.get(endpoint(attempt)).status_code == 401
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {attempt.id}")
    assert client.get(endpoint(attempt)).status_code == 401
    client.force_authenticate(user=operator)
    assert client.get(endpoint(attempt)).status_code == 403


def test_worker_credential_cannot_administer_adapters(attempt):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {attempt_token(attempt)}")
    assert client.get("/api/v1/cms/preparation-adapters/").status_code in {401, 403}
