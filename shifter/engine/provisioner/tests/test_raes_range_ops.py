"""Tests for the RAES-native range lifecycle entry (ADR-031, ADR-032, ADR-043).

Exercises run_raes_range_provision/destroy after the phase-5 cutover (#1837):
inputs come from the immutable operation-input projection selected by the
canonical ``operation_id``, and outcomes are reported as closed results on the
operation contract instead of published as outbox events. The GCE apply/destroy
and the input read are patched, so this verifies the orchestration flow
(generation fencing, step sequence, failure handling, resolver wiring), not the
cloud calls (covered by test_raes_gcp_apply).
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.operation_results import ResultStep
from shared.raes.content_delivery import DeliveryBinding
from shared.raes.operation_input import RaesOperationInput
from shared.raes.participant_access import ParticipantAccessBinding

import raes_gcp_network_allocation
import raes_range_ops
import range_placement
from config import GCERangeCellConfig, GCERangeImageProfile
from raes_plan import RAES_PROVISIONING_PLAN_CONTRACT_VERSION, RaesPlan, RaesPlanImage, RaesPlanNode

_OPERATION_ID = "11111111-2222-3333-4444-555555555555"
_SHA = "a" * 64


def _serialized_plan() -> dict:
    return {
        "kind": "raes_provisioning_plan",
        "contract_version": RAES_PROVISIONING_PLAN_CONTRACT_VERSION,
        "raes_version": "3.5.0",
        "operation_id": _OPERATION_ID,
        "resources": {
            "net.lan": {
                "address": "net.lan",
                "resource_type": "network",
                "payload": {"name": "lan", "spec": {"infrastructure": {"properties": {"cidr": "10.9.0.0/24"}}}},
            },
            "node.web": {
                "address": "node.web",
                "resource_type": "node",
                "payload": {
                    "name": "web",
                    "os_family": "linux",
                    "spec": {"node": {"source": "ubuntu"}, "infrastructure": {"networks": ["net.lan"]}},
                },
            },
        },
    }


def _open_network_plan() -> dict:
    plan = _serialized_plan()
    plan["resources"].pop("net.lan")
    plan["resources"]["node.web"]["payload"]["spec"]["infrastructure"] = {}
    return plan


_BINDING = DeliveryBinding(
    content_address="content.c",
    sha256=_SHA,
    storage_key=f"raes/content-delivery/aa/{_SHA}",
    byte_count=5,
)


def _run(**overrides):
    from provisioner_db_operation_input import RaesOperationRun

    return RaesOperationRun(operation_id=_OPERATION_ID, request_id="req-1", input=_projection(**overrides))


def _projection(**overrides) -> RaesOperationInput:
    kwargs = {
        "plan": _serialized_plan(),
        "delivery_bindings": (_BINDING,),
        "access_bindings": (),
        "artifact_bindings": (),
        "range_backend": "gce",
        "instantiation_purpose": "live_fire",
        "legacy_range_id": 7,
        "egress_mode": "status-quo",
        "_image_candidates": {},
    }
    kwargs.update(overrides)
    return RaesOperationInput(**kwargs)


@pytest.fixture
def patched(monkeypatch):
    calls = SimpleNamespace(
        apply=MagicMock(
            return_value={
                "operating_systems": [
                    {"instance_key": "node.web#0", "family": "linux", "distribution": "ubuntu", "version": "22.04"}
                ],
                "compute_substrates": [{"instance_key": "node.web#0", "value": "virtual-machine"}],
                "composition_verified_addresses": [],
                "instances": [],
            }
        ),
        destroy=MagicMock(),
        config=MagicMock(name="gce_config"),
        load_config=MagicMock(),
        append=MagicMock(),
        read_input=MagicMock(side_effect=lambda *a, **k: _run()),
        get_range_data=MagicMock(return_value={"subnet_index": 1, "placement_zone": ""}),
        reserve_subnet=MagicMock(
            return_value={
                "subnets": [
                    {
                        "uuid": "backend.gce.network.default",
                        "name": "backend-default",
                        "cidr": "10.90.0.0/28",
                    }
                ]
            }
        ),
        read_subnet=MagicMock(
            return_value={
                "subnets": [
                    {
                        "uuid": "backend.gce.network.default",
                        "name": "backend-default",
                        "cidr": "10.90.0.0/28",
                    }
                ]
            }
        ),
        release_subnet=MagicMock(),
    )
    calls.load_config.return_value = calls.config
    monkeypatch.setattr(raes_range_ops, "get_raes_operation_input", calls.read_input)
    monkeypatch.setattr(raes_range_ops, "load_gce_range_cell_config", calls.load_config)
    # Placement is read from the range row in range_placement; stub the DB read
    # there so the RAES lifecycle never touches the real database.
    monkeypatch.setattr(range_placement, "get_range_data_by_request_id", calls.get_range_data)
    monkeypatch.setattr(raes_range_ops, "apply_raes_range_cell", calls.apply)
    monkeypatch.setattr(raes_range_ops, "destroy_raes_range_cell", calls.destroy)
    monkeypatch.setattr(raes_range_ops, "append_operation_step_result", calls.append)
    monkeypatch.setattr(raes_gcp_network_allocation, "_reserve_range_subnet_cidrs", calls.reserve_subnet)
    monkeypatch.setattr(raes_gcp_network_allocation, "_realized_range_spec_for_destroy", calls.read_subnet)
    monkeypatch.setattr(raes_range_ops, "_release_subnet_allocations_best_effort", calls.release_subnet)
    return calls


def _steps(calls) -> list[str]:
    return [str(call.kwargs["step"]) for call in calls.append.call_args_list]


def _payload_for(calls, step: ResultStep) -> dict:
    for call in calls.append.call_args_list:
        if call.kwargs["step"] is step:
            return call.kwargs["result_payload"]
    raise AssertionError(f"no result appended for step {step}")


class TestGenerationFence:
    def test_provision_without_a_generation_fails_before_any_cloud_work(self, patched):
        # An RAES cloud mutation with no canonical operation id has no input to
        # read and no fence to report against; it must refuse, not fall back.
        with pytest.raises(raes_range_ops.RaesGenerationError):
            raes_range_ops.run_raes_range_provision("req-1", operation_id=None)
        assert not patched.apply.called
        assert not patched.read_input.called
        assert not patched.append.called

    def test_destroy_without_a_generation_fails_before_any_cloud_work(self, patched):
        with pytest.raises(raes_range_ops.RaesGenerationError):
            raes_range_ops.run_raes_range_destroy("req-1", operation_id=None)
        assert not patched.destroy.called
        assert not patched.append.called

    def test_input_is_read_for_this_generation_and_operation(self, patched):
        raes_range_ops.run_raes_range_provision("req-1", operation_id=_OPERATION_ID)
        patched.read_input.assert_called_once_with(_OPERATION_ID, request_id="req-1", operation="provision")


class TestProvision:
    def test_reports_running_snapshot_then_ready(self, patched):
        raes_range_ops.run_raes_range_provision("req-1", operation_id=_OPERATION_ID)
        assert _steps(patched) == [
            ResultStep.RAES_PROVISION_RUNNING,
            ResultStep.RAES_PROVISION_SNAPSHOT,
            ResultStep.RAES_TERMINAL_READY,
        ]

    def test_open_network_uses_shared_vpc_allocator_before_apply(self, patched):
        patched.config.network_mode = "shared-vpc"
        patched.read_input.side_effect = lambda *a, **k: _run(plan=_open_network_plan())

        raes_range_ops.run_raes_range_provision("req-1", operation_id=_OPERATION_ID)

        patched.reserve_subnet.assert_called_once_with(
            "req-1",
            raes_gcp_network_allocation._OPEN_NETWORK_SPEC,
            operation_id=_OPERATION_ID,
        )
        assert patched.apply.call_args.kwargs["options"].allocated_network_cidr == "10.90.0.0/28"

    def test_failed_open_network_apply_retains_shared_vpc_allocation_for_cleanup(self, patched):
        patched.config.network_mode = "shared-vpc"
        patched.read_input.side_effect = lambda *a, **k: _run(plan=_open_network_plan())
        patched.apply.side_effect = RuntimeError("apply failed")

        with pytest.raises(RuntimeError, match="apply failed"):
            raes_range_ops.run_raes_range_provision("req-1", operation_id=_OPERATION_ID)

        patched.release_subnet.assert_not_called()

    def test_the_terminal_result_carries_the_realized_access_projection(self, patched):
        """One generation, one atomic apply: READY carries its own realized state."""
        patched.apply.return_value = {
            "operating_systems": [
                {"instance_key": "node.web#0", "family": "linux", "distribution": "ubuntu", "version": "22.04"}
            ],
            "compute_substrates": [{"instance_key": "node.web#0", "value": "virtual-machine"}],
            "composition_verified_addresses": [],
            "instances": [
                {
                    "uuid": "node.web#0",
                    "name": "web",
                    "os": "linux",
                    "private_ip": "10.9.0.10",
                    "instance_id": "shifter-r-7-lan-web",
                    "subnet_name": "lan",
                    "participant_access_channels": ["ssh"],
                    "participant_access_usernames": {"ssh": "analyst"},
                    "ssh_key_secret_arn": "projects/p/secrets/ssh",
                    "gcp_host_public_key": "ssh-ed25519 AAAA",
                }
            ],
        }
        raes_range_ops.run_raes_range_provision("req-1", operation_id=_OPERATION_ID)
        members = _payload_for(patched, ResultStep.RAES_TERMINAL_READY)["members"]
        assert members == [
            {
                "uuid": "node.web#0",
                "name": "web",
                "os_type": "linux",
                "private_ip": "10.9.0.10",
                "instance_id": "shifter-r-7-lan-web",
                "subnet_name": "lan",
                "participant_access_channels": ["ssh"],
                "participant_access_usernames": {"ssh": "analyst"},
                "host_public_key": "ssh-ed25519 AAAA",
                "ssh_key_secret_arn": "projects/p/secrets/ssh",
            }
        ]

    def test_members_carry_declared_sftp_root_directory(self, patched):
        """A realized instance's SFTP root reaches the member projection (#375)."""
        patched.apply.return_value = {
            "operating_systems": [
                {"instance_key": "node.web#0", "family": "linux", "distribution": "ubuntu", "version": "22.04"}
            ],
            "compute_substrates": [{"instance_key": "node.web#0", "value": "virtual-machine"}],
            "composition_verified_addresses": [],
            "instances": [
                {
                    "uuid": "node.web#0",
                    "name": "web",
                    "os": "kali",
                    "private_ip": "10.9.0.10",
                    "instance_id": "shifter-r-7-lan-web",
                    "subnet_name": "lan",
                    "participant_access_channels": ["ssh"],
                    "participant_access_usernames": {"ssh": "analyst"},
                    "ssh_key_secret_arn": "projects/p/secrets/ssh",
                    "sftp_root_directory": "/home/kali",
                }
            ],
        }
        raes_range_ops.run_raes_range_provision("req-1", operation_id=_OPERATION_ID)
        members = _payload_for(patched, ResultStep.RAES_TERMINAL_READY)["members"]
        assert members[0]["sftp_root_directory"] == "/home/kali"

    def test_members_omit_sftp_root_directory_when_absent(self, patched):
        """No declared root emits no key rather than an empty guess (#375)."""
        patched.apply.return_value = {
            "operating_systems": [
                {"instance_key": "node.web#0", "family": "linux", "distribution": "ubuntu", "version": "22.04"}
            ],
            "compute_substrates": [{"instance_key": "node.web#0", "value": "virtual-machine"}],
            "composition_verified_addresses": [],
            "instances": [
                {
                    "uuid": "node.web#0",
                    "name": "web",
                    "os": "linux",
                    "private_ip": "10.9.0.10",
                    "instance_id": "shifter-r-7-lan-web",
                    "subnet_name": "lan",
                    "participant_access_channels": ["ssh"],
                    "participant_access_usernames": {"ssh": "analyst"},
                    "ssh_key_secret_arn": "projects/p/secrets/ssh",
                }
            ],
        }
        raes_range_ops.run_raes_range_provision("req-1", operation_id=_OPERATION_ID)
        members = _payload_for(patched, ResultStep.RAES_TERMINAL_READY)["members"]
        assert "sftp_root_directory" not in members[0]

    def test_members_never_carry_the_management_secret_reference(self, patched):
        """The provisioner-managed host key secret is not a participant credential."""
        patched.apply.return_value = {
            "operating_systems": [
                {"instance_key": "node.web#0", "family": "linux", "distribution": "ubuntu", "version": "22.04"}
            ],
            "compute_substrates": [{"instance_key": "node.web#0", "value": "virtual-machine"}],
            "composition_verified_addresses": [],
            "instances": [
                {
                    "uuid": "node.web#0",
                    "name": "web",
                    "os": "linux",
                    "private_ip": "10.9.0.10",
                    "instance_id": "shifter-r-7-lan-web",
                    "subnet_name": "lan",
                    "participant_access_channels": [],
                    "participant_access_usernames": {},
                    "gcp_host_ssh_key_secret_ref": "projects/p/secrets/management",
                }
            ],
        }
        raes_range_ops.run_raes_range_provision("req-1", operation_id=_OPERATION_ID)
        members = _payload_for(patched, ResultStep.RAES_TERMINAL_READY)["members"]
        assert "projects/p/secrets/management" not in str(members)

    def test_forwards_the_parsed_plan_from_the_projection(self, patched):
        raes_range_ops.run_raes_range_provision("req-1", operation_id=_OPERATION_ID)
        request_id, range_id, raes_plan = patched.apply.call_args.args[:3]
        # The legacy integer range id is the cloud/secret naming key only; it
        # comes from the projection, never from a domain-table read.
        assert (request_id, range_id) == ("req-1", 7)
        # The *parsed* RaesPlan is forwarded to realization, not the raw dict --
        # a refactor that skipped parse_plan before dispatch must fail here.
        assert isinstance(raes_plan, RaesPlan)
        assert [n.address for n in raes_plan.nodes] == ["node.web"]
        patched.load_config.assert_called_once_with(backend="gce")
        assert patched.apply.call_args.kwargs["options"].config is patched.config

    def test_forwards_the_pinned_egress_mode_from_the_projection(self, patched):
        # The pinned egress posture rides the operation input and must reach the
        # realizer; dropping it would silently give the range the default posture.
        patched.read_input.side_effect = lambda *a, **k: _run(egress_mode="none")
        raes_range_ops.run_raes_range_provision("req-1", operation_id=_OPERATION_ID)
        assert patched.apply.call_args.kwargs["options"].egress_mode == "none"

    def test_forwards_content_delivery_bindings_from_the_projection(self, patched):
        # #1564: the bindings gate + realize source-backed content delivery. They
        # now ride the immutable input rather than a live binding-table read.
        raes_range_ops.run_raes_range_provision("req-1", operation_id=_OPERATION_ID)
        assert patched.apply.call_args.kwargs["delivery_bindings"] == [_BINDING.to_transport()]

    def test_forwards_participant_access_bindings_from_the_projection(self, patched):
        # #1710: the sidecar gates + realizes participant access. Fabricating
        # apply's return value proves nothing about the input reaching it.
        binding = ParticipantAccessBinding(
            target_address="node.web",
            channel="ssh",
            account_address="acct.analyst",
        )
        patched.read_input.side_effect = lambda *a, **k: _run(access_bindings=(binding,))
        raes_range_ops.run_raes_range_provision("req-1", operation_id=_OPERATION_ID)
        assert patched.apply.call_args.kwargs["access_bindings"] == [binding.to_transport()]

    def test_snapshot_carries_the_bounded_plan_resources(self, patched):
        raes_range_ops.run_raes_range_provision("req-1", operation_id=_OPERATION_ID)
        resources = _payload_for(patched, ResultStep.RAES_PROVISION_SNAPSHOT)["resources"]
        assert {r["resource_type"] for r in resources} == {"network", "node"}

    def test_results_are_appended_under_the_raes_resource(self, patched):
        raes_range_ops.run_raes_range_provision("req-1", operation_id=_OPERATION_ID)
        for call in patched.append.call_args_list:
            assert call.kwargs["resource"] == "raes-range"
            assert call.kwargs["operation"] == "provision"
            assert call.args[0].operation_id == _OPERATION_ID


class TestProvisionFailure:
    def test_failure_reports_a_closed_reason_code_and_reraises(self, patched):
        patched.apply.side_effect = RuntimeError("gce insert 409 for projects/secret/instances/x")
        with pytest.raises(RuntimeError):
            raes_range_ops.run_raes_range_provision("req-1", operation_id=_OPERATION_ID)

        payload = _payload_for(patched, ResultStep.RAES_TERMINAL_FAILED)
        assert payload["reason_code"] == "cloud_operation_failed"
        assert ResultStep.RAES_TERMINAL_READY not in _steps(patched)
        assert ResultStep.RAES_PROVISION_SNAPSHOT not in _steps(patched)

    def test_failure_diagnostic_is_bounded(self, patched):
        patched.apply.side_effect = RuntimeError("x" * 5000)
        with pytest.raises(RuntimeError):
            raes_range_ops.run_raes_range_provision("req-1", operation_id=_OPERATION_ID)
        assert len(_payload_for(patched, ResultStep.RAES_TERMINAL_FAILED)["diagnostic"]) <= 512

    def test_provider_message_never_reaches_the_durable_diagnostic(self, patched):
        # RAES failures cross provider, storage, content-delivery, and guest
        # code whose messages carry response bodies, resource ids, storage
        # references, signed URLs, and guest output. The result inbox is a
        # durable cross-service channel; truncation bounds size, not
        # confidentiality. Only authored text may cross.
        secret = "https://storage.example/bucket/obj?X-Goog-Signature=deadbeef"
        patched.apply.side_effect = RuntimeError(f"insert failed for projects/acme-prod/instances/db1: {secret}")
        with pytest.raises(RuntimeError):
            raes_range_ops.run_raes_range_provision("req-1", operation_id=_OPERATION_ID)

        diagnostic = _payload_for(patched, ResultStep.RAES_TERMINAL_FAILED)["diagnostic"]
        for leaked in ("X-Goog-Signature", "deadbeef", "acme-prod", "storage.example", "db1"):
            assert leaked not in diagnostic

    def test_destroy_diagnostic_is_authored_too(self, patched):
        # Same category, other entry point: a fix applied only to provision
        # would leave this channel open.
        patched.destroy.side_effect = RuntimeError("teardown failed for projects/acme-prod/instances/db1")
        with pytest.raises(RuntimeError):
            raes_range_ops.run_raes_range_destroy("req-1", operation_id=_OPERATION_ID)

        diagnostic = _payload_for(patched, ResultStep.RAES_TERMINAL_FAILED)["diagnostic"]
        assert "acme-prod" not in diagnostic
        assert "db1" not in diagnostic

    def test_diagnostic_still_identifies_the_failure_type_for_triage(self, patched):
        # An exception class name is a code identifier, not runtime data, so it
        # can cross while the message cannot.
        patched.apply.side_effect = TimeoutError("waited on projects/acme-prod/operations/op-9")
        with pytest.raises(TimeoutError):
            raes_range_ops.run_raes_range_provision("req-1", operation_id=_OPERATION_ID)

        payload = _payload_for(patched, ResultStep.RAES_TERMINAL_FAILED)
        assert payload["reason_code"] == "cloud_timeout"
        assert "acme-prod" not in payload["diagnostic"]

    def test_malformed_composition_proof_fails_before_snapshot_or_ready(self, patched):
        patched.apply.return_value = {"composition_verified_addresses": "content.inline"}

        with pytest.raises(ValueError, match="verification proof is invalid"):
            raes_range_ops.run_raes_range_provision("req-1", operation_id=_OPERATION_ID)

        assert ResultStep.RAES_PROVISION_SNAPSHOT not in _steps(patched)
        assert ResultStep.RAES_TERMINAL_READY not in _steps(patched)
        assert ResultStep.RAES_TERMINAL_FAILED in _steps(patched)

    def test_an_invalid_input_projection_stops_before_cloud_work(self, patched):
        import provisioner_db_operation_input as reader

        patched.read_input.side_effect = reader.OperationInputError("tampered binding")
        with pytest.raises(reader.OperationInputError):
            raes_range_ops.run_raes_range_provision("req-1", operation_id=_OPERATION_ID)
        assert not patched.apply.called

    def test_an_unreadable_input_still_reports_a_terminal_failure(self, patched):
        # ADR-043-R7: an operation generation that never reports a terminal
        # result is only visible through a lag signal. We hold the generation
        # from argv, so we can fail the range explicitly instead of leaving it
        # stuck until an operator notices.
        import provisioner_db_operation_input as reader

        patched.read_input.side_effect = reader.OperationInputError("no input row")
        with pytest.raises(reader.OperationInputError):
            raes_range_ops.run_raes_range_provision("req-1", operation_id=_OPERATION_ID)

        assert _steps(patched) == [ResultStep.RAES_TERMINAL_FAILED]
        assert _payload_for(patched, ResultStep.RAES_TERMINAL_FAILED)["reason_code"] == "dependency_unavailable"

    def test_an_unreadable_input_reports_no_raw_diagnostic_detail(self, patched):
        import provisioner_db_operation_input as reader

        patched.read_input.side_effect = reader.OperationInputError("relation engine_operation_input does not exist")
        with pytest.raises(reader.OperationInputError):
            raes_range_ops.run_raes_range_provision("req-1", operation_id=_OPERATION_ID)

        diagnostic = _payload_for(patched, ResultStep.RAES_TERMINAL_FAILED)["diagnostic"]
        assert "engine_operation_input" not in diagnostic

    @pytest.mark.parametrize(
        ("backend", "purpose", "code"),
        [
            (None, "live_fire", "prerequisite"),
            ("gdc", "live_fire", "identity-or-policy"),
            ("gce", None, "prerequisite"),
            ("gce", "non_user_validation", "identity-or-policy"),
        ],
    )
    def test_rejects_non_gce_live_fire_binding_before_apply(
        self,
        monkeypatch,
        patched,
        backend,
        purpose,
        code,
    ):
        from cloud.exceptions import CloudError

        patched.read_input.side_effect = lambda *a, **k: _run(
            range_backend=backend,
            instantiation_purpose=purpose,
        )

        with pytest.raises(CloudError) as exc:
            raes_range_ops.run_raes_range_provision("req-1", operation_id=_OPERATION_ID)

        assert exc.value.code == code
        patched.apply.assert_not_called()
        patched.load_config.assert_not_called()


class TestDestroy:
    def test_reports_running_then_destroyed(self, patched):
        raes_range_ops.run_raes_range_destroy("req-1", operation_id=_OPERATION_ID)
        assert _steps(patched) == [ResultStep.RAES_DESTROY_RUNNING, ResultStep.RAES_TERMINAL_DESTROYED]

    def test_open_network_reuses_and_releases_shared_vpc_allocation(self, patched):
        patched.config.network_mode = "shared-vpc"
        patched.read_input.side_effect = lambda *a, **k: _run(plan=_open_network_plan())

        raes_range_ops.run_raes_range_destroy("req-1", operation_id=_OPERATION_ID)

        patched.read_subnet.assert_called_once_with(
            "req-1",
            raes_gcp_network_allocation._OPEN_NETWORK_SPEC,
            operation_id=_OPERATION_ID,
        )
        assert patched.destroy.call_args.args[3].allocated_network_cidr == "10.90.0.0/28"
        patched.release_subnet.assert_called_once_with("req-1", operation_id=_OPERATION_ID)

    def test_open_network_without_a_reservation_still_converges_destroy(self, patched):
        patched.config.network_mode = "shared-vpc"
        patched.read_input.side_effect = lambda *a, **k: _run(plan=_open_network_plan())
        patched.read_subnet.return_value = raes_gcp_network_allocation._OPEN_NETWORK_SPEC

        raes_range_ops.run_raes_range_destroy("req-1", operation_id=_OPERATION_ID)

        options = patched.destroy.call_args.args[3]
        assert options.allocated_network_cidr is None
        assert options.reconstruct_without_allocation is True
        patched.release_subnet.assert_not_called()
        assert _steps(patched)[-1] == ResultStep.RAES_TERMINAL_DESTROYED

    def test_forwards_the_parsed_plan(self, patched):
        raes_range_ops.run_raes_range_destroy("req-1", operation_id=_OPERATION_ID)
        request_id, range_id, raes_plan = patched.destroy.call_args.args[:3]
        assert (request_id, range_id) == ("req-1", 7)
        assert isinstance(raes_plan, RaesPlan)
        assert [n.address for n in raes_plan.nodes] == ["node.web"]
        patched.load_config.assert_called_once_with(backend="gce")
        assert patched.destroy.call_args.args[3].config is patched.config

    def test_failure_reports_a_closed_reason_code_and_reraises(self, patched):
        patched.destroy.side_effect = RuntimeError("kaboom")
        with pytest.raises(RuntimeError, match="kaboom"):
            raes_range_ops.run_raes_range_destroy("req-1", operation_id=_OPERATION_ID)
        assert _payload_for(patched, ResultStep.RAES_TERMINAL_FAILED)["reason_code"] == "cloud_operation_failed"
        assert ResultStep.RAES_TERMINAL_DESTROYED not in _steps(patched)

    def test_rejects_non_gce_binding_before_destroy(self, patched):
        from cloud.exceptions import CloudError

        patched.read_input.side_effect = lambda *a, **k: _run(
            range_backend="gdc",
            instantiation_purpose="live_fire",
        )

        with pytest.raises(CloudError) as exc:
            raes_range_ops.run_raes_range_destroy("req-1", operation_id=_OPERATION_ID)

        assert exc.value.code == "identity-or-policy"
        patched.destroy.assert_not_called()
        patched.load_config.assert_not_called()


def _node(image: RaesPlanImage | None) -> RaesPlanNode:
    return RaesPlanNode(
        address="node.web", name="web", os_family="linux", count=1, network_addresses=("net.lan",), image=image
    )


class TestRegistryResolver:
    """The resolver now reads candidates from the projection, not the registry table."""

    def test_resolver_wires_projected_candidates_to_policy(self, monkeypatch):
        candidates = [{"source_version": None, "image_ref": "projects/x/global/images/ubuntu-1"}]
        projection = _projection(_image_candidates={"gce:ubuntu": tuple(candidates)})
        resolve = MagicMock(return_value=GCERangeImageProfile(source_image="projects/x/global/images/ubuntu-1"))
        monkeypatch.setattr(raes_range_ops, "resolve_gce_image", resolve)

        node = _node(RaesPlanImage(name="ubuntu"))
        profile = raes_range_ops._registry_resolver(projection)(node)

        resolve.assert_called_once_with(node, candidates)
        assert profile.source_image == "projects/x/global/images/ubuntu-1"

    def test_resolver_uses_os_family_for_source_less_node(self, monkeypatch):
        # A source-less node looks up a base OS image by os_family (ADR-032).
        candidates = [{"source_version": "", "image_ref": "projects/x/global/images/ubuntu-base"}]
        projection = _projection(_image_candidates={"gce:linux": tuple(candidates)})
        resolve = MagicMock(return_value=GCERangeImageProfile())
        monkeypatch.setattr(raes_range_ops, "resolve_gce_image", resolve)

        node = _node(None)  # os_family linux, no image
        raes_range_ops._registry_resolver(projection)(node)

        resolve.assert_called_once_with(node, candidates)

    def test_a_source_with_no_projected_candidates_resolves_empty(self, monkeypatch):
        # Fail-loud stays with the existing image policy, which receives an empty
        # candidate list exactly as the direct read produced for an unmapped source.
        resolve = MagicMock(return_value=GCERangeImageProfile())
        monkeypatch.setattr(raes_range_ops, "resolve_gce_image", resolve)

        raes_range_ops._registry_resolver(_projection())(_node(RaesPlanImage(name="nope")))

        resolve.assert_called_once_with(_node(RaesPlanImage(name="nope")), [])

    def test_resolver_consumes_a_fenced_artifact_binding(self, monkeypatch):
        # A generation-fenced binding for the node realizes its image verbatim and
        # never touches the legacy registry-projection resolver (#1580, ADR-034-R8).
        from shared.raes.artifact_binding import ArtifactBinding

        binding = ArtifactBinding(
            target="node.web",
            requirement_id="r",
            artifact_id="img-web",
            version="1.0.0",
            digest="sha256:" + "a" * 64,
            media_type="application/vnd.raes.image",
            mechanism="exact-artifact",
            acquisition="local-lookup",
            timing="backend-preparation",
            image_ref="projects/x/global/images/fenced",
            machine_type="e2-medium",
        )
        legacy_candidate = {"source_version": None, "image_ref": "projects/x/global/images/legacy"}
        projection = _projection(
            artifact_bindings=(binding,),
            _image_candidates={"gce:ubuntu": (legacy_candidate,)},
        )
        legacy = MagicMock()
        monkeypatch.setattr(raes_range_ops, "resolve_gce_image", legacy)

        profile = raes_range_ops._registry_resolver(projection)(_node(RaesPlanImage(name="ubuntu")))

        legacy.assert_not_called()
        assert profile.source_image == "projects/x/global/images/fenced"
        assert profile.machine_type == "e2-medium"


class TestMultiRegionZonePoolPlacement:
    """The RAES lifecycle binds the pooled zone into the config it hands the
    apply/destroy realizers -- the same seam the legacy lifecycle uses, so the
    feature fires on the RAES-native path too. Placement is derived from the
    range's persisted allocation slot (``subnet_index - 1``), so provision and
    destroy resolve the same zone.
    """

    @staticmethod
    def _pooled_config() -> GCERangeCellConfig:
        return GCERangeCellConfig(
            project_id="proj",
            region="us-central1",
            zone="us-central1-a",
            network_mode="shared-vpc",
            network_id="projects/proj/global/networks/range",
        )

    def test_provision_binds_the_stored_placement_zone(self, patched):
        patched.load_config.return_value = self._pooled_config()
        patched.get_range_data.return_value = {"subnet_index": 2, "placement_zone": "us-east4-a"}

        raes_range_ops.run_raes_range_provision("req-1", operation_id=_OPERATION_ID)

        bound = patched.apply.call_args.kwargs["options"].config
        assert (bound.zone, bound.region) == ("us-east4-a", "us-east4")

    def test_destroy_binds_the_same_stored_zone(self, patched):
        patched.load_config.return_value = self._pooled_config()
        patched.get_range_data.return_value = {"subnet_index": 2, "placement_zone": "us-east4-a"}

        raes_range_ops.run_raes_range_destroy("req-1", operation_id=_OPERATION_ID)

        bound = patched.destroy.call_args.args[3].config
        assert (bound.zone, bound.region) == ("us-east4-a", "us-east4")

    def test_no_stored_placement_leaves_the_configured_scalar_zone(self, patched):
        patched.load_config.return_value = self._pooled_config()
        patched.get_range_data.return_value = {"subnet_index": 2, "placement_zone": ""}

        raes_range_ops.run_raes_range_provision("req-1", operation_id=_OPERATION_ID)

        bound = patched.apply.call_args.kwargs["options"].config
        assert (bound.zone, bound.region) == ("us-central1-a", "us-central1")
