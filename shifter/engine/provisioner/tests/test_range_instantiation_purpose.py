"""Provisioner consumes the persisted instantiation purpose (issue #1354, ADR-030).

Before #1354 the provisioner's defense-in-depth policy denial could only be
reached by passing ``purpose`` directly to ``apply_range`` -- a unit seam, not
production authority. These tests drive the real projection-to-route path: the
purpose comes from the locked Engine row, a live-fire GDC provision is denied
before any apply call, an admitted non-user pair proceeds, and a binding that no
longer matches the deploy selector fails closed rather than silently re-routing.
"""

import os
from unittest.mock import patch

import pytest
from shared.range_instantiation_policy import (
    POLICY_DENIAL_CODE,
    PREREQUISITE_DENIAL_CODE,
    InstantiationPurpose,
)


class TestResolveProvisionPurpose:
    def test_persisted_purpose_is_parsed(self):
        import range_backend_resolution

        resolved = range_backend_resolution.resolve_provision_purpose({"instantiation_purpose": "non_user_demo"}, "up")
        assert resolved is InstantiationPurpose.NON_USER_DEMO

    def test_null_binding_defaults_to_live_fire(self):
        # Legacy pre-#1666 and non-GCP rows carry NULL; the strictest reading of
        # "no recorded purpose" is live-fire, so an unbound row gains nothing.
        import range_backend_resolution

        assert range_backend_resolution.resolve_provision_purpose({}, "up") is InstantiationPurpose.LIVE_FIRE
        assert range_backend_resolution.resolve_provision_purpose({"instantiation_purpose": None}, "up") is (
            InstantiationPurpose.LIVE_FIRE
        )

    def test_unknown_purpose_fails_a_provision_closed(self):
        import range_backend_resolution
        from cloud.exceptions import CloudError

        with pytest.raises(CloudError) as exc:
            range_backend_resolution.resolve_provision_purpose({"instantiation_purpose": "bas"}, "up")
        assert exc.value.code == PREREQUISITE_DENIAL_CODE

    def test_destroy_never_parses_the_purpose(self):
        # Purpose is provision-only authority. Teardown routes solely from
        # persisted backend ownership (#1666), so a damaged or forward-version
        # purpose value must never strand owned resources.
        import range_backend_resolution

        assert (
            range_backend_resolution.resolve_provision_purpose({"instantiation_purpose": "bas"}, "destroy")
            is InstantiationPurpose.LIVE_FIRE
        )


class TestDestroyIsNotGatedByPurpose:
    def test_destroy_with_an_unparseable_purpose_still_reaches_teardown(self, monkeypatch):
        import terraform_ops

        dispatched = {}
        monkeypatch.setattr(
            terraform_ops,
            "get_range_data_by_request_id",
            lambda rid: {
                "range_id": 1,
                "user_id": 2,
                "spec": {},
                "request_id": rid,
                "range_backend": "gdc",
                # A forward-version or damaged value the current build cannot parse.
                "instantiation_purpose": "some_future_purpose",
            },
        )
        monkeypatch.setattr(terraform_ops, "_resolve_remote_access_capability", lambda data, op: None)
        monkeypatch.setattr(terraform_ops, "is_gce_range_cell_backend", lambda: False)
        monkeypatch.setattr(
            terraform_ops,
            "_dispatch_terraform_operation",
            lambda op, operation: dispatched.update(operation=op, backend=operation.backend),
        )

        terraform_ops.run_range_terraform("destroy", "req-1")

        assert dispatched == {"operation": "destroy", "backend": "gdc"}


class TestProvisionRouteMatchesTheAdmittedBinding:
    """A selector flip after CMS admission must not silently re-route a provision."""

    def test_mismatched_binding_fails_closed(self):
        import range_backend_resolution
        from cloud.exceptions import CloudError

        with (
            patch.dict(os.environ, {"CLOUD_PROVIDER": "gcp", "GCP_RANGE_BACKEND": "gce"}, clear=True),
            pytest.raises(CloudError) as exc,
        ):
            range_backend_resolution.assert_provision_route("gdc", "up")
        assert exc.value.code == PREREQUISITE_DENIAL_CODE

    def test_matching_binding_is_allowed(self):
        import range_backend_resolution

        with patch.dict(os.environ, {"CLOUD_PROVIDER": "gcp", "GCP_RANGE_BACKEND": "gdc"}, clear=True):
            range_backend_resolution.assert_provision_route("gdc", "up")

    def test_destroy_is_not_gated_by_the_current_selector(self):
        # Teardown routes from ownership (#1666); an owned GDC range must still be
        # destroyable after the deploy selector flips to gce.
        import range_backend_resolution

        with patch.dict(os.environ, {"CLOUD_PROVIDER": "gcp", "GCP_RANGE_BACKEND": "gce"}, clear=True):
            range_backend_resolution.assert_provision_route("gdc", "destroy")

    def test_unbound_and_non_gcp_ranges_are_unaffected(self):
        import range_backend_resolution

        with patch.dict(os.environ, {"CLOUD_PROVIDER": "aws"}, clear=True):
            range_backend_resolution.assert_provision_route(None, "up")


class TestApplyRangeHonorsThePersistedPurpose:
    def _gdc_env(self):
        return patch.dict(os.environ, {"CLOUD_PROVIDER": "gcp", "GCP_RANGE_BACKEND": "gdc"}, clear=True)

    def test_live_fire_gdc_is_denied_before_any_apply(self):
        from cloud.exceptions import CloudError
        from range_terraform_runner import apply_range

        with self._gdc_env(), pytest.raises(CloudError) as exc:
            apply_range("req-1", {}, purpose=InstantiationPurpose.LIVE_FIRE)
        assert exc.value.code == POLICY_DENIAL_CODE

    @pytest.mark.parametrize(
        "purpose",
        [InstantiationPurpose.NON_USER_DEMO, InstantiationPurpose.OPERATOR_VALIDATION],
    )
    def test_an_admitted_non_user_purpose_reaches_the_gdc_route(self, purpose, monkeypatch):
        import gdc_range_networks
        import gdc_scenario_pods
        import gdc_vmruntime_assets
        from range_terraform_runner import apply_range

        monkeypatch.setattr(gdc_range_networks, "apply_range_networks", lambda rid, v: {"subnets": {"a": "b"}})
        monkeypatch.setattr(gdc_vmruntime_assets, "apply_range_assets", lambda rid, v, s: [{"name": "vm"}])
        monkeypatch.setattr(gdc_scenario_pods, "apply_range_assets", lambda rid, v, s: [])

        with self._gdc_env():
            output = apply_range("req-1", {}, purpose=purpose)

        assert output["subnets"] == {"a": "b"}
        assert output["instances"] == [{"name": "vm"}]


class TestRangeOperationCarriesThePurpose:
    def test_provision_passes_the_resolved_purpose_to_apply_range(self, monkeypatch):
        import terraform_ops

        seen = {}

        def _fake_apply(request_uuid, variables, *, purpose=InstantiationPurpose.LIVE_FIRE, backend=None):
            seen["purpose"] = purpose
            seen["backend"] = backend
            raise RuntimeError("stop after the policy-bearing call")

        monkeypatch.setattr(terraform_ops.range_terraform_runner, "apply_range", _fake_apply)
        monkeypatch.setattr(terraform_ops, "update_range_status", lambda **kwargs: None)
        monkeypatch.setattr(terraform_ops, "_reserve_range_subnet_cidrs", lambda *a, **k: {})
        monkeypatch.setattr(terraform_ops, "_build_operation_variables", lambda *a, **k: {})
        monkeypatch.setattr(terraform_ops, "is_gce_range_cell_backend", lambda: False)

        operation = terraform_ops.RangeOperation(
            request_id="req-1",
            range_id=1,
            user_id=2,
            range_spec={},
            backend="gdc",
            purpose=InstantiationPurpose.OPERATOR_VALIDATION,
        )
        with pytest.raises(RuntimeError, match="stop after"):
            terraform_ops._run_terraform_provision(operation)

        assert seen["purpose"] is InstantiationPurpose.OPERATOR_VALIDATION
        assert seen["backend"] == "gdc"

    def test_purpose_defaults_to_live_fire(self):
        import terraform_ops

        operation = terraform_ops.RangeOperation(request_id="req-1", range_id=1, user_id=2, range_spec={})
        assert operation.purpose is InstantiationPurpose.LIVE_FIRE
