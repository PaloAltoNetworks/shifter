"""Unit tests for the closed range-instantiation policy (issues #1348/#1354, ADR-030).

Pure-function policy: no Django, no DB. Covers the single GCP range-backend
parser, the closed default-deny backend registry, and the fail-closed
(backend, purpose) admission matrix shared by the CMS service gate and the
provisioner defense-in-depth denial.
"""

import pytest

from shared.range_instantiation_policy import (
    POLICY_DENIAL_CODE,
    PREREQUISITE_DENIAL_CODE,
    RANGE_BACKENDS,
    BackendAdmission,
    GcpRangeBackendError,
    InstantiationPurpose,
    evaluate_gcp_backend_admission,
    normalize_gcp_range_backend,
    parse_instantiation_purpose,
)

NON_USER_PURPOSES = (
    InstantiationPurpose.NON_USER_DEMO,
    InstantiationPurpose.OPERATOR_VALIDATION,
    InstantiationPurpose.NON_USER_VALIDATION,
)


class TestNormalizeGcpRangeBackend:
    def test_defaults_to_gce_when_unset(self):
        assert normalize_gcp_range_backend(None, None) == "gce"

    def test_selects_gdc_explicitly(self):
        assert normalize_gcp_range_backend("gdc", None) == "gdc"

    def test_falls_back_to_plane_alias(self):
        assert normalize_gcp_range_backend(None, "gdc") == "gdc"

    def test_backend_wins_over_plane_alias(self):
        assert normalize_gcp_range_backend("gce", "gdc") == "gce"

    def test_normalizes_case_and_whitespace(self):
        assert normalize_gcp_range_backend("  GDC ", None) == "gdc"

    def test_empty_backend_falls_through_to_default(self):
        assert normalize_gcp_range_backend("", "") == "gce"

    def test_rejects_unknown_value(self):
        with pytest.raises(GcpRangeBackendError, match=r"gdc.*gce|gce.*gdc"):
            normalize_gcp_range_backend("gdcx", None)

    def test_rejects_whitespace_only_value(self):
        # A non-empty-but-whitespace selector is a misconfiguration, not "unset"
        # (preserves the pre-#1348 get_gcp_range_backend() contract).
        with pytest.raises(GcpRangeBackendError):
            normalize_gcp_range_backend("   ", None)


class TestLiveFireAdmission:
    def test_gce_is_admitted(self):
        result = evaluate_gcp_backend_admission("gce", None, InstantiationPurpose.LIVE_FIRE)
        assert result == BackendAdmission(True, "gce", InstantiationPurpose.LIVE_FIRE, "", "")

    def test_unset_defaults_to_admitted_gce(self):
        result = evaluate_gcp_backend_admission(None, None, InstantiationPurpose.LIVE_FIRE)
        assert result.admitted is True
        assert result.backend == "gce"

    def test_gdc_is_denied_identity_or_policy(self):
        result = evaluate_gcp_backend_admission("gdc", None, InstantiationPurpose.LIVE_FIRE)
        assert result.admitted is False
        assert result.code == POLICY_DENIAL_CODE
        assert result.backend == "gdc"
        assert "GDC" in result.reason
        assert "gce" in result.reason.lower()

    def test_gdc_via_plane_alias_is_denied(self):
        result = evaluate_gcp_backend_admission(None, "gdc", InstantiationPurpose.LIVE_FIRE)
        assert result.admitted is False
        assert result.code == POLICY_DENIAL_CODE

    def test_unknown_selector_fails_closed_prerequisite(self):
        result = evaluate_gcp_backend_admission("bogus", None, InstantiationPurpose.LIVE_FIRE)
        assert result.admitted is False
        assert result.code == PREREQUISITE_DENIAL_CODE


class TestNonUserAdmission:
    @pytest.mark.parametrize("purpose", NON_USER_PURPOSES)
    def test_gdc_is_admitted_for_every_non_user_purpose(self, purpose):
        result = evaluate_gcp_backend_admission("gdc", None, purpose)
        assert result.admitted is True
        assert result.backend == "gdc"
        assert result.purpose is purpose

    @pytest.mark.parametrize("purpose", NON_USER_PURPOSES)
    def test_gce_is_admitted_for_every_non_user_purpose(self, purpose):
        result = evaluate_gcp_backend_admission("gce", None, purpose)
        assert result.admitted is True

    @pytest.mark.parametrize("purpose", NON_USER_PURPOSES)
    def test_unknown_selector_still_fails_closed(self, purpose):
        result = evaluate_gcp_backend_admission("bogus", None, purpose)
        assert result.admitted is False
        assert result.code == PREREQUISITE_DENIAL_CODE


class TestInstantiationPurposeIsClosed:
    def test_purpose_values(self):
        assert InstantiationPurpose.LIVE_FIRE.value == "live_fire"
        assert InstantiationPurpose.NON_USER_DEMO.value == "non_user_demo"
        assert InstantiationPurpose.OPERATOR_VALIDATION.value == "operator_validation"
        assert InstantiationPurpose.NON_USER_VALIDATION.value == "non_user_validation"

    def test_purpose_is_a_closed_set(self):
        assert set(InstantiationPurpose) == {
            InstantiationPurpose.LIVE_FIRE,
            InstantiationPurpose.NON_USER_DEMO,
            InstantiationPurpose.OPERATOR_VALIDATION,
            InstantiationPurpose.NON_USER_VALIDATION,
        }

    def test_every_purpose_fits_the_persisted_column_width(self):
        # engine.models.Range.instantiation_purpose is CharField(max_length=24);
        # a longer identifier would silently need a migration (#1354 plan).
        assert all(len(purpose.value) <= 24 for purpose in InstantiationPurpose)


class TestBackendRegistryIsDefaultDeny:
    """ADR-030-R6: each backend explicitly enumerates its permitted purposes."""

    def test_registry_covers_exactly_the_parseable_gcp_backends(self):
        gcp_slugs = {slug for slug, reg in RANGE_BACKENDS.items() if reg.provider == "gcp"}
        assert gcp_slugs == {"gce", "gdc"}

    def test_gce_permits_live_fire_and_every_non_user_purpose(self):
        assert RANGE_BACKENDS["gce"].permitted_purposes == set(InstantiationPurpose)

    def test_gdc_never_permits_live_fire(self):
        assert InstantiationPurpose.LIVE_FIRE not in RANGE_BACKENDS["gdc"].permitted_purposes

    def test_gdc_permits_only_the_non_user_purposes_adr_030_names(self):
        assert RANGE_BACKENDS["gdc"].permitted_purposes == set(NON_USER_PURPOSES)

    def test_registration_is_immutable(self):
        with pytest.raises(TypeError):
            RANGE_BACKENDS["gdc"] = RANGE_BACKENDS["gce"]

    def test_denial_names_the_permitted_scope(self):
        # ADR-030-R3: the runtime error must name the scope the retained
        # substrate is limited to, not just say "denied".
        reason = evaluate_gcp_backend_admission("gdc", None, InstantiationPurpose.LIVE_FIRE).reason
        assert "gdc" in reason
        assert "live_fire" in reason
        for permitted in RANGE_BACKENDS["gdc"].permitted_purposes:
            assert permitted.value in reason

    def test_an_unregistered_backend_is_denied_for_every_purpose(self):
        # The parser's valid set is derived from the registry, so an unregistered
        # slug cannot be selected for any purpose -- registration is the only way in.
        for purpose in InstantiationPurpose:
            result = evaluate_gcp_backend_admission("k8s", None, purpose)
            assert result.admitted is False
            assert result.code == PREREQUISITE_DENIAL_CODE


class TestParseInstantiationPurpose:
    def test_parses_every_closed_value(self):
        for purpose in InstantiationPurpose:
            assert parse_instantiation_purpose(purpose.value) is purpose

    def test_normalizes_case_and_whitespace(self):
        assert parse_instantiation_purpose("  Operator_Validation ") is InstantiationPurpose.OPERATOR_VALIDATION

    def test_absent_purpose_defaults_to_live_fire(self):
        # NULL/blank is the legacy pre-#1666 and non-GCP sentinel; the safe
        # interpretation of "no recorded purpose" is the strictest one.
        assert parse_instantiation_purpose(None) is InstantiationPurpose.LIVE_FIRE
        assert parse_instantiation_purpose("") is InstantiationPurpose.LIVE_FIRE
        assert parse_instantiation_purpose("   ") is InstantiationPurpose.LIVE_FIRE

    def test_rejects_an_unknown_purpose(self):
        with pytest.raises(ValueError, match="live_fire"):
            parse_instantiation_purpose("bas")
