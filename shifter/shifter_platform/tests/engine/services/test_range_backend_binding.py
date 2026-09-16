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
from engine.services import create_raes_range
from engine.services._common import EngineError
from shared.range_instantiation_policy import (
    BackendAdmission,
    InstantiationPurpose,
    evaluate_gcp_backend_admission,
)

# Import the RAES plan builder from the sibling behavior test to avoid duplication.
from tests.engine.services.test_raes_range import make_compiled_plan

# Opaque #1325 workspace scope binding. engine.services requires one on every
# range create (ADR-046-R3); these suites do not exercise tenancy, so a fixed
# scalar stands in for the value the CMS launch facade would resolve.
_WORKSPACE_ID = 1


def _create_raes_range(**kwargs):
    """Call the real seam with the workspace binding these suites do not vary."""
    kwargs.setdefault("workspace_id", _WORKSPACE_ID)
    return create_raes_range(**kwargs)


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
        _create_raes_range(
            request_id=request_id, user_id=user.id, compiled_plan=make_compiled_plan(), backend_admission=admission
        )
        rng = Range.objects.get(request__request_id=request_id)
        assert rng.range_backend == "gce"
        assert rng.instantiation_purpose == "live_fire"

    def test_no_admission_leaves_binding_null(self, user):
        request_id = uuid4()
        _create_raes_range(request_id=request_id, user_id=user.id, compiled_plan=make_compiled_plan())
        rng = Range.objects.get(request__request_id=request_id)
        assert rng.range_backend is None
        assert rng.instantiation_purpose is None

    def test_idempotent_same_binding_is_accepted(self, user):
        admission = evaluate_gcp_backend_admission("gce", None, InstantiationPurpose.LIVE_FIRE)
        request_id = uuid4()
        _create_raes_range(
            request_id=request_id, user_id=user.id, compiled_plan=make_compiled_plan(), backend_admission=admission
        )
        # Re-drive with the same binding: idempotent reuse, no error.
        ref = _create_raes_range(
            request_id=request_id, user_id=user.id, compiled_plan=make_compiled_plan(), backend_admission=admission
        )
        assert ref.accepted is True

    def test_idempotent_different_binding_is_conflict(self, user):
        admission = evaluate_gcp_backend_admission("gce", None, InstantiationPurpose.LIVE_FIRE)
        request_id = uuid4()
        _create_raes_range(
            request_id=request_id, user_id=user.id, compiled_plan=make_compiled_plan(), backend_admission=admission
        )
        conflicting = BackendAdmission(True, "gdc", InstantiationPurpose.NON_USER_VALIDATION, "", "")
        plan = make_compiled_plan()
        with pytest.raises(EngineError, match="conflict"):
            _create_raes_range(
                request_id=request_id,
                user_id=user.id,
                compiled_plan=plan,
                backend_admission=conflicting,
            )


class TestCreateRevalidatesTheAdmittedPair:
    """#1354: BackendAdmission is constructible, so admitted=True is not authority."""

    def test_fabricated_live_fire_gdc_admission_is_refused(self, user):
        forged = BackendAdmission(True, "gdc", InstantiationPurpose.LIVE_FIRE, "", "")
        request_id = uuid4()
        plan = make_compiled_plan()
        with pytest.raises(EngineError, match="not admitted"):
            _create_raes_range(request_id=request_id, user_id=user.id, compiled_plan=plan, backend_admission=forged)
        assert not Range.objects.filter(request__request_id=request_id).exists()

    def test_fabricated_unregistered_backend_is_refused(self, user):
        forged = BackendAdmission(True, "k8s", InstantiationPurpose.OPERATOR_VALIDATION, "", "")
        request_id = uuid4()
        plan = make_compiled_plan()
        with pytest.raises(EngineError):
            _create_raes_range(request_id=request_id, user_id=user.id, compiled_plan=plan, backend_admission=forged)

    def test_a_genuinely_admitted_non_user_pair_persists(self, user):
        admission = evaluate_gcp_backend_admission("gdc", None, InstantiationPurpose.NON_USER_DEMO)
        request_id = uuid4()
        _create_raes_range(
            request_id=request_id, user_id=user.id, compiled_plan=make_compiled_plan(), backend_admission=admission
        )
        rng = Range.objects.get(request__request_id=request_id)
        assert rng.range_backend == "gdc"
        assert rng.instantiation_purpose == "non_user_demo"


class TestOperatorBackfill:
    def test_backfill_sets_binding_then_refuses_overwrite(self, user):
        legacy = Range.objects.create(workspace_id=_WORKSPACE_ID, user=user, status=Range.Status.READY)
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
        legacy = Range.objects.create(workspace_id=_WORKSPACE_ID, user=user, status=Range.Status.READY)
        range_id = str(legacy.id)
        with pytest.raises(CommandError):
            call_command("backfill_range_backend_binding", "--range-id", range_id, "--backend", "bogus")


class TestBackendEgressNoneCapabilityGate:
    """A `none` range fails closed on a backend without native no-NAT support (PLAT-238)."""

    def test_gce_supports_none(self):
        from engine.services._range_backend_binding import assert_backend_supports_egress_none

        # No raise: GCE realizes `none` by omitting the range-owned Cloud NAT.
        assert_backend_supports_egress_none("gce", "none")

    def test_aws_path_none_backend_supports_none(self):
        from engine.services._range_backend_binding import assert_backend_supports_egress_none

        # The AWS path carries no GCP range_backend and realizes `none` via Terraform.
        assert_backend_supports_egress_none(None, "none")

    def test_gdc_rejects_none(self):
        from engine.services._range_backend_binding import assert_backend_supports_egress_none

        with pytest.raises(EngineError, match="does not support the zero-egress"):
            assert_backend_supports_egress_none("gdc", "none")

    def test_status_quo_is_never_gated(self):
        from engine.services._range_backend_binding import assert_backend_supports_egress_none

        # Only a `none` decision is gated; status-quo passes for any backend.
        assert_backend_supports_egress_none("gdc", "status-quo")

    def test_none_launch_on_gdc_is_refused_at_the_real_create_path(self, user):
        """The capability gate must fire where it is wired, not only as a unit call."""
        admission = evaluate_gcp_backend_admission("gdc", None, InstantiationPurpose.NON_USER_DEMO)
        request_id = uuid4()
        plan = make_compiled_plan()
        with pytest.raises(EngineError, match="does not support the zero-egress"):
            _create_raes_range(
                request_id=request_id,
                user_id=user.id,
                compiled_plan=plan,
                backend_admission=admission,
                egress_mode="none",
            )
        assert not Range.objects.filter(request__request_id=request_id).exists()

    def test_none_launch_on_gce_is_admitted_and_pinned(self, user):
        admission = evaluate_gcp_backend_admission("gce", None, InstantiationPurpose.LIVE_FIRE)
        request_id = uuid4()
        _create_raes_range(
            request_id=request_id,
            user_id=user.id,
            compiled_plan=make_compiled_plan(),
            backend_admission=admission,
            egress_mode="none",
        )
        rng = Range.objects.get(request__request_id=request_id)
        assert rng.range_backend == "gce"
        assert rng.egress_mode == "none"
