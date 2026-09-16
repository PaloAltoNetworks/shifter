"""Range-backend ownership binding routing + legacy resolution (#1666).

Proves the destroy-after-selector-flip contract: teardown routes from the
per-operation binding resolved from persisted ownership, never the mutable
``GCP_RANGE_BACKEND`` env selector, and legacy (NULL-binding) ranges resolve from
durable ownership evidence or fail closed with a ``prerequisite`` diagnostic.
"""

import os
from unittest.mock import MagicMock, patch

import pytest

_OPERATION_ID = "11111111-2222-3333-4444-555555555555"


def _range_cell_variables():
    """Build an admitted GCE VM range-cell request (mirrors test_range_terraform_runner)."""
    from shared.range_cells import build_gcp_vm_range_cell_request, build_scenario_artifact

    artifact = build_scenario_artifact(
        {
            "spec_schema": "range_spec",
            "spec_version": "1",
            "payload": {"scenario_id": "scenario-a", "user_id": 7, "subnets": []},
        }
    )
    return build_gcp_vm_range_cell_request(
        request_id="req-1",
        range_id=1,
        scenario_artifact=artifact,
        network_bindings=[],
    )


class TestDestroyRoutesFromBinding:
    """destroy_range routes from the explicit binding, overriding the env selector."""

    def test_routing_decision_follows_binding_not_env(self):
        """The gdc/gce routing predicates honor the binding, overriding the env selector.

        Asserts observable routing behavior of the pure predicates rather than
        mocking the first-party gdc destroy runners (ADR-019). A gdc-bound range
        selects the GDC plane even after the deploy selector flips to gce.
        """
        from range_terraform_runner import _uses_active_gdc_range_plane, _uses_gce_range_cells

        with patch.dict(os.environ, {"CLOUD_PROVIDER": "gcp", "GCP_RANGE_BACKEND": "gce"}, clear=True):
            # Binding gdc wins over the gce env selector (destroy-after-flip).
            assert _uses_active_gdc_range_plane("gdc") is True
            assert _uses_gce_range_cells("gdc") is False
            # The reverse binding also wins.
            assert _uses_gce_range_cells("gce") is True
            assert _uses_active_gdc_range_plane("gce") is False
            # With no binding (provision path) it still reads the env selector.
            assert _uses_gce_range_cells() is True

    def test_gce_binding_beats_gdc_env_selector(self):
        """A gce-bound range is torn down through the GCE range cell even if the env selector is gdc."""
        from range_terraform_runner import destroy_range

        variables = _range_cell_variables()
        calls = []
        with patch.dict(os.environ, {"CLOUD_PROVIDER": "gcp", "GCP_RANGE_BACKEND": "gdc"}, clear=True):
            destroy_range(
                "req-1",
                variables=variables,
                gce_destroy_range_cell=lambda rid, v: calls.append((rid, v)),
                backend="gce",
            )

        assert calls == [("req-1", variables)]

    def test_state_key_prefix_and_cleanup_follow_binding(self):
        from range_terraform_runner import get_range_state_key_prefix

        with patch.dict(os.environ, {"CLOUD_PROVIDER": "gcp", "GCP_RANGE_BACKEND": "gce"}, clear=True):
            assert get_range_state_key_prefix(backend="gdc") == "gcp/gdc-ranges"
            assert get_range_state_key_prefix(backend="gce") == "gcp/gce-range-cells"


class TestLegacyBackendFromOperationInput:
    """The Engine resolves the evidence; the provisioner reads only the outcome."""

    def _validated(self, backend):
        from provisioner_db_operation_input import ValidatedOperationInput

        return ValidatedOperationInput(
            operation_id=_OPERATION_ID,
            request_id="req-1",
            resource="range",
            operation="destroy",
            payload={"range_spec": {}, "legacy_range_backend": backend},
        )

    @pytest.mark.parametrize(("backend", "expected"), [("gce", "gce"), ("gdc", "gdc"), (None, None)])
    def test_normalized_outcome_is_passed_through(self, monkeypatch, backend, expected):
        import range_backend_resolution

        monkeypatch.setattr(range_backend_resolution, "get_operation_input", lambda **kwargs: self._validated(backend))
        assert range_backend_resolution._legacy_backend_from_operation_input(_OPERATION_ID, "req-1") == expected

    def test_the_exact_generation_is_requested(self, monkeypatch):
        # Never "latest by request": a retry must resolve the backend its own
        # generation was authorized with.
        import range_backend_resolution

        seen = {}

        def _capture(**kwargs):
            seen.update(kwargs)
            return self._validated("gce")

        monkeypatch.setattr(range_backend_resolution, "get_operation_input", _capture)
        range_backend_resolution._legacy_backend_from_operation_input(_OPERATION_ID, "req-1")
        # Both halves of the compound identity are bound, not just the operation.
        assert seen == {
            "operation_id": _OPERATION_ID,
            "request_id": "req-1",
            "resource": "range",
            "operation": "destroy",
        }

    def test_no_generation_resolves_to_none(self, monkeypatch):
        import range_backend_resolution

        monkeypatch.setattr(range_backend_resolution, "get_operation_input", MagicMock(side_effect=AssertionError))
        assert range_backend_resolution._legacy_backend_from_operation_input(None, "req-1") is None

    def test_an_unreadable_input_fails_closed_rather_than_guessing(self, monkeypatch):
        import range_backend_resolution
        from provisioner_db_operation_input import OperationInputError

        monkeypatch.setattr(
            range_backend_resolution, "get_operation_input", MagicMock(side_effect=OperationInputError("gone"))
        )
        assert range_backend_resolution._legacy_backend_from_operation_input(_OPERATION_ID, "req-1") is None

    def test_an_input_for_another_request_fails_closed(self, monkeypatch):
        # The reader refuses the mismatch; teardown must then deny rather than
        # route this range from another request's backend evidence.
        import range_backend_resolution
        from provisioner_db_operation_input import OperationInputError

        monkeypatch.setattr(
            range_backend_resolution,
            "get_operation_input",
            MagicMock(side_effect=OperationInputError("operation input belongs to a different request")),
        )
        assert range_backend_resolution._legacy_backend_from_operation_input(_OPERATION_ID, "req-other") is None


class TestResolveOperationBackend:
    """_resolve_operation_backend prefers the persisted binding and fails closed on legacy ambiguity."""

    def test_persisted_binding_wins_without_legacy_resolution(self, monkeypatch):
        import range_backend_resolution

        # A persisted binding returns immediately; the input read must never be
        # consulted, and neither must the env-selector path.
        monkeypatch.setattr(range_backend_resolution, "get_operation_input", MagicMock(side_effect=AssertionError))
        monkeypatch.setattr(range_backend_resolution, "resolve_cloud_provider", MagicMock(side_effect=AssertionError))
        result = range_backend_resolution.resolve_operation_backend({"range_backend": "gdc"}, "destroy", _OPERATION_ID)
        assert result == "gdc"

    def test_non_gcp_returns_none(self, monkeypatch):
        import range_backend_resolution

        monkeypatch.setattr(range_backend_resolution, "resolve_cloud_provider", lambda: "aws")
        assert (
            range_backend_resolution.resolve_operation_backend({"range_backend": None}, "destroy", _OPERATION_ID)
            is None
        )

    def test_legacy_destroy_without_evidence_fails_closed(self, monkeypatch):
        from shared.range_instantiation_policy import PREREQUISITE_DENIAL_CODE

        import range_backend_resolution
        from cloud.exceptions import CloudError

        monkeypatch.setattr(range_backend_resolution, "resolve_cloud_provider", lambda: "gcp")
        monkeypatch.setattr(range_backend_resolution, "_legacy_backend_from_operation_input", lambda oid, rid: None)
        with pytest.raises(CloudError) as exc:
            range_backend_resolution.resolve_operation_backend(
                {"range_backend": None, "request_id": "req-1"}, "destroy", _OPERATION_ID
            )
        assert exc.value.code == PREREQUISITE_DENIAL_CODE

    def test_legacy_destroy_without_a_generation_fails_closed(self, monkeypatch):
        # A destroy carrying no canonical generation cannot prove ownership, so
        # it must deny rather than fall back to the mutable env selector (#1666).
        from shared.range_instantiation_policy import PREREQUISITE_DENIAL_CODE

        import range_backend_resolution
        from cloud.exceptions import CloudError

        monkeypatch.setattr(range_backend_resolution, "resolve_cloud_provider", lambda: "gcp")
        with pytest.raises(CloudError) as exc:
            range_backend_resolution.resolve_operation_backend(
                {"range_backend": None, "request_id": "req-1"}, "destroy", None
            )
        assert exc.value.code == PREREQUISITE_DENIAL_CODE

    def test_legacy_destroy_resolves_from_evidence(self, monkeypatch):
        import range_backend_resolution

        monkeypatch.setattr(range_backend_resolution, "resolve_cloud_provider", lambda: "gcp")
        monkeypatch.setattr(range_backend_resolution, "_legacy_backend_from_operation_input", lambda oid, rid: "gdc")
        result = range_backend_resolution.resolve_operation_backend(
            {"range_backend": None, "request_id": "req-1"}, "destroy", _OPERATION_ID
        )
        assert result == "gdc"

    def test_gcp_provision_with_null_binding_fails_closed(self, monkeypatch):
        """A normal GCP provision must consume the persisted admission binding."""
        from shared.range_instantiation_policy import PREREQUISITE_DENIAL_CODE

        import range_backend_resolution
        from cloud.exceptions import CloudError

        monkeypatch.setattr(range_backend_resolution, "resolve_cloud_provider", lambda: "gcp")
        monkeypatch.setattr(
            range_backend_resolution,
            "get_operation_input",
            MagicMock(side_effect=AssertionError),
        )
        with pytest.raises(CloudError) as exc:
            range_backend_resolution.resolve_operation_backend(
                {"range_backend": None},
                "up",
                _OPERATION_ID,
            )
        assert exc.value.code == PREREQUISITE_DENIAL_CODE


class TestProvisionRoutesFromBinding:
    """Provision-time validation and dispatch consume one persisted binding."""

    def test_gce_binding_validates_artifact_when_selector_matches(self, monkeypatch):
        from shared.range_cells import build_scenario_artifact

        import terraform_ops

        artifact = build_scenario_artifact(
            {
                "spec_schema": "range_spec",
                "spec_version": "1",
                "payload": {"scenario_id": "scenario-a", "user_id": 7, "subnets": []},
            }
        )
        dispatch = MagicMock()
        monkeypatch.setattr(
            terraform_ops,
            "get_range_data_by_request_id",
            MagicMock(
                return_value={
                    "request_id": "req-1",
                    "range_id": 1,
                    "user_id": 7,
                    "spec": artifact["payload"],
                    "spec_envelope": artifact,
                    "range_backend": "gce",
                    "instantiation_purpose": "live_fire",
                }
            ),
        )
        monkeypatch.setattr(terraform_ops, "_dispatch_terraform_operation", dispatch)

        with patch.dict(os.environ, {"CLOUD_PROVIDER": "gcp", "GCP_RANGE_BACKEND": "gce"}, clear=True):
            terraform_ops.run_range_terraform("up", "req-1")

        operation = dispatch.call_args.args[1]
        assert operation.backend == "gce"
        assert operation.purpose.value == "live_fire"
        assert operation.scenario_artifact == artifact

    def test_gce_binding_rejects_unknown_purpose_before_dispatch(self, monkeypatch):
        import terraform_ops
        from cloud.exceptions import CloudError

        dispatch = MagicMock()
        monkeypatch.setattr(
            terraform_ops,
            "get_range_data_by_request_id",
            MagicMock(
                return_value={
                    "request_id": "req-1",
                    "range_id": 1,
                    "user_id": 7,
                    "spec": {},
                    "range_backend": "gce",
                    "instantiation_purpose": "unknown-purpose",
                }
            ),
        )
        monkeypatch.setattr(terraform_ops, "_dispatch_terraform_operation", dispatch)
        update_status = MagicMock()
        monkeypatch.setattr(terraform_ops, "update_range_status", update_status)

        with pytest.raises(CloudError) as exc:
            terraform_ops.run_range_terraform("up", "req-1")

        assert getattr(exc.value, "code", None) == "prerequisite"
        dispatch.assert_not_called()
        update_status.assert_not_called()

    def test_unsupported_composition_fails_before_ngfw_or_dispatch(self, monkeypatch):
        from shared.range_cells import build_scenario_artifact
        from shared.range_instantiation_policy import UNSUPPORTED_CAPABILITY_CODE

        import terraform_ops
        from cloud.exceptions import CloudError

        artifact = build_scenario_artifact(
            {
                "spec_schema": "range_spec",
                "spec_version": "1",
                "payload": {
                    "scenario_id": "ngfw-scenario",
                    "user_id": 7,
                    "ngfw": True,
                    "subnets": [],
                },
            }
        )
        dispatch = MagicMock()
        ensure_ngfw = MagicMock()
        monkeypatch.setattr(
            terraform_ops,
            "get_range_data_by_request_id",
            MagicMock(
                return_value={
                    "request_id": "req-1",
                    "range_id": 1,
                    "user_id": 7,
                    "spec": artifact["payload"],
                    "spec_envelope": artifact,
                    "range_backend": "gce",
                    "instantiation_purpose": "live_fire",
                }
            ),
        )
        monkeypatch.setattr(terraform_ops, "_ensure_ngfw_ready_for_provisioning", ensure_ngfw)
        monkeypatch.setattr(terraform_ops, "_dispatch_terraform_operation", dispatch)
        monkeypatch.setattr(terraform_ops, "update_range_status", MagicMock())

        with pytest.raises(CloudError) as exc:
            terraform_ops.run_range_terraform("up", "req-1")

        assert exc.value.code == UNSUPPORTED_CAPABILITY_CODE
        ensure_ngfw.assert_not_called()
        dispatch.assert_not_called()

    def test_provision_pipeline_threads_binding_through_every_backend_seam(self, monkeypatch):
        from shared.range_instantiation_policy import InstantiationPurpose

        import terraform_ops

        build_variables = MagicMock(return_value=_range_cell_variables())
        apply = MagicMock(return_value={"subnets": {}, "instances": []})
        monkeypatch.setattr(terraform_ops, "update_range_status", MagicMock())
        monkeypatch.setattr(terraform_ops, "_build_operation_variables", build_variables)
        monkeypatch.setattr(terraform_ops.range_terraform_runner, "apply_range", apply)
        monkeypatch.setattr(terraform_ops, "_validate_provisioned_outputs", MagicMock())
        monkeypatch.setattr(terraform_ops, "_validate_ngfw_range_attachment", MagicMock())
        monkeypatch.setattr(terraform_ops, "_configure_ngfw_for_range", MagicMock())
        monkeypatch.setattr(terraform_ops, "run_instance_setup", MagicMock())
        monkeypatch.setattr(
            terraform_ops,
            "get_range_data_by_request_id",
            MagicMock(return_value={"ngfw_instance_id": None}),
        )
        monkeypatch.setattr(terraform_ops, "write_provisioned_state", MagicMock())
        monkeypatch.setattr(terraform_ops, "update_range_status", MagicMock())
        operation = terraform_ops.RangeOperation(
            request_id="req-1",
            range_id=1,
            user_id=7,
            range_spec={"subnets": []},
            scenario_artifact={"digest": "bound"},
            backend="gce",
            purpose=InstantiationPurpose.LIVE_FIRE,
        )

        terraform_ops._run_terraform_provision(operation)

        # The range has no authored subnets, so reservation short-circuits and
        # needs no stand-in. Nothing writes realized CIDRs back to the scenario
        # any more (ADR-043-R6), so there is no persistence flag to thread.
        # backend (and the pinned egress posture) ride the per-operation context.
        assert build_variables.call_args.args[4].backend == "gce"
        apply.assert_called_once_with(
            "req-1",
            build_variables.return_value,
            backend="gce",
            purpose=InstantiationPurpose.LIVE_FIRE,
        )
