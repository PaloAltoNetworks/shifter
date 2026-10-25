"""Deployment readback for the three GCP range audit telemetry controls (#2535)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from shared.gcp_range_telemetry import GcpRangeTelemetryPolicy

PROJECT = "acme-shifter"
RANGE_PROJECT = "acme-ranges"
NETWORK = "shifter-dev-range"
NETWORK_URL = f"https://www.googleapis.com/compute/v1/projects/{PROJECT}/global/networks/{NETWORK}"
OTHER_NETWORK_URL = f"https://www.googleapis.com/compute/v1/projects/{PROJECT}/global/networks/shifter-dev-platform"
PER_RANGE_URL = f"https://www.googleapis.com/compute/v1/projects/{RANGE_PROJECT}/global/networks/shifter-range-9"
FLOW_ON = {
    "enable": True,
    "aggregationInterval": "INTERVAL_5_SEC",
    "flowSampling": 0.5,
    "metadata": "INCLUDE_ALL_METADATA",
}
NAT_ON = {"enable": True, "filter": "ALL"}
TF_SUBNET = "shifter-dev-vpn"
TF_ROUTER = "shifter-dev-range-nat"


def load_module():
    path = Path(__file__).resolve().parents[1] / "verify_range_audit_telemetry.py"
    spec = importlib.util.spec_from_file_location("verify_range_audit_telemetry", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _audit(*log_types: str, service: str = "aiplatform.googleapis.com", exempted: list[str] | None = None) -> dict:
    configs = []
    for log_type in log_types:
        entry: dict[str, object] = {"logType": log_type}
        if exempted:
            entry["exemptedMembers"] = exempted
        configs.append(entry)
    return {"service": service, "auditLogConfigs": configs}


def _subnet(name: str, log_config: dict | None = FLOW_ON, network: str = NETWORK_URL) -> dict:
    subnet = {"name": name, "network": network}
    if log_config is not None:
        subnet["logConfig"] = log_config
    return subnet


def _router(name: str, log_config: dict | None = NAT_ON, network: str = NETWORK_URL, gateway: str = "gw") -> dict:
    nat = {"name": gateway}
    if log_config is not None:
        nat["logConfig"] = log_config
    return {"name": name, "network": network, "nats": [nat]}


def _default_subnets() -> list[dict]:
    return [_subnet(TF_SUBNET), _subnet("shifter-r-7-attack"), _subnet("platform-gke", None, OTHER_NETWORK_URL)]


def _default_routers() -> list[dict]:
    return [
        _router(TF_ROUTER),
        _router("shifter-r-7-nat-router"),
        _router("platform-nat", None, OTHER_NETWORK_URL),
    ]


def _readback(*, audit_configs=None, subnets=None, routers=None, range_project=None, fail: str | None = None):
    """Return a fake gcloud runner keyed by the fixed readback command and project."""
    by_project = {
        PROJECT: {
            "subnets": subnets if subnets is not None else _default_subnets(),
            "routers": routers if routers is not None else _default_routers(),
        },
        RANGE_PROJECT: range_project or {"subnets": [], "routers": []},
    }
    policy = {
        "bindings": [{"role": "roles/owner", "members": ["user:x@example.com"]}],
        "auditConfigs": audit_configs if audit_configs is not None else [_audit("DATA_READ", "DATA_WRITE")],
    }
    calls: list[tuple[str, ...]] = []

    def run(*args: str) -> object:
        calls.append(args)
        key = "get-iam-policy" if "get-iam-policy" in args else ("subnets" if "subnets" in args else "routers")
        project = args[args.index("--project") + 1] if "--project" in args else args[-1]
        if fail in {key, f"{key}:{project}"}:
            raise subprocess.CalledProcessError(1, ["gcloud"], stderr="PERMISSION_DENIED token=abc")
        return policy if key == "get-iam-policy" else by_project[project][key]

    run.calls = calls
    return run


def _verify(module, policy=None, *, range_project_id=PROJECT, **readback):
    return module.verify(
        policy or GcpRangeTelemetryPolicy(),
        project_id=PROJECT,
        range_project_id=range_project_id,
        range_network=NETWORK,
        terraform_subnetworks=(TF_SUBNET,),
        terraform_nat_routers=(TF_ROUTER,),
        run=_readback(**readback),
    )


def _by_control(results) -> dict:
    return {result.control: result for result in results}


def _statuses(results) -> dict[str, str]:
    return {result.control: result.status for result in results}


def test_default_policy_passes_when_every_control_is_applied():
    module = load_module()

    results = _by_control(_verify(module))

    assert {name: result.status for name, result in results.items()} == {
        "vertex_data_access_logs": "PASS",
        "vpc_flow_logs": "PASS",
        "nat_logs": "PASS",
    }
    # Platform subnets and routers outside the range placement are not evaluated.
    assert results["vpc_flow_logs"].checked == 2
    assert results["nat_logs"].checked == 2


def test_readback_uses_fixed_argv_with_project_scope():
    module = load_module()
    run = _readback()

    module.verify(
        GcpRangeTelemetryPolicy(),
        project_id=PROJECT,
        range_project_id=RANGE_PROJECT,
        range_network=NETWORK,
        terraform_subnetworks=(),
        terraform_nat_routers=(),
        run=run,
    )

    assert ("projects", "get-iam-policy", PROJECT) in run.calls
    for project in (PROJECT, RANGE_PROJECT):
        assert ("compute", "networks", "subnets", "list", "--project", project) in run.calls
        assert ("compute", "routers", "list", "--project", project) in run.calls
    assert ("projects", "get-iam-policy", RANGE_PROJECT) not in run.calls


@pytest.mark.parametrize(
    "audit_configs",
    [
        [],
        [_audit("DATA_READ")],
        [_audit("ADMIN_READ")],
        [_audit("DATA_READ", "DATA_WRITE", exempted=["serviceAccount:range-host@example.iam.gserviceaccount.com"])],
        [_audit("DATA_READ", "DATA_WRITE", service="secretmanager.googleapis.com")],
    ],
)
def test_vertex_audit_fails_when_data_access_logging_is_missing_or_exempted(audit_configs):
    module = load_module()

    assert _statuses(_verify(module, audit_configs=audit_configs))["vertex_data_access_logs"] == "FAIL"


def test_vertex_audit_accepts_all_services_coverage():
    module = load_module()
    configs = [_audit("DATA_READ", "DATA_WRITE", service="allServices")]

    assert _statuses(_verify(module, audit_configs=configs))["vertex_data_access_logs"] == "PASS"


@pytest.mark.parametrize(
    "log_config",
    [
        None,
        {"enable": False},
        {**FLOW_ON, "flowSampling": 0.1},
        {**FLOW_ON, "aggregationInterval": "INTERVAL_1_MIN"},
        {**FLOW_ON, "metadata": "EXCLUDE_ALL_METADATA"},
    ],
)
def test_terraform_owned_subnet_mismatch_fails_the_deploy(log_config):
    module = load_module()

    results = _verify(module, subnets=[_subnet(TF_SUBNET, log_config), _subnet("shifter-r-7-attack")])

    flow = _by_control(results)["vpc_flow_logs"]
    assert flow.status == "FAIL"
    assert flow.mismatched == (TF_SUBNET,)
    assert module.exit_code(results) == 1


@pytest.mark.parametrize("log_config", [None, {"enable": False}, {"enable": True, "filter": "ERRORS_ONLY"}])
def test_terraform_owned_nat_mismatch_fails_the_deploy(log_config):
    module = load_module()

    results = _verify(module, routers=[_router(TF_ROUTER, log_config), _router("shifter-r-7-nat-router")])

    assert _statuses(results)["nat_logs"] == "FAIL"
    assert module.exit_code(results) == 1


def test_missing_terraform_owned_resource_fails():
    module = load_module()

    results = _verify(module, subnets=[_subnet("shifter-r-7-attack")], routers=[_router("shifter-r-7-nat-router")])

    statuses = _statuses(results)
    assert statuses["vpc_flow_logs"] == "FAIL"
    assert statuses["nat_logs"] == "FAIL"
    assert _by_control(results)["vpc_flow_logs"].mismatched == (f"{TF_SUBNET} (missing)",)


def test_policy_change_reports_existing_ranges_as_pending_reprovision_without_blocking():
    """An operator policy change must deploy: Terraform-owned resources converge in the same
    apply, while existing provisioner-owned range resources converge only when provisioned
    again with the new runtime policy (core-F1)."""
    module = load_module()
    policy = GcpRangeTelemetryPolicy.model_validate({"vpc_flow_logs": {"flow_sampling": 0.1}})
    converged = {**FLOW_ON, "flowSampling": 0.1}

    results = _verify(
        module,
        policy,
        subnets=[_subnet(TF_SUBNET, converged), _subnet("shifter-r-7-attack", FLOW_ON)],
    )

    flow = _by_control(results)["vpc_flow_logs"]
    assert flow.status == "DRIFT"
    assert flow.mismatched == ()
    assert flow.pending_reprovision == ("shifter-r-7-attack",)
    assert module.exit_code(results) == 0


def test_unlogged_existing_ranges_are_reported_on_first_rollout():
    module = load_module()

    results = _verify(
        module,
        subnets=[_subnet(TF_SUBNET), _subnet("shifter-r-7-attack", None)],
        routers=[_router(TF_ROUTER), _router("shifter-r-7-nat-router", None)],
    )

    statuses = _statuses(results)
    assert (statuses["vpc_flow_logs"], statuses["nat_logs"]) == ("DRIFT", "DRIFT")
    assert _by_control(results)["nat_logs"].pending_reprovision == ("shifter-r-7-nat-router/gw",)
    assert module.exit_code(results) == 0


def test_separate_range_project_and_per_range_vpc_are_inventoried():
    """Ranges placed in GCP_RANGE_CELL_PROJECT_ID or in a vpc-per-range network are not
    silently excluded (core-F2)."""
    module = load_module()
    range_project = {
        "subnets": [_subnet("shifter-r-9-lan", None, PER_RANGE_URL), _subnet("other", None, OTHER_NETWORK_URL)],
        "routers": [_router("shifter-r-9-nat-router", None, PER_RANGE_URL)],
    }

    results = _verify(module, range_project_id=RANGE_PROJECT, range_project=range_project)

    flow = _by_control(results)["vpc_flow_logs"]
    nat = _by_control(results)["nat_logs"]
    assert flow.status == "DRIFT" and flow.pending_reprovision == ("shifter-r-9-lan",)
    assert flow.checked == 3
    assert nat.status == "DRIFT" and nat.pending_reprovision == ("shifter-r-9-nat-router/gw",)


def test_unreadable_range_project_is_a_coverage_failure_not_an_empty_deployment():
    module = load_module()

    results = _verify(module, range_project_id=RANGE_PROJECT, fail=f"subnets:{RANGE_PROJECT}")

    flow = _by_control(results)["vpc_flow_logs"]
    assert flow.status == "FAIL"
    assert flow.observed == "readback-failed"


def test_flow_sampling_tolerates_provider_float32_readback():
    module = load_module()
    policy = GcpRangeTelemetryPolicy.model_validate({"vpc_flow_logs": {"flow_sampling": 0.1}})
    readback = {**FLOW_ON, "flowSampling": 0.10000000149}

    results = _verify(module, policy, subnets=[_subnet(TF_SUBNET, readback), _subnet("shifter-r-7-attack", readback)])

    assert _statuses(results)["vpc_flow_logs"] == "PASS"


def test_explicit_operator_override_is_checked_against_the_override():
    module = load_module()
    policy = GcpRangeTelemetryPolicy.model_validate({"nat_logs": {"filter": "ERRORS_ONLY"}})
    errors_only = {"enable": True, "filter": "ERRORS_ONLY"}

    results = _verify(
        module, policy, routers=[_router(TF_ROUTER, errors_only), _router("shifter-r-7-nat-router", errors_only)]
    )

    assert _statuses(results)["nat_logs"] == "PASS"


def test_disabled_controls_report_a_coverage_warning_not_a_pass():
    module = load_module()
    policy = GcpRangeTelemetryPolicy.model_validate(
        {
            "vpc_flow_logs": {"enabled": False},
            "nat_logs": {"enabled": False},
            "vertex_data_access_logs": {"enabled": False},
        }
    )

    results = _verify(module, policy, audit_configs=[])

    assert set(_statuses(results).values()) == {"DISABLED"}
    assert module.exit_code(results) == 0


def test_no_range_resources_yet_is_not_applicable():
    module = load_module()

    results = module.verify(
        GcpRangeTelemetryPolicy(),
        project_id=PROJECT,
        range_project_id=PROJECT,
        range_network=NETWORK,
        terraform_subnetworks=(),
        terraform_nat_routers=(),
        run=_readback(subnets=[], routers=[]),
    )

    statuses = _statuses(results)
    assert (statuses["vpc_flow_logs"], statuses["nat_logs"]) == ("NOT_APPLICABLE", "NOT_APPLICABLE")
    assert module.exit_code(results) == 0


@pytest.mark.parametrize("fail", ["get-iam-policy", "subnets", "routers"])
def test_readback_failure_fails_that_control_without_leaking_provider_output(fail, capsys):
    module = load_module()

    results = _verify(module, fail=fail)
    module.report(results)

    assert "FAIL" in _statuses(results).values()
    assert module.exit_code(results) == 1
    output = capsys.readouterr().out
    assert "PERMISSION_DENIED" not in output
    assert "token" not in output


def test_report_lists_every_control_with_desired_observed_and_pending_state(capsys):
    module = load_module()

    results = _verify(module, subnets=[_subnet(TF_SUBNET), _subnet("shifter-r-7-attack", None)])
    module.report(results)

    lines = capsys.readouterr().out.splitlines()
    assert [line.split(":", 1)[0] for line in lines] == ["vertex_data_access_logs", "vpc_flow_logs", "nat_logs"]
    assert all("desired=" in line and "observed=" in line for line in lines)
    assert "status=DRIFT" in lines[1] and "pending_reprovision=shifter-r-7-attack" in lines[1]
    assert "user:x@example.com" not in "\n".join(lines)


def test_main_loads_the_policy_from_shifter_yaml(tmp_path, monkeypatch, capsys):
    module = load_module()
    config = tmp_path / "shifter.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "backend": "gcp",
                "deployment": {"name": "shifter", "domain": "shifter.example.com"},
                "secrets": {"django_secret_key": "prompt"},
                "settings": {
                    "project_id": PROJECT,
                    "dynamic_secret_project_id": "acme-range-secrets",
                    "region": "us-central1",
                    "range_telemetry": {"nat_logs": {"filter": "ERRORS_ONLY"}},
                },
            }
        )
    )
    errors_only = {"enable": True, "filter": "ERRORS_ONLY"}
    monkeypatch.setattr(module, "_gcloud", _readback(routers=[_router(TF_ROUTER, errors_only)]))

    rc = module.main(
        [
            "--config",
            str(config),
            "--project-id",
            PROJECT,
            "--range-network",
            NETWORK,
            "--terraform-subnetwork",
            TF_SUBNET,
            "--terraform-nat-router",
            TF_ROUTER,
        ]
    )

    assert rc == 0
    assert "nat_logs: status=PASS" in capsys.readouterr().out


def test_gcloud_adapter_uses_fixed_argv_without_a_shell(monkeypatch):
    module = load_module()
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        seen["kwargs"] = kwargs
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps([]), stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    assert module._gcloud("compute", "routers", "list", "--project", PROJECT) == []
    assert seen["argv"] == ["gcloud", "compute", "routers", "list", "--project", PROJECT, "--format=json", "--quiet"]
    assert seen["kwargs"]["check"] is True
    assert "shell" not in seen["kwargs"]
    assert seen["kwargs"]["timeout"] > 0
