"""Unit tests for the closed range-instantiation policy (issue #1348, ADR-030).

Pure-function policy: no Django, no DB. Covers the single GCP range-backend
parser and the fail-closed (backend, purpose) admission matrix shared by the CMS
service gate and the provisioner defense-in-depth denial.
"""

import pytest

from shared.range_instantiation_policy import (
    POLICY_DENIAL_CODE,
    PREREQUISITE_DENIAL_CODE,
    BackendAdmission,
    GcpRangeBackendError,
    InstantiationPurpose,
    evaluate_gcp_backend_admission,
    normalize_gcp_range_backend,
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
        assert "GDC" in result.reason and "gce" in result.reason.lower()

    def test_gdc_via_plane_alias_is_denied(self):
        result = evaluate_gcp_backend_admission(None, "gdc", InstantiationPurpose.LIVE_FIRE)
        assert result.admitted is False
        assert result.code == POLICY_DENIAL_CODE

    def test_unknown_selector_fails_closed_prerequisite(self):
        result = evaluate_gcp_backend_admission("bogus", None, InstantiationPurpose.LIVE_FIRE)
        assert result.admitted is False
        assert result.code == PREREQUISITE_DENIAL_CODE


class TestNonUserValidationAdmission:
    def test_gdc_is_admitted_for_validation(self):
        result = evaluate_gcp_backend_admission("gdc", None, InstantiationPurpose.NON_USER_VALIDATION)
        assert result.admitted is True
        assert result.backend == "gdc"

    def test_gce_is_admitted_for_validation(self):
        result = evaluate_gcp_backend_admission("gce", None, InstantiationPurpose.NON_USER_VALIDATION)
        assert result.admitted is True

    def test_unknown_selector_still_fails_closed(self):
        result = evaluate_gcp_backend_admission("bogus", None, InstantiationPurpose.NON_USER_VALIDATION)
        assert result.admitted is False
        assert result.code == PREREQUISITE_DENIAL_CODE


class TestInstantiationPurposeIsClosed:
    def test_purpose_values(self):
        assert InstantiationPurpose.LIVE_FIRE.value == "live_fire"
        assert InstantiationPurpose.NON_USER_VALIDATION.value == "non_user_validation"

    def test_purpose_is_a_closed_set(self):
        assert set(InstantiationPurpose) == {
            InstantiationPurpose.LIVE_FIRE,
            InstantiationPurpose.NON_USER_VALIDATION,
        }
