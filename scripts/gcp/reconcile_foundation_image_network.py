"""Reconcile only the foundation image network through a tenant deploy run."""

from __future__ import annotations

import json
import os
import subprocess  # nosec B404 - only the fixed Terraform and gcloud CLIs are invoked.
import sys
import tempfile
from pathlib import Path

from check_image_network_plan import _MODULE_PREFIX, _RESOURCES, validate_plan

_ROOT = Path(__file__).resolve().parents[2] / "platform/terraform/gcp/global/cicd-oidc"


def _run(command: list[str], *, env: dict[str, str]) -> str:
    result = subprocess.run(  # nosec B603 - argv only, with no shell or executable from input.
        command, capture_output=True, text=True, check=False, env=env
    )
    if result.returncode:
        # Terraform's plan and state output can contain sensitive foundation
        # values. Keep diagnostics on the runner; never emit them to Actions.
        operation = next(
            (part for part in command[1:] if part in {"init", "plan", "show", "apply", "state"}), command[1]
        )
        raise RuntimeError(f"{command[0]} {operation} failed with exit code {result.returncode}")
    return result.stdout


def _cloud_json(args: list[str], project_id: str, env: dict[str, str]) -> dict:
    return json.loads(_run(["gcloud", "compute", *args, f"--project={project_id}", "--format=json"], env=env))


def _verify_live_network(
    project_id: str, environment: str, region: str, subnet_cidr: str, env: dict[str, str]
) -> list[str]:
    prefix = f"shifter-{environment}-image-build"
    network = _cloud_json(["networks", "describe", prefix], project_id, env)
    subnet = _cloud_json(["networks", "subnets", "describe", prefix, f"--region={region}"], project_id, env)
    router = _cloud_json(["routers", "describe", prefix, f"--region={region}"], project_id, env)
    builder_firewall = _cloud_json(["firewall-rules", "describe", f"{prefix}-iap"], project_id, env)
    validator_firewall = _cloud_json(
        ["firewall-rules", "describe", f"shifter-{environment}-image-validate-iap"], project_id, env
    )
    if network.get("name") != prefix or subnet.get("name") != prefix or router.get("name") != prefix:
        raise ValueError("Foundation image-build network, subnet, or router name does not match the selected tenant")
    if network.get("autoCreateSubnetworks") is not False or network.get("peerings"):
        raise ValueError("Foundation image-build VPC has unexpected subnet or peering configuration")
    nats = [nat for nat in router.get("nats") or [] if nat.get("name") == prefix]
    if len(nats) != 1 or nats[0].get("natIpAllocateOption") != "AUTO_ONLY":
        raise ValueError("Foundation image-build Cloud NAT is missing")
    if not any(item.get("name", "").endswith(f"/subnetworks/{prefix}") for item in nats[0].get("subnetworks") or []):
        raise ValueError("Foundation image-build Cloud NAT does not cover the build subnet")
    if (
        not subnet.get("network", "").endswith(f"/networks/{prefix}")
        or subnet.get("ipCidrRange") != subnet_cidr
        or subnet.get("privateIpGoogleAccess") is not True
    ):
        raise ValueError("Foundation image-build subnet is on the wrong network")
    if not router.get("network", "").endswith(f"/networks/{prefix}"):
        raise ValueError("Foundation image-build router is on the wrong network")
    for firewall in (builder_firewall, validator_firewall):
        if (
            not firewall.get("network", "").endswith(f"/networks/{prefix}")
            or firewall.get("sourceRanges") != ["35.235.240.0/20"]
            or firewall.get("direction") != "INGRESS"
        ):
            raise ValueError("Foundation image-build firewall is on the wrong network")
    expected_builder = f"{('shifter-' + environment).replace('-', '')}-packer@{project_id}.iam.gserviceaccount.com"
    if builder_firewall.get("targetServiceAccounts") != [expected_builder]:
        raise ValueError("Foundation image-build firewall targets the wrong build identity")
    if validator_firewall.get("targetTags") != ["shifter-validation"] or validator_firewall.get("allowed") != [
        {"IPProtocol": "tcp", "ports": ["22", "389", "2222"]}
    ]:
        raise ValueError("Foundation image validation firewall has unexpected targeting or ports")
    allowed = builder_firewall.get("allowed") or []
    if len(allowed) != 1 or allowed[0].get("IPProtocol") != "tcp":
        raise ValueError("Foundation image-build IAP firewall has unexpected rules")
    ports = allowed[0].get("ports") or []
    if ports not in (["22", "5986"], ["22", "2222", "5986"]):
        raise ValueError("Foundation image-build IAP firewall has unexpected ports")
    return ports


def reconcile() -> None:
    environment = os.environ["GCP_ENVIRONMENT"]
    project_id = os.environ["GCP_PROJECT_ID"]
    inputs = json.loads(os.environ["GCP_FOUNDATION_INPUTS_JSON"])
    if not isinstance(inputs, dict) or any(
        (
            inputs.get("environment") != environment,
            inputs.get("project_id") != project_id,
            inputs.get("name_prefix") != f"shifter-{environment}",
            inputs.get("terraform_state_bucket_name") != f"{project_id}-terraform-state",
            inputs.get("enable_image_build_network") is not True,
        )
    ):
        raise ValueError("Foundation inputs do not match the selected tenant and image-network migration")

    region = inputs.get("region")
    if not isinstance(region, str) or not region:
        raise ValueError("Foundation region is required")
    subnet_cidr = inputs.get("image_build_subnet_cidr", "10.201.0.0/24")
    if not isinstance(subnet_cidr, str) or not subnet_cidr:
        raise ValueError("Foundation image-build subnet CIDR is invalid")
    current_ports = _verify_live_network(project_id, environment, region, subnet_cidr, os.environ.copy())

    with tempfile.TemporaryDirectory(prefix="foundation-image-network-", dir=os.environ["RUNNER_TEMP"]) as temporary:
        directory = Path(temporary)
        tfvars = directory / "foundation.auto.tfvars.json"
        tfvars.write_text(json.dumps(inputs), encoding="utf-8")
        tfvars.chmod(0o600)
        plan_file = directory / "image-network.tfplan"
        terraform = ["terraform", f"-chdir={_ROOT}"]
        process_env = os.environ.copy()
        process_env["TF_DATA_DIR"] = str(directory / "tfdata")
        _run(
            [
                *terraform,
                "init",
                "-reconfigure",
                "-input=false",
                f"-backend-config=bucket={project_id}-terraform-state",
                "-backend-config=prefix=cicd-oidc",
            ],
            env=process_env,
        )
        _run(
            [
                *terraform,
                "plan",
                "-input=false",
                "-refresh=false",
                "-lock-timeout=5m",
                f"-var-file={tfvars}",
                f"-out={plan_file}",
            ],
            env=process_env,
        )
        plan = json.loads(_run([*terraform, "show", "-json", str(plan_file)], env=process_env))
        moves, updates = validate_plan(plan)
        if updates != (0 if "2222" in current_ports else 1):
            raise ValueError("Terraform firewall plan disagrees with the live IAP rule")
        print(f"Foundation plan approved: {moves} image-network address moves, {updates} IAP port update")
        _run([*terraform, "apply", "-input=false", "-lock-timeout=5m", str(plan_file)], env=process_env)
        addresses = set(_run([*terraform, "state", "list"], env=process_env).splitlines())
        expected = {_MODULE_PREFIX + resource for resource in _RESOURCES}
        if not expected.issubset(addresses) or any(resource in addresses for resource in _RESOURCES):
            raise ValueError("Foundation state does not contain all six moved image-network resources")

    if _verify_live_network(project_id, environment, region, subnet_cidr, os.environ.copy()) != [
        "22",
        "2222",
        "5986",
    ]:
        raise ValueError("Foundation image-build IAP rule did not admit port 2222")
    print("Foundation image network reconciled; six resources retained and IAP port 2222 verified")


def main() -> int:
    try:
        reconcile()
    except (KeyError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"Foundation image-network reconciliation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
