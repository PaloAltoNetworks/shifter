"""Write-once range-backend ownership binding at Engine create + operator backfill (#1666).

Drives the real engine services against a real database: the trusted
``BackendAdmission`` carried from CMS is persisted as the immutable
(range_backend, instantiation_purpose) binding on the Range, write-once, in the
create transaction; and the operator backfill command repairs a legacy row.
"""

from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command

from engine.models import Range
from engine.services import create_aces_range
from engine.services._common import EngineError
from shared.range_instantiation_policy import (
    BackendAdmission,
    InstantiationPurpose,
    evaluate_gcp_backend_admission,
)

# Import the ACES plan builder from the sibling behavior test to avoid duplication.
from tests.engine.services.test_aces_range import make_compiled_plan

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="binding@example.com", email="binding@example.com")


@pytest.fixture(autouse=True)
def _ecs_noop(settings):
    settings.LOCAL_PROVISIONER = None
    settings.ENGINE_TASK_CLUSTER = ""
    settings.ENGINE_ECS_CLUSTER_ARN = ""


class TestCreateBindsOwnershipWriteOnce:
    def test_admission_persists_backend_and_purpose(self, user):
        admission = evaluate_gcp_backend_admission("gce", None, InstantiationPurpose.LIVE_FIRE)
        request_id = uuid4()
        create_aces_range(
            request_id=request_id, user_id=user.id, compiled_plan=make_compiled_plan(), backend_admission=admission
        )
        rng = Range.objects.get(request__request_id=request_id)
        assert rng.range_backend == "gce"
        assert rng.instantiation_purpose == "live_fire"

    def test_no_admission_leaves_binding_null(self, user):
        request_id = uuid4()
        create_aces_range(request_id=request_id, user_id=user.id, compiled_plan=make_compiled_plan())
        rng = Range.objects.get(request__request_id=request_id)
        assert rng.range_backend is None
        assert rng.instantiation_purpose is None

    def test_idempotent_same_binding_is_accepted(self, user):
        admission = evaluate_gcp_backend_admission("gce", None, InstantiationPurpose.LIVE_FIRE)
        request_id = uuid4()
        create_aces_range(
            request_id=request_id, user_id=user.id, compiled_plan=make_compiled_plan(), backend_admission=admission
        )
        # Re-drive with the same binding: idempotent reuse, no error.
        ref = create_aces_range(
            request_id=request_id, user_id=user.id, compiled_plan=make_compiled_plan(), backend_admission=admission
        )
        assert ref.accepted is True

    def test_idempotent_different_binding_is_conflict(self, user):
        admission = evaluate_gcp_backend_admission("gce", None, InstantiationPurpose.LIVE_FIRE)
        request_id = uuid4()
        create_aces_range(
            request_id=request_id, user_id=user.id, compiled_plan=make_compiled_plan(), backend_admission=admission
        )
        conflicting = BackendAdmission(True, "gdc", InstantiationPurpose.NON_USER_VALIDATION, "", "")
        plan = make_compiled_plan()
        with pytest.raises(EngineError, match="conflict"):
            create_aces_range(
                request_id=request_id,
                user_id=user.id,
                compiled_plan=plan,
                backend_admission=conflicting,
            )


class TestOperatorBackfill:
    def test_backfill_sets_binding_then_refuses_overwrite(self, user):
        legacy = Range.objects.create(user=user, status=Range.Status.READY)
        range_id = str(legacy.id)
        assert legacy.range_backend is None

        call_command("backfill_range_backend_binding", "--range-id", range_id, "--backend", "gdc")
        legacy.refresh_from_db()
        assert legacy.range_backend == "gdc"
        assert legacy.instantiation_purpose == "live_fire"

        # Write-once: a second backfill must refuse rather than overwrite.
        with pytest.raises(CommandError, match="write-once"):
            call_command("backfill_range_backend_binding", "--range-id", range_id, "--backend", "gce")

    def test_backfill_rejects_unknown_backend(self, user):
        legacy = Range.objects.create(user=user, status=Range.Status.READY)
        range_id = str(legacy.id)
        with pytest.raises(CommandError):
            call_command("backfill_range_backend_binding", "--range-id", range_id, "--backend", "bogus")
