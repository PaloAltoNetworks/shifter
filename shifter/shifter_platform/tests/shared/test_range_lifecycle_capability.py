"""Unit tests for the closed range pause/resume lifecycle-capability policy (#614).

Pure-function policy: no Django, no DB. Covers the backend-authoritative
``(cloud_provider, asset_type)`` capability table shared by the CMS gate, the
Mission Control range projection, and the provisioner defense-in-depth denial.
"""

from shared.range_lifecycle_capability import (
    ASSET_TYPE_GCE_VM,
    ASSET_TYPE_SCENARIO_POD,
    ASSET_TYPE_VM_RUNTIME_VM,
    is_lossless_pausable,
    normalize_asset_key,
    normalize_backend,
    range_pause_resume_capability,
)


class TestIsLosslessPausable:
    def test_aws_vm_runtime_is_pausable(self):
        assert is_lossless_pausable("aws", ASSET_TYPE_VM_RUNTIME_VM) is True

    def test_gcp_vm_runtime_is_pausable(self):
        assert is_lossless_pausable("gcp", ASSET_TYPE_VM_RUNTIME_VM) is True

    def test_gce_vm_is_pausable(self):
        assert is_lossless_pausable("gcp", ASSET_TYPE_GCE_VM) is True

    def test_scenario_pod_is_not_pausable(self):
        assert is_lossless_pausable("gcp", ASSET_TYPE_SCENARIO_POD) is False

    def test_unknown_provider_is_not_pausable(self):
        assert is_lossless_pausable("azure", "vm") is False

    def test_defaults_missing_fields_to_aws_vm_runtime(self):
        assert normalize_asset_key(None, None) == ("aws", ASSET_TYPE_VM_RUNTIME_VM)
        assert is_lossless_pausable(None, None) is True

    def test_normalizes_case_and_whitespace(self):
        assert normalize_asset_key("  GCP ", "  gce_vm ") == ("gcp", ASSET_TYPE_GCE_VM)


class TestNormalizeBackend:
    def test_none_and_blank_map_to_aws(self):
        assert normalize_backend(None) == "aws"
        assert normalize_backend("") == "aws"
        assert normalize_backend("  AWS ") == "aws"

    def test_gcp_backends_pass_through(self):
        assert normalize_backend("gce") == "gce"
        assert normalize_backend(" GDC ") == "gdc"


class TestRangePauseResumeCapability:
    def test_empty_range_is_vacuously_supported(self):
        cap = range_pause_resume_capability("gce", [])
        assert cap.supported is True
        assert cap.reason == ""
        assert cap.unsupported_assets == ()

    def test_all_gce_range_is_supported(self):
        cap = range_pause_resume_capability("gce", [("gcp", ASSET_TYPE_GCE_VM), ("gcp", ASSET_TYPE_GCE_VM)])
        assert cap.supported is True

    def test_all_gdc_vm_runtime_range_is_supported(self):
        cap = range_pause_resume_capability("gdc", [("gcp", ASSET_TYPE_VM_RUNTIME_VM)])
        assert cap.supported is True

    def test_pure_aws_range_is_supported(self):
        cap = range_pause_resume_capability(None, [("aws", ASSET_TYPE_VM_RUNTIME_VM), (None, None)])
        assert cap.supported is True

    def test_gdc_range_with_scenario_pod_is_unsupported_losing_state(self):
        cap = range_pause_resume_capability(
            "gdc", [("gcp", ASSET_TYPE_VM_RUNTIME_VM), ("gcp", ASSET_TYPE_SCENARIO_POD)]
        )
        assert cap.supported is False
        assert ("gcp", ASSET_TYPE_SCENARIO_POD) in cap.unsupported_assets
        assert "losing state" in cap.reason

    def test_cross_adapter_mix_fails_binding(self):
        # A GCE VM realized on a GDC-bound range is not admitted by the binding.
        cap = range_pause_resume_capability("gdc", [("gcp", ASSET_TYPE_VM_RUNTIME_VM), ("gcp", ASSET_TYPE_GCE_VM)])
        assert cap.supported is False
        assert ("gcp", ASSET_TYPE_GCE_VM) in cap.unsupported_assets
        assert "not admitted" in cap.reason

    def test_stale_metadata_against_binding_fails(self):
        # A gce_vm asset on a gce range is fine, but a vm_runtime_vm on a gce
        # range means realized metadata disagrees with the binding -> fail closed.
        cap = range_pause_resume_capability("gce", [("gcp", ASSET_TYPE_VM_RUNTIME_VM)])
        assert cap.supported is False
        assert "not admitted" in cap.reason

    def test_gce_asset_on_aws_binding_fails(self):
        cap = range_pause_resume_capability(None, [("gcp", ASSET_TYPE_GCE_VM)])
        assert cap.supported is False

    def test_unknown_backend_fails_closed(self):
        cap = range_pause_resume_capability("azure", [("azure", "vm")])
        assert cap.supported is False

    def test_unsupported_assets_are_deduped_and_sorted(self):
        cap = range_pause_resume_capability(
            "gdc",
            [
                ("gcp", ASSET_TYPE_SCENARIO_POD),
                ("gcp", ASSET_TYPE_SCENARIO_POD),
                ("gcp", ASSET_TYPE_GCE_VM),
            ],
        )
        assert cap.unsupported_assets == (("gcp", ASSET_TYPE_GCE_VM), ("gcp", ASSET_TYPE_SCENARIO_POD))
