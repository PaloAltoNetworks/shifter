"""Trusted instantiation-purpose seam at the CMS launch boundary (issue #1354, ADR-030).

The generic product facades are permanently live-fire: they take no
instantiation-purpose argument. The only path to a non-user purpose is
``create_non_user_range``, which mints it from a declared workflow *after* its
own operator-authority gate. CTF creation can never obtain one.
"""

import inspect
import os
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

import cms.services as services
from cms.exceptions import CMSError
from cms.services._non_user_range_launch import NonUserWorkflow, create_non_user_range
from cms.services._range_backend_admission import assert_backend_admitted
from shared.enums import RangeSource
from shared.range_instantiation_policy import POLICY_DENIAL_CODE, InstantiationPurpose

User = get_user_model()

NON_USER_PURPOSES = (
    InstantiationPurpose.NON_USER_DEMO,
    InstantiationPurpose.OPERATOR_VALIDATION,
    InstantiationPurpose.NON_USER_VALIDATION,
)


def _gcp(settings, backend):
    settings.CLOUD_PROVIDER = "gcp"
    return patch.dict(os.environ, {"GCP_RANGE_BACKEND": backend}, clear=True)


class TestGenericFacadesCannotEscalate:
    """ADR-030-R6: the product facades expose no purpose argument at all."""

    @pytest.mark.parametrize(
        "facade",
        [services.create_range, services.create_range_dispatch, services.create_raes_native_range],
    )
    def test_facade_exposes_no_instantiation_purpose_parameter(self, facade):
        assert "instantiation_purpose" not in inspect.signature(facade).parameters

    @pytest.mark.parametrize(
        "facade",
        [services.create_range, services.create_range_dispatch, services.create_raes_native_range],
    )
    def test_facade_rejects_a_smuggled_purpose_argument(self, facade):
        with pytest.raises(TypeError):
            facade(None, "scenario", instantiation_purpose=InstantiationPurpose.NON_USER_DEMO)


class TestNonUserPurposeAdmitsRetainedGdc:
    """AC: demo/BAS and operator validation can opt in to the retained plumbing."""

    @pytest.mark.parametrize("purpose", NON_USER_PURPOSES)
    def test_gdc_is_admitted_for_a_non_user_purpose(self, settings, purpose):
        with _gcp(settings, "gdc"):
            admission = assert_backend_admitted(purpose)
        assert admission is not None
        assert admission.admitted is True
        assert admission.backend == "gdc"
        assert admission.purpose is purpose

    def test_live_fire_default_is_unchanged_by_the_new_purposes(self, settings):
        with _gcp(settings, "gdc"), pytest.raises(CMSError) as exc:
            assert_backend_admitted(InstantiationPurpose.LIVE_FIRE)
        assert exc.value.details["code"] == POLICY_DENIAL_CODE


class TestCtfCanNeverObtainANonUserPurpose:
    """AC: CTF participant creation cannot use Kubernetes/GDC participant infra."""

    @pytest.mark.parametrize("purpose", NON_USER_PURPOSES)
    def test_ctf_source_with_a_non_user_purpose_is_denied(self, settings, purpose):
        with _gcp(settings, "gdc"), pytest.raises(CMSError) as exc:
            assert_backend_admitted(purpose, range_source=RangeSource.CTF)
        assert exc.value.details["code"] == POLICY_DENIAL_CODE

    def test_ctf_source_is_denied_even_when_the_backend_would_permit_it(self, settings):
        # The guard is on the source/purpose pair, not on the selected backend:
        # a CTF launch must not carry non-user authority on GCE either.
        with _gcp(settings, "gce"), pytest.raises(CMSError):
            assert_backend_admitted(InstantiationPurpose.NON_USER_DEMO, range_source=RangeSource.CTF)

    def test_ctf_live_fire_on_the_approved_backend_still_launches(self, settings):
        with _gcp(settings, "gce"):
            admission = assert_backend_admitted(InstantiationPurpose.LIVE_FIRE, range_source=RangeSource.CTF)
        assert admission is not None
        assert admission.admitted is True


class TestPurposeIsAClosedTrustedValue:
    def test_a_raw_string_is_rejected(self, settings):
        # A str arriving here means an untrusted value was plumbed in; only a
        # closed enum member is workflow authority (ADR-030-R6).
        with _gcp(settings, "gdc"), pytest.raises(CMSError):
            assert_backend_admitted("non_user_demo")

    def test_an_unknown_object_is_rejected(self, settings):
        unknown_purpose = object()
        with _gcp(settings, "gdc"), pytest.raises(CMSError):
            assert_backend_admitted(unknown_purpose)

    def test_non_gcp_returns_no_binding(self, settings):
        settings.CLOUD_PROVIDER = "aws"
        assert assert_backend_admitted(InstantiationPurpose.NON_USER_DEMO) is None


@pytest.mark.django_db
class TestOperatorGateOnTheDedicatedEntryPoint:
    @pytest.fixture
    def participant(self, db):
        return User.objects.create_user(username="player@example.com", email="player@example.com")

    @pytest.fixture
    def operator(self, db):
        return User.objects.create_user(username="operator@example.com", email="operator@example.com", is_staff=True)

    @pytest.mark.parametrize("workflow", list(NonUserWorkflow))
    def test_a_non_operator_is_refused_before_any_purpose_is_minted(
        self, settings, participant, hydratable_scenario, workflow
    ):
        from cms.models import RangeInstance

        with _gcp(settings, "gdc"), pytest.raises(CMSError) as exc:
            create_non_user_range(participant, hydratable_scenario.scenario_id, workflow=workflow)
        assert exc.value.details["code"] == POLICY_DENIAL_CODE
        assert not RangeInstance.objects.filter(user_id=participant.id).exists()

    def test_an_inactive_operator_is_refused(self, settings, operator, hydratable_scenario):
        operator.is_active = False
        operator.save(update_fields=["is_active"])
        with _gcp(settings, "gdc"), pytest.raises(CMSError):
            create_non_user_range(
                operator, hydratable_scenario.scenario_id, workflow=NonUserWorkflow.OPERATOR_VALIDATION
            )

    def test_an_undeclared_workflow_is_refused(self, settings, operator, hydratable_scenario):
        with _gcp(settings, "gdc"), pytest.raises(CMSError):
            create_non_user_range(operator, hydratable_scenario.scenario_id, workflow="operator_validation")

    @pytest.mark.parametrize(
        ("workflow", "expected_purpose"),
        [
            (NonUserWorkflow.PRODUCT_DEMO, InstantiationPurpose.NON_USER_DEMO),
            (NonUserWorkflow.BREACH_ATTACK_SIMULATION, InstantiationPurpose.NON_USER_DEMO),
            (NonUserWorkflow.OPERATOR_VALIDATION, InstantiationPurpose.OPERATOR_VALIDATION),
            (NonUserWorkflow.IMAGE_VALIDATION, InstantiationPurpose.OPERATOR_VALIDATION),
        ],
    )
    def test_an_operator_launch_binds_the_raes_backend(
        self, settings, operator, make_agent, hydratable_scenario, workflow, expected_purpose
    ):
        from engine.models import Range as EngineRange

        agent = make_agent(operator)
        with _gcp(settings, "gce"):
            create_non_user_range(
                operator,
                hydratable_scenario.scenario_id,
                {"windows": agent.id},
                workflow=workflow,
            )
        engine_range = EngineRange.objects.get(user_id=operator.id)
        assert engine_range.range_backend == "gce"
        assert engine_range.instantiation_purpose == expected_purpose.value


@pytest.mark.django_db
class TestCreateRangeFacadeStaysLiveFire:
    @pytest.fixture
    def user(self, db):
        return User.objects.create_user(username="purpose@example.com", email="purpose@example.com")

    def test_default_launch_binds_live_fire(self, settings, user, make_agent, hydratable_scenario):
        from engine.models import Range as EngineRange

        agent = make_agent(user)
        with _gcp(settings, "gce"):
            services.create_range(user, hydratable_scenario.scenario_id, {"windows": agent.id})
        engine_range = EngineRange.objects.get(user_id=user.id)
        assert engine_range.range_backend == "gce"
        assert engine_range.instantiation_purpose == InstantiationPurpose.LIVE_FIRE.value

    def test_a_staff_user_on_the_normal_facade_still_gets_live_fire(
        self, settings, user, make_agent, hydratable_scenario
    ):
        # Operator authority does not leak into the ordinary product path; only
        # the dedicated workflow mints a non-user purpose (ADR-030-R6).
        from cms.exceptions import CMSError as _CMSError

        user.is_staff = True
        user.save(update_fields=["is_staff"])
        agent = make_agent(user)
        with _gcp(settings, "gdc"), pytest.raises(_CMSError) as exc:
            services.create_range(user, hydratable_scenario.scenario_id, {"windows": agent.id})
        assert exc.value.details["code"] == POLICY_DENIAL_CODE

    def test_ctf_launch_stays_live_fire_and_is_denied_on_gdc(self, settings, user, make_agent, hydratable_scenario):
        from cms.models import RangeInstance

        agent = make_agent(user)
        # Built outside the raises block so only create_range can throw (Sonar S5778).
        teardown_at = timezone.now() + timedelta(days=1)
        with _gcp(settings, "gdc"), pytest.raises(CMSError):
            services.create_range(
                user,
                hydratable_scenario.scenario_id,
                {"windows": agent.id},
                range_source=RangeSource.CTF,
                remote_access_teardown_at=teardown_at,
            )
        assert not RangeInstance.objects.filter(user_id=user.id).exists()
