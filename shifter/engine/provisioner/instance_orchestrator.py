"""Parallel orchestration of per-instance setup for the Shifter Engine provisioner.

Extracted from ``instance_setup.py`` (Sonar S104). Owns the partition
helpers (pod-vs-VM, DC-vs-other), the blocking DC sequence + parallel
non-DC pool, and the ``run_instance_setup`` entry point the orchestrator
container calls after Terraform completes.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from agent_assets import get_agent_presigned_url
from dc_setup import _run_dc_setup
from instance_setup import (
    _DomainJoinSpec,
    _InstanceSetupSpec,
    _run_single_instance_setup,
    _set_attacker_container_password_after_bootstrap,
)
from orchestrators.setup_orchestrator import SetupError
from polaris_bootstrap import _run_polaris_range_bootstrap

logger = logging.getLogger(__name__)


def _build_uuid_to_config(range_spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return a {instance uuid → instance config} lookup from the range spec."""
    return {
        inst.get("uuid", ""): inst for subnet in range_spec.get("subnets", []) for inst in subnet.get("instances", [])
    }


def _partition_pod_vs_vm(
    instances_output: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split scanned instances into (pod-backed, VM-backed) lists."""
    pods: list[dict[str, Any]] = []
    vms: list[dict[str, Any]] = []
    for inst in instances_output:
        if inst.get("asset_type", "vm_runtime_vm") == "scenario_pod":
            pods.append(inst)
        else:
            vms.append(inst)
    return pods, vms


def _partition_dc_vs_other(
    vm_instances: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split VM-backed instances into (DC, non-DC) lists."""
    dcs: list[dict[str, Any]] = []
    others: list[dict[str, Any]] = []
    for inst in vm_instances:
        if inst.get("role") == "dc":
            dcs.append(inst)
        else:
            others.append(inst)
    return dcs, others


def _setup_dc_instances_blocking(
    dc_instances: list[dict[str, Any]],
    uuid_to_config: dict[str, dict[str, Any]],
) -> None:
    """Run DC setup for every DC instance synchronously (domain joins depend on it)."""
    for dc_inst in dc_instances:
        inst_uuid = dc_inst.get("uuid", "")
        inst_config = uuid_to_config.get(inst_uuid, {})
        dc_config = inst_config.get("dc_config", {})
        agent_url = get_agent_presigned_url(inst_config)
        _run_dc_setup(
            instance_data=dc_inst,
            instance_id=dc_inst["instance_id"],
            dc_config=dc_config,
            agent_presigned_url=agent_url or "",
            public_key=dc_inst.get("public_key", ""),
            xdr_required=bool(inst_config.get("agent")),
        )


def _resolve_dc_ip_and_domain(
    dc_instances: list[dict[str, Any]],
    uuid_to_config: dict[str, dict[str, Any]],
    dc_ip: str | None,
    domain_name: str | None,
) -> tuple[str | None, str | None]:
    """Pick the DC IP + domain to use for downstream domain joins."""
    if not dc_instances or dc_ip:
        return dc_ip, domain_name
    first_dc = dc_instances[0]
    dc_uuid = first_dc.get("uuid", "")
    dc_config = uuid_to_config.get(dc_uuid, {}).get("dc_config", {})
    return first_dc.get("private_ip"), dc_config.get("domain_name")


def _setup_one_other_instance(
    inst: dict[str, Any],
    uuid_to_config: dict[str, dict[str, Any]],
    actual_dc_ip: str | None,
    actual_domain: str | None,
    range_id: int,
) -> tuple[str, bool, str | None]:
    """Run setup for a single non-DC VM. Returns (instance_id, success, error)."""
    inst_id = inst["instance_id"]
    inst_uuid = inst.get("uuid", "")
    inst_config = uuid_to_config.get(inst_uuid, {})
    is_polaris_vm = inst_config.get("ami_key") == "polaris-vm"
    spec = _InstanceSetupSpec(
        role=inst.get("role", "victim"),
        os_type=inst.get("os", "ubuntu"),
        public_key=inst.get("public_key", ""),
        agent_presigned_url=get_agent_presigned_url(inst_config) or "",
        xdr_required=bool(inst_config.get("agent")),
        instance_name=inst.get("hostname", "") or inst.get("name", ""),
        range_id=range_id,
        domain_join=_DomainJoinSpec(
            join_domain=inst_config.get("join_domain", False),
            dc_ip=actual_dc_ip,
            domain_name=actual_domain,
        ),
        set_local_password=not is_polaris_vm,
    )
    try:
        _run_single_instance_setup(instance_data=inst, instance_id=inst_id, spec=spec)
        # Per-scenario post-bootstrap: the polaris VM AMI is pre-baked with
        # a docker compose stack hardcoded to range 0's DC IP and the
        # bake-time kali pubkey. After LinuxBootstrapPlan finishes, rewrite
        # the compose override and force-recreate the dns + a14-kali
        # containers with this range's actual DC IP and per-instance pubkey.
        # Gate on ami_key so this only fires for polaris instances.
        if is_polaris_vm:
            _run_polaris_range_bootstrap(
                instance_id=inst_id,
                dc_ip=actual_dc_ip or "",
                public_key=inst.get("public_key", ""),
            )
            _set_attacker_container_password_after_bootstrap(
                instance_data=inst,
                instance_id=inst_id,
                container_name="a14-kali",
                ssh_user="kali",
            )
        return (inst_id, True, None)
    except Exception as e:
        # Catch-all so any single instance's failure becomes a tuple the
        # orchestrator can fail the whole range on, rather than crashing
        # the executor thread.
        return (inst_id, False, str(e))


def _setup_other_instances_parallel(
    other_instances: list[dict[str, Any]],
    uuid_to_config: dict[str, dict[str, Any]],
    actual_dc_ip: str | None,
    actual_domain: str | None,
    range_id: int,
) -> None:
    """Run setup for non-DC VMs in parallel; raise on any failure."""
    if not other_instances:
        return
    logger.info("Running setup for %d non-DC instances in parallel...", len(other_instances))
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(
                _setup_one_other_instance,
                inst,
                uuid_to_config,
                actual_dc_ip,
                actual_domain,
                range_id,
            ): inst
            for inst in other_instances
        }
        for future in as_completed(futures):
            inst_id, success, error = future.result()
            if not success:
                raise SetupError(f"Instance {inst_id} setup failed: {error}")


def run_instance_setup(
    instances_output: list[dict[str, Any]],
    range_spec: dict[str, Any],
    dc_ip: str | None = None,
    domain_name: str | None = None,
    range_id: int = 0,
) -> None:
    """Run setup for all instances after infrastructure is ready.

    Runs DC setup first (blocking), then all other instances in parallel.
    """
    uuid_to_config = _build_uuid_to_config(range_spec)
    pod_instances, vm_instances = _partition_pod_vs_vm(instances_output)
    if pod_instances:
        logger.info("Skipping VM setup for %d pod-backed scenario assets", len(pod_instances))

    dc_instances, other_instances = _partition_dc_vs_other(vm_instances)

    # DC setup MUST complete before any domain joins fire.
    _setup_dc_instances_blocking(dc_instances, uuid_to_config)

    actual_dc_ip, actual_domain = _resolve_dc_ip_and_domain(dc_instances, uuid_to_config, dc_ip, domain_name)

    _setup_other_instances_parallel(other_instances, uuid_to_config, actual_dc_ip, actual_domain, range_id)
    logger.info("All instance setup complete")
