"""Tests for RAES-native GCE range-cell provisioning orchestration (ADR-031/032).

Exercises the full apply/destroy path against a fake Compute API + injected SSH
secret ops (no real GCP): provision creates network/subnets/firewalls/addresses/
instances; the provisioner-managed SSH key is minted per instance (never a
scenario secret); reconcile skips re-insert; apply cleans up on failure; and
destroy deletes every owned resource + secret.
"""

import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import raes_gcp_apply as apply_module
from config import GCE_BOOTSTRAP_PRECONFIGURED_MACHINE_HOST, GCERangeCellConfig, GCERangeImageProfile
from executors.base import CommandResult
from executors.factory import GuestExecutionContext
from raes_account_credentials import RaesAccountCredentialOps, install_instance_account_credentials
from raes_active_directory import RaesDirectorySecretOps
from raes_gcp_apply import (
    RaesGceApplyOptions,
    RaesGceDestroyOptions,
    RaesGceSecretOps,
    apply_raes_range_cell,
    destroy_raes_range_cell,
)
from raes_gcp_composition import RaesGceCompositionError
from raes_gcp_firewall import node_tag
from raes_gcp_plan import RaesGcePlanError, build_raes_range_cell_plan
from raes_gcp_vpn_plan import RaesGceVpnAccess, vpn_pool_firewall_name
from raes_plan import (
    RaesPlan,
    RaesPlanAccount,
    RaesPlanContent,
    RaesPlanDomain,
    RaesPlanFeature,
    RaesPlanImage,
    RaesPlanNetwork,
    RaesPlanNode,
    RaesPlanServicePort,
)


class _NotFound(Exception):
    """Fake Google NotFound exception."""


@pytest.fixture(autouse=True)
def _fake_advisory_lock_database(monkeypatch):
    monkeypatch.setenv("DB_HOST", "localhost")
    monkeypatch.setenv("DB_USER", "test")
    monkeypatch.setenv("DB_NAME", "test")
    monkeypatch.setenv("DB_PASSWORD", "test-only")
    monkeypatch.setattr("provisioner_db.psycopg.connect", lambda **_kwargs: MagicMock())


def _config(network_mode: str = "vpc-per-range") -> GCERangeCellConfig:
    return GCERangeCellConfig(
        project_id="proj-1",
        region="us-east1",
        zone="us-east1-b",
        network_mode=network_mode,
        network_id="projects/proj-1/global/networks/shared" if network_mode == "shared-vpc" else "",
        service_account_email="host@proj-1.iam.gserviceaccount.com",
        portal_network_cidrs=("203.0.113.0/24",),
    )


def _plan() -> RaesPlan:
    node = RaesPlanNode(
        address="node.web",
        name="web",
        os_family="linux",
        count=2,
        network_addresses=("net.lan",),
        image=RaesPlanImage(name="ubuntu"),
    )
    network = RaesPlanNetwork(address="net.lan", name="lan", cidr="10.9.0.0/24")
    return RaesPlan(raes_version="3.5.0", nodes=(node,), networks=(network,))


def _resolver(node):
    return GCERangeImageProfile(source_image="projects/x/global/images/ubuntu-1")


@pytest.mark.parametrize("phase", ["runtime_plugin", "model_enrollment"])
def test_plugin_failure_enters_resource_and_secret_cleanup_before_readiness(phase):
    from runtime_plugin_execution import RuntimePluginExecutionError

    clients = _clients(exists=True)
    secrets, secret_calls = _secret_ops()
    plugin = MagicMock(side_effect=RuntimePluginExecutionError("Runtime plugin guest execution failed"))
    composition = MagicMock()
    options = _apply_options(_config(), clients, secrets, **{phase: plugin}, composition_verifier=composition)
    with pytest.raises(RuntimePluginExecutionError):
        apply_raes_range_cell("req-plugin", 7, _plan(), _resolver, options)
    assert clients.instances.delete.call_count == 2
    assert secret_calls.delete_ssh.call_count == 2
    composition.assert_not_called()


def _clients(*, exists: bool = False, instance_insert_error: Exception | None = None) -> SimpleNamespace:
    def get_side_effect(**_kwargs):
        if exists:
            return SimpleNamespace(metadata=SimpleNamespace(items=[]))
        raise _NotFound()

    def service(insert_error: Exception | None = None):
        svc = MagicMock()
        svc.get.side_effect = get_side_effect
        if insert_error is not None:
            svc.insert.side_effect = insert_error
        else:
            svc.insert.return_value = SimpleNamespace(name="op")
        svc.delete.return_value = SimpleNamespace(name="op")
        svc.patch.return_value = SimpleNamespace(name="op")
        return svc

    op_service = MagicMock()
    op_service.wait.return_value = SimpleNamespace(status="DONE")
    routers = service()
    router_state = {}

    def router_get(**kwargs):
        name = kwargs["router"]
        if name in router_state:
            return router_state[name]
        if exists:
            return {"name": name, "network": "projects/proj-1/global/networks/shared", "nats": []}
        raise _NotFound()

    def router_insert(**kwargs):
        body = kwargs["router_resource"]
        router_state[body["name"]] = body
        return SimpleNamespace(name="op")

    def router_patch(**kwargs):
        name = kwargs["router"]
        router_state[name] = {**router_state.get(name, {"name": name}), **kwargs["router_resource"]}
        return SimpleNamespace(name="op")

    def router_delete(**kwargs):
        router_state.pop(kwargs["router"], None)
        return SimpleNamespace(name="op")

    routers.get.side_effect = router_get
    routers.list.side_effect = lambda **_kwargs: list(router_state.values())
    routers.insert.side_effect = router_insert
    routers.patch.side_effect = router_patch
    routers.delete.side_effect = router_delete
    return SimpleNamespace(
        networks=service(),
        subnetworks=service(),
        firewalls=service(),
        addresses=service(),
        routers=routers,
        instances=service(instance_insert_error),
        global_operations=op_service,
        region_operations=op_service,
        zone_operations=op_service,
        google_exceptions=SimpleNamespace(NotFound=_NotFound),
    )


def _secret_ops() -> tuple[RaesGceSecretOps, SimpleNamespace]:
    mocks = SimpleNamespace(
        ensure_ssh=MagicMock(return_value=("projects/proj-1/secrets/ssh", "ssh-ed25519 AAAAKEY")),
        delete_ssh=MagicMock(),
    )
    return RaesGceSecretOps(ensure_ssh=mocks.ensure_ssh, delete_ssh=mocks.delete_ssh), mocks


def _apply_options(
    config: GCERangeCellConfig,
    clients: SimpleNamespace,
    secret_ops: RaesGceSecretOps,
    **overrides,
) -> RaesGceApplyOptions:
    """Build injectable RAES apply options for fake-GCP tests."""
    overrides.setdefault(
        "composition_verifier",
        lambda plan, _outputs: frozenset(
            [item.address for item in plan.content]
            + [account.address for account in plan.accounts]
            + [feature.address for feature in plan.features]
        ),
    )
    overrides.setdefault(
        "substrate_observer",
        lambda plan, _clients: [
            {"instance_key": instance["uuid"], "value": "virtual-machine"} for instance in plan["instances"]
        ],
    )
    overrides.setdefault("host_readiness_verifier", MagicMock())
    overrides.setdefault(
        "operating_system_observer",
        lambda _plan, outputs: [
            {
                "instance_key": output["uuid"],
                "family": output["os"],
                "distribution": "windows-server" if output["os"] == "windows" else "ubuntu",
                "version": "10.0.20348" if output["os"] == "windows" else "22.04",
            }
            for output in outputs
        ],
    )
    return RaesGceApplyOptions(
        config=config,
        clients=clients,
        secret_ops=secret_ops,
        **overrides,
    )


def test_missing_guest_os_evidence_fails_apply_and_cleans_up():
    clients = _clients()
    secrets, _ = _secret_ops()
    options = _apply_options(_config(), clients, secrets, operating_system_observer=lambda _plan, _outputs: [])
    with pytest.raises(ValueError, match="operating-system"):
        apply_raes_range_cell("req-1", 7, _plan(), _resolver, options)
    # This fake reports every resource absent on readback. Cleanup revisits
    # both guests for disk convergence and deletion; absent resources need no delete call.
    assert clients.instances.get.call_count == 6


def test_enrolled_guest_gets_exact_broker_firewall_before_enrollment():
    clients = _clients()
    secrets, _ = _secret_ops()
    cfg = replace(_config(), model_broker_vip="10.20.0.9")

    def enroll(_plan, _outputs):
        rules = [call.kwargs["firewall_resource"] for call in clients.firewalls.insert.call_args_list]
        broker = [rule for rule in rules if rule.get("destination_ranges") == ["10.20.0.9/32"]]
        assert len(broker) == 1
        assert broker[0]["allowed"] == [{"I_p_protocol": "tcp", "ports": ["443"]}]

    options = _apply_options(
        cfg,
        clients,
        secrets,
        model_enrollment=enroll,
        model_broker={"contract_version": "model-broker-egress/v1", "vip": "10.20.0.9", "port": 443},
    )
    apply_raes_range_cell("req-broker", 7, _plan(), _resolver, options)


def _account_secret_ops() -> tuple[RaesAccountCredentialOps, SimpleNamespace]:
    mocks = SimpleNamespace(
        ensure_password=MagicMock(return_value=("projects/proj-1/secrets/password", "PASSWORD")),
        ensure_public_key=MagicMock(return_value=("projects/proj-1/secrets/key", "ssh-rsa PUBLIC")),
        delete=MagicMock(),
    )
    return (
        RaesAccountCredentialOps(
            ensure_password=mocks.ensure_password,
            ensure_public_key=mocks.ensure_public_key,
            delete=mocks.delete,
        ),
        mocks,
    )


def _directory_secret_ops() -> tuple[RaesDirectorySecretOps, SimpleNamespace]:
    mocks = SimpleNamespace(
        ensure_dsrm=MagicMock(return_value=("secret/dsrm", "DSRM")),
        ensure_authority=MagicMock(return_value=("secret/authority", "AUTHORITY")),
        ensure_account=MagicMock(return_value=("secret/account", "ACCOUNT")),
        delete_dsrm=MagicMock(),
        delete_authority=MagicMock(),
        delete_account=MagicMock(),
    )
    return (
        RaesDirectorySecretOps(
            ensure_dsrm=mocks.ensure_dsrm,
            ensure_authority=mocks.ensure_authority,
            ensure_account=mocks.ensure_account,
            delete_dsrm=mocks.delete_dsrm,
            delete_authority=mocks.delete_authority,
            delete_account=mocks.delete_account,
        ),
        mocks,
    )


def _plan_with_domain(*, include_local: bool = False) -> RaesPlan:
    controller = RaesPlanNode(
        address="node.dc",
        name="dc",
        os_family="windows",
        count=1,
        network_addresses=("net.lan",),
        domain_id="corp",
        domain_role="controller",
        controller_addresses=("node.dc",),
    )
    member = RaesPlanNode(
        address="node.member",
        name="member",
        os_family="windows",
        count=1,
        network_addresses=("net.lan",),
        ordering_dependencies=("node.dc",),
        domain_id="corp",
        domain_role="member",
        controller_addresses=("node.dc",),
    )
    authority = RaesPlanAccount(
        address="account.admin",
        username="Administrator",
        target_address="node.dc",
        password_strength="strong",
        domain_id="corp",
    )
    service = RaesPlanAccount(
        address="account.service",
        username="svc-web",
        target_address="node.member",
        password_strength="strong",
        spn="HTTP/member.corp.example",
        domain_ref="corp",
        domain_id="corp",
    )
    local_operator = RaesPlanAccount(
        address="account.local-operator",
        username="local-operator",
        target_address="node.member",
        password_strength="strong",
    )
    domain = RaesPlanDomain(
        domain_id="corp",
        profile="active_directory",
        dns_name="corp.example",
        netbios_name="CORP",
        authority_account_address=authority.address,
        controller_addresses=(controller.address,),
        member_addresses=(member.address,),
    )
    return RaesPlan(
        raes_version="3.5.0",
        nodes=(controller, member),
        networks=(RaesPlanNetwork(address="net.lan", name="lan", cidr="10.9.0.0/24"),),
        accounts=(authority, service, *((local_operator,) if include_local else ())),
        domains=(domain,),
    )


class TestApply:
    def test_provisions_network_subnet_firewall_and_instances(self):
        clients = _clients()
        secret_ops, secret_mocks = _secret_ops()
        output = apply_raes_range_cell("req-1", 7, _plan(), _resolver, _apply_options(_config(), clients, secret_ops))

        assert clients.networks.insert.called  # vpc-per-range manages its own VPC
        assert clients.subnetworks.insert.call_count == 1
        assert clients.firewalls.insert.called
        # count=2 -> two instances, two reserved addresses, two SSH secrets.
        assert clients.addresses.insert.call_count == 2
        assert clients.instances.insert.call_count == 2
        assert secret_mocks.ensure_ssh.call_count == 2
        assert len(output["instances"]) == 2
        assert set(output["subnets"]) == {"lan"}
        # A status-quo range owns a Cloud Router+NAT for its egress (PLAT-238).
        assert clients.routers.insert.called

    def test_zero_egress_range_provisions_no_router_nat(self):
        clients = _clients()
        secret_ops, _ = _secret_ops()
        apply_raes_range_cell(
            "req-1", 7, _plan(), _resolver, _apply_options(_config(), clients, secret_ops, egress_mode="none")
        )
        # A none range carries no NAT path at all: no range-owned router is created.
        assert not clients.routers.insert.called

    def test_shared_vpc_reconciles_nat_during_apply(self, monkeypatch):
        ensure_nat = MagicMock()
        monkeypatch.setattr(apply_module, "_ensure_router_nat", ensure_nat)
        monkeypatch.setattr(apply_module, "assert_shared_nat_capacity", MagicMock(), raising=False)
        plan = {
            "manage_network": False,
            "subnets": [],
            "shared_nat": {"router_name": "shared-nat-router"},
            "firewalls": [],
            "instances": [],
        }
        runtime = SimpleNamespace(clients=object())

        assert apply_module._provision_raes_resources(plan, runtime, {}, {}, {}) == []
        ensure_nat.assert_called_once_with(plan, runtime.clients)

    def test_ssh_secret_keyed_on_raes_instance_not_scenario(self):
        clients = _clients()
        secret_ops, secret_mocks = _secret_ops()
        apply_raes_range_cell("req-1", 7, _plan(), _resolver, _apply_options(_config(), clients, secret_ops))
        keys = sorted(call.args[1] for call in secret_mocks.ensure_ssh.call_args_list)
        assert keys == ["node.web#0", "node.web#1"]

    def test_shared_vpc_does_not_create_network(self):
        clients = _clients()
        secret_ops, _ = _secret_ops()
        apply_raes_range_cell(
            "req-1",
            7,
            _plan(),
            _resolver,
            _apply_options(
                _config("shared-vpc"),
                clients,
                secret_ops,
                allocated_network_cidrs=(("net.lan", "10.90.1.0/24"),),
            ),
        )
        assert not clients.networks.insert.called

    def test_pre_mutation_plan_failure_invokes_reservation_cleanup_only(self):
        clients = _clients()
        secret_ops, secret_mocks = _secret_ops()
        release = MagicMock()

        with pytest.raises(RaesGcePlanError, match="does not match"):
            apply_raes_range_cell(
                "req-1",
                7,
                _plan(),
                _resolver,
                _apply_options(
                    _config("shared-vpc"),
                    clients,
                    secret_ops,
                    allocated_network_cidrs=(("net.wrong", "10.90.1.0/24"),),
                    on_pre_mutation_failure=release,
                ),
            )

        release.assert_called_once_with()
        clients.networks.insert.assert_not_called()
        clients.subnetworks.insert.assert_not_called()
        secret_mocks.ensure_ssh.assert_not_called()
        secret_mocks.delete_ssh.assert_not_called()

    def test_reconcile_existing_instance_skips_insert(self):
        clients = _clients(exists=True)
        secret_ops, _ = _secret_ops()
        apply_raes_range_cell("req-1", 7, _plan(), _resolver, _apply_options(_config(), clients, secret_ops))
        assert not clients.instances.insert.called

    def test_machine_image_clone_uses_source_and_owns_every_attached_disk(self):
        profile = GCERangeImageProfile(
            source_machine_image="projects/proj-1/global/machineImages/nested-host-v1",
            machine_type="n2-standard-8",
            bootstrap_capability=GCE_BOOTSTRAP_PRECONFIGURED_MACHINE_HOST,
            participant_container_name="participant-desktop",
            participant_username="operator",
            host_ssh_username="hostadmin",
            host_ssh_port=2222,
        )
        clients = _clients()
        created = SimpleNamespace(
            disks=[
                SimpleNamespace(device_name="boot", auto_delete=True),
                SimpleNamespace(device_name="nested-data", auto_delete=False),
            ]
        )
        clients.instances.get.side_effect = [_NotFound(), _NotFound(), created]
        clients.instances.set_disk_auto_delete.return_value = SimpleNamespace(name="op")
        secret_ops, _ = _secret_ops()
        plan = _plan()
        plan = replace(plan, nodes=(replace(plan.nodes[0], count=1),))

        apply_raes_range_cell(
            "req-1",
            7,
            plan,
            lambda _node: profile,
            _apply_options(_config(), clients, secret_ops),
        )

        request = clients.instances.insert.call_args.kwargs["request"]
        assert request["source_machine_image"] == profile.source_machine_image
        assert "disks" not in request["instance_resource"]
        clients.instances.set_disk_auto_delete.assert_called_once_with(
            project="proj-1",
            zone="us-east1-b",
            instance=request["instance_resource"]["name"],
            device_name="nested-data",
            auto_delete=True,
        )

    def test_preconfigured_custom_image_uses_owned_boot_disk(self):
        profile = GCERangeImageProfile(
            source_image="projects/proj-1/global/images/nested-host-v1",
            machine_type="n2-standard-8",
            disk_size_gb=220,
            bootstrap_capability=GCE_BOOTSTRAP_PRECONFIGURED_MACHINE_HOST,
            participant_container_name="participant-desktop",
            participant_username="operator",
            host_ssh_username="hostadmin",
            participant_readiness_contract="participant-readiness/v1",
            participant_readiness_manifest_sha256="a" * 64,
        )
        clients = _clients()
        secret_ops, _ = _secret_ops()
        plan = replace(_plan(), nodes=(replace(_plan().nodes[0], count=1),))
        readiness = MagicMock()

        output = apply_raes_range_cell(
            "req-1",
            7,
            plan,
            lambda _node: profile,
            _apply_options(_config(), clients, secret_ops, host_readiness_verifier=readiness),
        )

        body = clients.instances.insert.call_args.kwargs["instance_resource"]
        assert body["disks"][0]["auto_delete"] is True
        assert body["disks"][0]["initialize_params"]["source_image"] == profile.source_image
        assert body["advanced_machine_features"] == {"enable_nested_virtualization": True}
        assert output["instances"][0]["gcp_participant_container_name"] == "participant-desktop"
        assert output["instances"][0]["participant_sftp_enabled"] is False
        readiness.assert_called_once()
        assert readiness.call_args.args[0][0]["gcp_bootstrap_capability"] == GCE_BOOTSTRAP_PRECONFIGURED_MACHINE_HOST

    def test_conflicting_preconfigured_host_is_rejected_before_mutation(self):
        profile = GCERangeImageProfile(
            source_image="projects/proj-1/global/images/nested-host-v1",
            machine_type="n2-standard-8",
            disk_size_gb=220,
            bootstrap_capability=GCE_BOOTSTRAP_PRECONFIGURED_MACHINE_HOST,
            participant_container_name="participant-desktop",
            participant_username="operator",
            host_ssh_username="hostadmin",
            participant_readiness_contract="participant-readiness/v1",
            participant_readiness_manifest_sha256="a" * 64,
        )
        clients = _clients(exists=True)
        clients.instances.get.side_effect = None
        clients.instances.get.return_value = SimpleNamespace(
            labels={"managed-by": "unrelated", "range-id": "other", "image-profile": "wrong"}
        )
        secret_ops, secret_calls = _secret_ops()
        with pytest.raises(RuntimeError, match="conflicting range or image-profile"):
            apply_raes_range_cell(
                "req-1",
                7,
                _plan(),
                lambda _node: profile,
                _apply_options(_config(), clients, secret_ops),
            )
        clients.instances.insert.assert_not_called()
        clients.instances.delete.assert_not_called()
        secret_calls.ensure_ssh.assert_not_called()

    def test_late_conflicting_host_is_never_deleted(self):
        profile = GCERangeImageProfile(
            source_image="projects/proj-1/global/images/nested-host-v1",
            machine_type="n2-standard-8",
            disk_size_gb=220,
            bootstrap_capability=GCE_BOOTSTRAP_PRECONFIGURED_MACHINE_HOST,
            participant_container_name="participant-desktop",
            participant_username="operator",
            host_ssh_username="hostadmin",
            participant_readiness_contract="participant-readiness/v1",
            participant_readiness_manifest_sha256="a" * 64,
        )
        clients = _clients()
        clients.instances.get.side_effect = [_NotFound(), SimpleNamespace(labels={"managed-by": "unrelated"})]
        secret_ops, secret_calls = _secret_ops()
        plan = replace(_plan(), nodes=(replace(_plan().nodes[0], count=1),))
        with pytest.raises(RuntimeError, match="conflicting range or image-profile"):
            apply_raes_range_cell(
                "req-1",
                7,
                plan,
                lambda _node: profile,
                _apply_options(_config(), clients, secret_ops),
            )
        clients.instances.delete.assert_not_called()
        secret_calls.ensure_ssh.assert_not_called()

    def test_late_conflict_cleans_prior_created_instance_only(self):
        profile = GCERangeImageProfile(
            source_image="projects/proj-1/global/images/nested-host-v1",
            machine_type="n2-standard-8",
            disk_size_gb=220,
            bootstrap_capability=GCE_BOOTSTRAP_PRECONFIGURED_MACHINE_HOST,
            participant_container_name="participant-desktop",
            participant_username="operator",
            host_ssh_username="hostadmin",
            participant_readiness_contract="participant-readiness/v1",
            participant_readiness_manifest_sha256="a" * 64,
        )
        raes_plan = _plan()
        rendered = build_raes_range_cell_plan("req-1", 7, raes_plan, lambda _node: profile, _config())
        names = [instance["resource_name"] for instance in rendered["instances"]]
        seen: dict[str, int] = {}

        def get_instance(*, instance, **_kwargs):
            count = seen.get(instance, 0)
            seen[instance] = count + 1
            if count == 0 or (instance == names[0] and count == 1):
                raise _NotFound()
            if instance == names[1]:
                return SimpleNamespace(labels={"managed-by": "unrelated"})
            return SimpleNamespace(labels={}, disks=[], metadata=SimpleNamespace(items=[]))

        clients = _clients()
        clients.instances.get.side_effect = get_instance
        clients.networks.get.side_effect = [_NotFound(), SimpleNamespace()]
        secret_ops, secret_calls = _secret_ops()
        with pytest.raises(RuntimeError, match="conflicting range or image-profile"):
            apply_raes_range_cell(
                "req-1",
                7,
                raes_plan,
                lambda _node: profile,
                _apply_options(_config(), clients, secret_ops),
            )
        deleted = [call.kwargs["instance"] for call in clients.instances.delete.call_args_list]
        assert deleted == [names[0]]
        clients.networks.delete.assert_called_once()
        secret_calls.delete_ssh.assert_called_once_with(7, rendered["instances"][0]["uuid"])

    def test_custom_image_host_reconcile_restores_boot_disk_auto_delete(self):
        profile = GCERangeImageProfile(
            source_image="projects/proj-1/global/images/nested-host-v1",
            machine_type="n2-standard-8",
            disk_size_gb=220,
            bootstrap_capability=GCE_BOOTSTRAP_PRECONFIGURED_MACHINE_HOST,
            participant_container_name="participant-desktop",
            participant_username="operator",
            host_ssh_username="hostadmin",
            participant_readiness_contract="participant-readiness/v1",
            participant_readiness_manifest_sha256="a" * 64,
        )
        raes_plan = replace(_plan(), nodes=(replace(_plan().nodes[0], count=1),))
        rendered = build_raes_range_cell_plan("req-1", 7, raes_plan, lambda _node: profile, _config())
        instance = rendered["instances"][0]
        existing = SimpleNamespace(
            labels={
                **rendered["labels"],
                "image-key": "default",
                "image-profile": instance["image_profile_fingerprint"],
            },
            disks=[SimpleNamespace(device_name="boot", auto_delete=False)],
            metadata=SimpleNamespace(items=[]),
        )
        clients = _clients()
        clients.instances.get.side_effect = None
        clients.instances.get.return_value = existing
        clients.instances.set_disk_auto_delete.return_value = SimpleNamespace(name="op")
        secret_ops, _ = _secret_ops()

        apply_raes_range_cell(
            "req-1",
            7,
            raes_plan,
            lambda _node: profile,
            _apply_options(_config(), clients, secret_ops),
        )

        clients.instances.insert.assert_not_called()
        clients.instances.set_disk_auto_delete.assert_called_once_with(
            project="proj-1",
            zone="us-east1-b",
            instance=instance["resource_name"],
            device_name="boot",
            auto_delete=True,
        )

    def test_destroy_converges_retained_custom_host_boot_disk(self):
        clients = _clients(exists=True)
        clients.instances.get.side_effect = None
        clients.instances.get.return_value = SimpleNamespace(
            disks=[SimpleNamespace(device_name="boot", auto_delete=False)]
        )
        clients.instances.set_disk_auto_delete.return_value = SimpleNamespace(name="op")
        secret_ops, _ = _secret_ops()
        raes_plan = replace(_plan(), nodes=(replace(_plan().nodes[0], count=1),))

        destroy_raes_range_cell(
            "req-1",
            7,
            raes_plan,
            RaesGceDestroyOptions(config=_config(), clients=clients, secret_ops=secret_ops),
        )

        clients.instances.set_disk_auto_delete.assert_called_once()
        assert clients.instances.set_disk_auto_delete.call_args.kwargs["auto_delete"] is True

    def test_apply_failure_triggers_cleanup_and_reraises(self):
        clients = _clients(instance_insert_error=RuntimeError("boom"))
        secret_ops, secret_mocks = _secret_ops()
        plan_2 = _plan()
        release = MagicMock()
        apply_options = _apply_options(_config(), clients, secret_ops, on_pre_mutation_failure=release)
        with pytest.raises(RuntimeError, match="boom"):
            apply_raes_range_cell("req-1", 7, plan_2, _resolver, apply_options)
        release.assert_not_called()
        # Cleanup ran: the reconstructive destroy sweeps EVERY instance's SSH secret
        # unconditionally. The plan has count=2, so a regression that swept only one
        # instance (early return/break, swallowed exception, off-by-one) would leave
        # orphaned credential residue -- assert the exact count, not just `.called`.
        # instances.delete is legitimately not reached (the first insert failed, so
        # nothing exists yet to GCE-delete).
        assert secret_mocks.delete_ssh.call_count == 2
        assert clients.instances.get.called

    def test_domain_realization_gates_success_and_domain_accounts_bypass_local_credentials(self):
        clients = _clients()
        secret_ops, _ = _secret_ops()
        account_secret_ops, _ = _account_secret_ops()
        directory_secret_ops, _ = _directory_secret_ops()
        credential_installer = MagicMock()
        directory_realizer = MagicMock()

        output = apply_raes_range_cell(
            "req-1",
            7,
            _plan_with_domain(include_local=True),
            _resolver,
            _apply_options(
                _config(),
                clients,
                secret_ops,
                account_secret_ops=account_secret_ops,
                credential_installer=credential_installer,
                directory_secret_ops=directory_secret_ops,
                directory_realizer=directory_realizer,
            ),
        )

        credential_installer.assert_called_once()
        assert tuple(account.username for account in credential_installer.call_args.kwargs["accounts"]) == (
            "local-operator",
        )
        directory_realizer.assert_called_once()
        assert len(directory_realizer.call_args.kwargs["instance_outputs"]) == 2
        assert len(output["instances"]) == 2
        startup_scripts = [
            next(
                item["value"]
                for item in call.kwargs["instance_resource"]["metadata"]["items"]
                if item["key"] == "windows-startup-script-ps1"
            )
            for call in clients.instances.insert.call_args_list
        ]
        assert sum("New-LocalUser" in script for script in startup_scripts) == 1
        assert any("local-operator" in script for script in startup_scripts)
        assert all("New-LocalUser -Name 'Administrator'" not in script for script in startup_scripts)
        assert all("svc-web" not in script for script in startup_scripts)

    def test_directory_failure_runs_reconstructive_secret_cleanup_and_never_returns_success(self):
        clients = _clients()
        secret_ops, _ = _secret_ops()
        directory_secret_ops, directory_mocks = _directory_secret_ops()
        directory_realizer = MagicMock(side_effect=RuntimeError("directory failed"))
        plan = _plan_with_domain()
        options = _apply_options(
            _config(),
            clients,
            secret_ops,
            directory_secret_ops=directory_secret_ops,
            directory_realizer=directory_realizer,
        )

        with pytest.raises(RuntimeError, match="directory failed"):
            apply_raes_range_cell("req-1", 7, plan, _resolver, options)

        directory_mocks.delete_account.assert_called_once_with(7, "corp", "account.service")
        directory_mocks.delete_authority.assert_called_once_with(7, "corp")
        directory_mocks.delete_dsrm.assert_called_once_with(7, "corp")


def _plan_with_content(*content: RaesPlanContent) -> RaesPlan:
    node = RaesPlanNode(
        address="node.web",
        name="web",
        os_family="linux",
        count=1,
        network_addresses=("net.lan",),
        image=RaesPlanImage(name="ubuntu"),
    )
    network = RaesPlanNetwork(address="net.lan", name="lan", cidr="10.9.0.0/24")
    return RaesPlan(raes_version="3.5.0", nodes=(node,), networks=(network,), content=content)


class TestCompositionIntegration:
    def _startup_script(self, clients) -> str:
        body = clients.instances.insert.call_args.kwargs["instance_resource"]
        items = body["metadata"]["items"]
        return next(item["value"] for item in items if item["key"] == "startup-script")

    def test_composition_reaches_instance_startup_script(self):
        content = RaesPlanContent(
            name="doc", content_type="file", target_address="node.web", path="/srv/x.txt", text="hello"
        )
        clients = _clients()
        secret_ops, _ = _secret_ops()
        apply_raes_range_cell(
            "req-1",
            7,
            _plan_with_content(content),
            _resolver,
            _apply_options(_config(), clients, secret_ops),
        )
        startup = self._startup_script(clients)
        import base64

        assert base64.b64encode(b"hello").decode() in startup
        assert "chmod 644 /srv/x.txt" in startup

    def test_verified_composition_addresses_are_returned_only_after_probe(self):
        content = RaesPlanContent(
            address="content.doc",
            name="doc",
            content_type="file",
            target_address="node.web",
            path="/srv/x.txt",
            text="hello",
        )
        clients = _clients()
        secret_ops, _ = _secret_ops()
        verifier = MagicMock(return_value=frozenset({"content.doc"}))

        output = apply_raes_range_cell(
            "req-1",
            7,
            _plan_with_content(content),
            _resolver,
            _apply_options(_config(), clients, secret_ops, composition_verifier=verifier),
        )

        verifier.assert_called_once()
        assert output["composition_verified_addresses"] == ["content.doc"]

    def test_probe_failure_triggers_cleanup_and_returns_no_proof(self):
        content = RaesPlanContent(
            address="content.doc",
            name="doc",
            content_type="directory",
            target_address="node.web",
            destination="/srv/data",
        )
        clients = _clients()
        secret_ops, secret_mocks = _secret_ops()
        verifier = MagicMock(side_effect=RaesGceCompositionError("in-guest verification failed"))
        plan = _plan_with_content(content)
        options = _apply_options(_config(), clients, secret_ops, composition_verifier=verifier)

        with pytest.raises(RaesGceCompositionError, match="in-guest verification failed"):
            apply_raes_range_cell("req-1", 7, plan, _resolver, options)

        assert secret_mocks.delete_ssh.call_count == 1

    def test_orphan_composition_target_fails_closed(self):
        content = RaesPlanContent(name="doc", content_type="file", target_address="node.ghost", path="/srv/x", text="h")
        clients = _clients()
        secret_ops, _ = _secret_ops()
        plan_with_content = _plan_with_content(content)
        apply_options = _apply_options(_config(), clients, secret_ops)
        with pytest.raises(RaesGcePlanError, match="not present in this plan"):
            apply_raes_range_cell(
                "req-1",
                7,
                plan_with_content,
                _resolver,
                apply_options,
            )


def _binding(**kw) -> dict:
    base = {
        "content_address": "content.c",
        "sha256": "a" * 64,
        "storage_key": "raes/content-delivery/aa/" + "a" * 64,
        "byte_count": 5,
        "binding_version": 1,
    }
    base.update(kw)
    return base


def _source_backed_content(**kw) -> RaesPlanContent:
    base = {
        "name": "c",
        "content_type": "file",
        "target_address": "node.web",
        "path": "/opt/x.bin",
        "source_name": "pkg",
        "address": "content.c",
    }
    base.update(kw)
    return RaesPlanContent(**base)


class TestContentDeliveryIntegration:
    """Wiring tests for #1564: the gate and realizer are reached from apply_raes_range_cell."""

    def test_missing_binding_fails_closed_before_any_cloud_resource_is_created(self):
        content = _source_backed_content()
        clients = _clients()
        secret_ops, _ = _secret_ops()
        plan = _plan_with_content(content)
        options = _apply_options(_config(), clients, secret_ops)
        with pytest.raises(RaesGceCompositionError, match="missing its delivery binding"):
            apply_raes_range_cell(
                "req-1",
                7,
                plan,
                _resolver,
                options,
                delivery_bindings=[],
            )
        assert not clients.instances.insert.called
        assert not clients.networks.insert.called

    def test_extra_binding_with_no_source_backed_content_fails_closed(self):
        clients = _clients()
        secret_ops, _ = _secret_ops()
        plan = _plan()
        options = _apply_options(_config(), clients, secret_ops)
        binding = _binding()
        with pytest.raises(RaesGceCompositionError, match="does not match any deliverable resource"):
            apply_raes_range_cell(
                "req-1",
                7,
                plan,
                _resolver,
                options,
                delivery_bindings=[binding],
            )
        assert not clients.instances.insert.called

    def test_unsupported_source_backed_content_type_fails_closed(self):
        content = RaesPlanContent(
            name="c",
            content_type="dataset",
            target_address="node.web",
            source_name="pkg",
            items=("a",),
            address="content.c",
        )
        clients = _clients()
        secret_ops, _ = _secret_ops()
        plan = _plan_with_content(content)
        options = _apply_options(_config(), clients, secret_ops)
        with pytest.raises(RaesGceCompositionError, match="no delivery materializer"):
            apply_raes_range_cell(
                "req-1",
                7,
                plan,
                _resolver,
                options,
                delivery_bindings=[],
            )
        assert not clients.instances.insert.called

    def test_realizer_is_invoked_with_plan_outputs_and_bindings_when_content_is_source_backed(self):
        content = _source_backed_content()
        clients = _clients()
        secret_ops, _ = _secret_ops()
        realizer = MagicMock()
        binding = _binding()

        apply_raes_range_cell(
            "req-1",
            7,
            _plan_with_content(content),
            _resolver,
            _apply_options(_config(), clients, secret_ops, content_delivery_realizer=realizer),
            delivery_bindings=[binding],
        )

        realizer.assert_called_once()
        assert realizer.call_args.kwargs["delivery_bindings"] == [binding]
        assert len(realizer.call_args.kwargs["instance_outputs"]) == 1
        assert realizer.call_args.kwargs["raes_plan"].content[0].source_name == "pkg"

    def test_realizer_is_not_invoked_when_no_content_is_source_backed(self):
        content = RaesPlanContent(
            name="c", content_type="file", target_address="node.web", path="/srv/x.txt", text="hi"
        )
        clients = _clients()
        secret_ops, _ = _secret_ops()
        realizer = MagicMock()

        apply_raes_range_cell(
            "req-1",
            7,
            _plan_with_content(content),
            _resolver,
            _apply_options(_config(), clients, secret_ops, content_delivery_realizer=realizer),
        )

        realizer.assert_not_called()

    def test_realizer_is_invoked_for_service_feature_before_ready(self):
        clients = _clients()
        secret_ops, _ = _secret_ops()
        realizer = MagicMock()
        base = _plan()
        feature = RaesPlanFeature(
            name="nginx",
            feature_type="service",
            target_address="node.web",
            address="feature.nginx",
            source_name="nginx",
        )
        plan = RaesPlan(
            raes_version=base.raes_version,
            nodes=base.nodes,
            networks=base.networks,
            features=(feature,),
        )
        result = apply_raes_range_cell(
            "req-1",
            7,
            plan,
            _resolver,
            _apply_options(_config(), clients, secret_ops, content_delivery_realizer=realizer),
        )
        realizer.assert_called_once()
        assert realizer.call_args.kwargs["raes_plan"] is plan
        assert realizer.call_args.kwargs["instance_outputs"] == result["instances"]
        assert {item["uuid"] for item in result["instances"]} == {"node.web#0", "node.web#1"}
        assert realizer.call_args.kwargs["delivery_bindings"] is None
        assert result["composition_verified_addresses"] == ["feature.nginx"]

    def test_realizer_failure_triggers_cleanup_and_reraises(self):
        content = _source_backed_content()
        clients = _clients()
        secret_ops, secret_mocks = _secret_ops()
        realizer = MagicMock(side_effect=RuntimeError("delivery failed"))
        plan = _plan_with_content(content)
        options = _apply_options(_config(), clients, secret_ops, content_delivery_realizer=realizer)
        binding = _binding()

        with pytest.raises(RuntimeError, match="delivery failed"):
            apply_raes_range_cell(
                "req-1",
                7,
                plan,
                _resolver,
                options,
                delivery_bindings=[binding],
            )

        # Reconstructive cleanup ran (same as a directory-realization failure).
        assert secret_mocks.delete_ssh.call_count == 1
        assert clients.instances.get.called


def _plan_with_accounts(*accounts: RaesPlanAccount, os_family: str = "linux", count: int = 2) -> RaesPlan:
    plan = _plan()
    return RaesPlan(
        raes_version=plan.raes_version,
        nodes=(replace(plan.nodes[0], os_family=os_family, count=count),),
        networks=plan.networks,
        accounts=accounts,
    )


class _RecordingCredentialExecutor:
    def __init__(self):
        self.scripts: list[str] = []
        self.stdin_inputs: list[str | None] = []
        self.closed = False

    def wait_for_ready(self, target, timeout_seconds, document_name):
        return True

    def run_command(self, instance_id, script, timeout_seconds, document_name, stdin_input=None):
        self.scripts.append(script)
        self.stdin_inputs.append(stdin_input)
        return CommandResult(success=True, exit_code=0, stdout="", stderr="")

    def close(self):
        self.closed = True


@pytest.mark.parametrize("os_family", ["linux", "windows"])
def test_normal_apply_path_realizes_both_account_auth_methods_without_output_exposure(os_family: str):
    accounts = (
        RaesPlanAccount(
            username="alice",
            target_address="node.web",
            auth_method="password",
            password_strength="strong",
        ),
        RaesPlanAccount(username="bob", target_address="node.web", auth_method="key"),
    )
    clients = _clients()
    ssh_ops, _ = _secret_ops()
    account_ops, _ = _account_secret_ops()
    executors: list[_RecordingCredentialExecutor] = []

    def execution_builder(instance_output, **_kwargs):
        executor = _RecordingCredentialExecutor()
        executors.append(executor)
        return GuestExecutionContext(
            executor=executor,
            target=instance_output["private_ip"],
            document_name="AWS-RunPowerShellScript" if os_family == "windows" else "AWS-RunShellScript",
            transport_name="ssh",
        )

    def credential_installer(**kwargs):
        kwargs["secret_ops"] = replace(kwargs["secret_ops"], execution_builder=execution_builder)
        install_instance_account_credentials(**kwargs)

    output = apply_raes_range_cell(
        "req-1",
        7,
        _plan_with_accounts(*accounts, os_family=os_family, count=1),
        _resolver,
        _apply_options(
            _config(),
            clients,
            ssh_ops,
            account_secret_ops=account_ops,
            credential_installer=credential_installer,
        ),
    )

    rendered_scripts = "\n".join(executors[0].scripts)
    assert "PASSWORD" not in rendered_scripts
    assert "PASSWORD" in "\n".join(value or "" for value in executors[0].stdin_inputs)
    assert "ssh-rsa PUBLIC" in rendered_scripts
    if os_family == "windows":
        assert "Set-LocalUser" in rendered_scripts
        assert "$Username = 'bob'" in rendered_scripts
        assert "Match User $Username" in rendered_scripts
        assert "authorizedkeysfile" in rendered_scripts.lower()
    else:
        assert "chpasswd" in rendered_scripts
        assert "chmod 600" in rendered_scripts
        assert "grep -Fqx" in rendered_scripts
    assert executors[0].closed is True
    assert "PASSWORD" not in repr(output)
    assert "ssh-rsa PUBLIC" not in repr(output)
    assert "projects/proj-1/secrets/password" not in repr(output)


def test_participant_projection_uses_only_the_selected_verified_account():
    from raes_access import RealizedAccessBinding
    from raes_gcp_apply import _publish_participant_access

    output = {
        "public_key": "management-public-key",
        "_verified_account_public_keys": {"account.selected": "participant-key", "account.other": "other-key"},
    }
    binding = RealizedAccessBinding("node.web", "ssh", "account.selected", "participant", "key")
    _publish_participant_access(output, (binding,), {"account.selected": "participant-secret-ref"})
    assert output["participant_ssh_public_key"] == "participant-key"
    assert output["ssh_key_secret_arn"] == "participant-secret-ref"
    assert "_verified_account_public_keys" not in output
    assert "other-key" not in repr(output)


def test_undeclared_account_public_keys_are_not_published():
    from raes_gcp_apply import _publish_participant_access

    output = {"public_key": "management-public-key", "_verified_account_public_keys": {"account.other": "other-key"}}
    _publish_participant_access(output, (), {"account.other": "other-secret-ref"})
    assert output == {"public_key": "management-public-key"}


class TestAccountCredentialIntegration:
    def test_installs_each_target_account_on_every_concrete_node_instance(self):
        account = RaesPlanAccount(
            username="alice",
            target_address="node.web",
            auth_method="password",
            password_strength="strong",
        )
        clients = _clients()
        ssh_ops, _ = _secret_ops()
        account_ops, _ = _account_secret_ops()
        installer = MagicMock()

        output = apply_raes_range_cell(
            "req-1",
            7,
            _plan_with_accounts(account),
            _resolver,
            _apply_options(
                _config(),
                clients,
                ssh_ops,
                account_secret_ops=account_ops,
                credential_installer=installer,
            ),
        )

        assert installer.call_count == 2
        assert [call.kwargs["instance_key"] for call in installer.call_args_list] == ["node.web#0", "node.web#1"]
        assert all(call.kwargs["accounts"] == (account,) for call in installer.call_args_list)
        serialized_output = repr(output)
        assert "PASSWORD" not in serialized_output
        assert "projects/proj-1/secrets/password" not in serialized_output

    def test_accounts_for_other_nodes_are_not_installed(self):
        account = RaesPlanAccount(username="alice", target_address="node.other")
        clients = _clients()
        ssh_ops, _ = _secret_ops()
        account_ops, _ = _account_secret_ops()
        installer = MagicMock()

        plan_with_accounts = _plan_with_accounts(account)
        apply_options = _apply_options(
            _config(),
            clients,
            ssh_ops,
            account_secret_ops=account_ops,
            credential_installer=installer,
        )
        with pytest.raises(RaesGcePlanError, match="not present in this plan"):
            apply_raes_range_cell(
                "req-1",
                7,
                plan_with_accounts,
                _resolver,
                apply_options,
            )

        installer.assert_not_called()

    def test_reconcile_existing_instances_reapplies_account_credentials(self):
        account = RaesPlanAccount(username="alice", target_address="node.web", auth_method="password")
        clients = _clients(exists=True)
        ssh_ops, _ = _secret_ops()
        account_ops, _ = _account_secret_ops()
        installer = MagicMock()

        apply_raes_range_cell(
            "req-1",
            7,
            _plan_with_accounts(account),
            _resolver,
            _apply_options(
                _config(),
                clients,
                ssh_ops,
                account_secret_ops=account_ops,
                credential_installer=installer,
            ),
        )

        assert not clients.instances.insert.called
        assert [call.kwargs["instance_key"] for call in installer.call_args_list] == ["node.web#0", "node.web#1"]

    def test_credential_install_failure_cleans_up_every_account_secret(self):
        account = RaesPlanAccount(username="alice", target_address="node.web", auth_method="key")
        clients = _clients()
        ssh_ops, ssh_mocks = _secret_ops()
        account_ops, account_mocks = _account_secret_ops()
        installer = MagicMock(side_effect=RuntimeError("credential setup failed"))

        plan_with_accounts = _plan_with_accounts(account)
        apply_options = _apply_options(
            _config(),
            clients,
            ssh_ops,
            account_secret_ops=account_ops,
            credential_installer=installer,
        )
        with pytest.raises(RuntimeError, match="credential setup failed"):
            apply_raes_range_cell(
                "req-1",
                7,
                plan_with_accounts,
                _resolver,
                apply_options,
            )

        assert ssh_mocks.delete_ssh.call_count == 2
        assert account_mocks.delete.call_count == 2
        assert [call.args[1] for call in account_mocks.delete.call_args_list] == ["node.web#1", "node.web#0"]


def _plan_with_service() -> RaesPlan:
    plan = _plan()  # count=2 node
    node = replace(plan.nodes[0], services=(RaesPlanServicePort(port=80, protocol="tcp", name="http"),))
    return RaesPlan(raes_version=plan.raes_version, nodes=(node,), networks=plan.networks)


class TestServiceFirewallLifecycle:
    def _inserted_service_firewalls(self, clients) -> list[dict]:
        tag = node_tag(7, "node.web")
        return [
            call.kwargs["firewall_resource"]
            for call in clients.firewalls.insert.call_args_list
            if call.kwargs["firewall_resource"].get("target_tags") == [tag]
            and "allowed" in call.kwargs["firewall_resource"]
        ]

    def test_service_firewall_rendered_via_compute_renderer_once_regardless_of_count(self):
        clients = _clients()
        secret_ops, _ = _secret_ops()
        apply_raes_range_cell(
            "req-1", 7, _plan_with_service(), _resolver, _apply_options(_config(), clients, secret_ops)
        )
        bodies = self._inserted_service_firewalls(clients)
        # one shared node-tag rule for the count=2 node (no per-instance duplication)
        assert len(bodies) == 1
        assert bodies[0]["allowed"] == [{"I_p_protocol": "tcp", "ports": ["80"]}]

    def test_destroy_reconstructively_deletes_service_firewall_by_same_name(self):
        built = build_raes_range_cell_plan("req-1", 7, _plan_with_service(), _resolver, _config())
        tag = node_tag(7, "node.web")
        service_names = [fw["name"] for fw in built["firewalls"] if fw.get("target_tags") == [tag] and "allowed" in fw]
        assert len(service_names) == 1

        clients = _clients(exists=True)
        secret_ops, _ = _secret_ops()
        destroy_raes_range_cell(
            "req-1",
            7,
            _plan_with_service(),
            RaesGceDestroyOptions(config=_config(), clients=clients, secret_ops=secret_ops),
        )
        deleted = {call.kwargs.get("firewall") for call in clients.firewalls.delete.call_args_list}
        assert service_names[0] in deleted


class TestDestroy:
    def test_reconstructive_destroy_sweeps_optional_public_web_firewall(self):
        clients = _clients(exists=True)
        secret_ops, _ = _secret_ops()
        destroy_raes_range_cell(
            "req-1", 7, _plan(), RaesGceDestroyOptions(config=_config(), clients=clients, secret_ops=secret_ops)
        )

        assert any(
            call.kwargs.get("firewall") == "shifter-r-7-egress-web" for call in clients.firewalls.delete.call_args_list
        )

    def test_deletes_instances_addresses_firewalls_subnets_network_and_secrets(self):
        clients = _clients(exists=True)
        secret_ops, secret_mocks = _secret_ops()
        destroy_raes_range_cell(
            "req-1", 7, _plan(), RaesGceDestroyOptions(config=_config(), clients=clients, secret_ops=secret_ops)
        )

        assert clients.instances.delete.call_count == 2
        assert clients.addresses.delete.call_count == 2
        assert clients.firewalls.delete.called
        assert clients.subnetworks.delete.call_count == 1
        assert clients.networks.delete.called  # vpc-per-range owns the VPC
        # The range-owned Cloud Router+NAT is torn down (PLAT-238); leaving it was
        # a live resource leak before this fix.
        assert clients.routers.delete.called
        assert secret_mocks.delete_ssh.call_count == 2

    def test_shared_vpc_destroy_keeps_network(self):
        clients = _clients(exists=True)
        secret_ops, _ = _secret_ops()
        destroy_raes_range_cell(
            "req-1",
            7,
            _plan(),
            RaesGceDestroyOptions(
                config=_config("shared-vpc"),
                clients=clients,
                secret_ops=secret_ops,
                allocated_network_cidrs=(("net.lan", "10.90.1.0/24"),),
            ),
        )
        assert not clients.networks.delete.called
        assert clients.routers.delete.called

    def test_deletes_every_per_instance_authored_account_secret(self):
        account = RaesPlanAccount(username="alice", target_address="node.web", auth_method="key")
        clients = _clients(exists=True)
        ssh_ops, _ = _secret_ops()
        account_ops, account_mocks = _account_secret_ops()

        destroy_raes_range_cell(
            "req-1",
            7,
            _plan_with_accounts(account),
            RaesGceDestroyOptions(
                config=_config(),
                clients=clients,
                secret_ops=ssh_ops,
                account_secret_ops=account_ops,
            ),
        )

        assert account_mocks.delete.call_count == 2
        assert [call.args[1] for call in account_mocks.delete.call_args_list] == ["node.web#1", "node.web#0"]

    def test_destroys_a_stale_plan_carrying_source_backed_content_without_bindings(self):
        # #1564: content delivery has no destroy-side ownership -- destroy takes
        # no delivery_bindings parameter at all, and a plan whose source-backed
        # content item was never realized (or the range is being torn down
        # before delivery bindings even existed) must still parse and destroy
        # every owned GCE resource cleanly.
        content = RaesPlanContent(
            name="pkg", content_type="file", target_address="node.web", path="/opt/app/data.bin", source_name="pkg"
        )
        clients = _clients(exists=True)
        secret_ops, secret_mocks = _secret_ops()

        destroy_raes_range_cell(
            "req-1",
            7,
            _plan_with_content(content),
            RaesGceDestroyOptions(config=_config(), clients=clients, secret_ops=secret_ops),
        )

        assert clients.instances.delete.call_count == 1
        assert secret_mocks.delete_ssh.call_count == 1


def _access_plan() -> RaesPlan:
    """One single-instance node with one enabled local key account."""
    node = RaesPlanNode(
        address="node.web",
        name="web",
        os_family="linux",
        count=1,
        network_addresses=("net.lan",),
        image=RaesPlanImage(name="ubuntu"),
    )
    account = RaesPlanAccount(
        username="analyst",
        target_address="node.web",
        address="acct.analyst",
        auth_method="key",
    )
    network = RaesPlanNetwork(address="net.lan", name="lan", cidr="10.9.0.0/24")
    return RaesPlan(raes_version="3.5.0", nodes=(node,), networks=(network,), accounts=(account,))


def _access_transport(channel: str = "ssh") -> dict:
    return {
        "target_address": "node.web",
        "channel": channel,
        "account_address": "acct.analyst",
        "binding_version": 1,
    }


class TestParticipantAccessRealization:
    """A declared endpoint reaches the output only with a verified credential (#1710)."""

    @pytest.mark.parametrize("warm", [False, True])
    def test_participant_identity_readback_failure_prevents_readiness(self, monkeypatch, warm):
        from raes_gcp_apply import realize_access_on_existing_cell

        clients = _clients()
        secret_ops, _ = _secret_ops()
        account_ops, _ = _account_secret_ops()
        options = _apply_options(
            _config(),
            clients,
            secret_ops,
            account_secret_ops=account_ops,
            credential_installer=lambda **_kwargs: {"acct.analyst": "projects/proj-1/secrets/analyst-key"},
        )
        context = MagicMock()
        context.wait_for_ready.return_value = True
        context.executor.run_command.return_value = CommandResult(False, 1, "", "")
        from raes_participant_host_keys import observe_participant_host_keys

        def observe(instances):
            observe_participant_host_keys(instances, execution_builder=lambda *_args, **_kwargs: context)

        module = "raes_gcp_activation_apply" if warm else "raes_gcp_verification"
        monkeypatch.setattr(f"{module}.observe_participant_host_keys", observe, raising=False)
        apply = realize_access_on_existing_cell if warm else apply_raes_range_cell

        def resolver(node):
            return replace(_resolver(node), host_ssh_port=2222)

        with pytest.raises(ValueError, match="identity readback failed"):
            apply("req-1", 7, _access_plan(), resolver, options, access_bindings=[_access_transport()])
        context.close.assert_called_once()

    def test_declared_ssh_publishes_the_account_credential_reference(self):
        clients = _clients()
        secret_ops, _ = _secret_ops()
        account_ops, _mocks = _account_secret_ops()
        options = _apply_options(
            _config(),
            clients,
            secret_ops,
            account_secret_ops=account_ops,
            credential_installer=lambda **_kwargs: {"acct.analyst": "projects/proj-1/secrets/analyst-key"},
        )

        output = apply_raes_range_cell(
            "req-1", 7, _access_plan(), _resolver, options, access_bindings=[_access_transport()]
        )

        instance = output["instances"][0]
        assert instance["participant_access_channels"] == ["ssh"]
        assert instance["ssh_key_secret_arn"] == "projects/proj-1/secrets/analyst-key"
        assert instance["participant_access_usernames"] == {"ssh": "analyst"}

    def test_a_declared_channel_without_a_verified_credential_fails_closed(self):
        """No verified credential means the endpoint was never realized."""
        clients = _clients()
        secret_ops, _ = _secret_ops()
        account_ops, _mocks = _account_secret_ops()
        options = _apply_options(
            _config(),
            clients,
            secret_ops,
            account_secret_ops=account_ops,
            # The installer reports no reference for the declared account.
            credential_installer=lambda **_kwargs: {},
        )

        plan = _access_plan()
        bindings = [_access_transport()]

        with pytest.raises(RaesGcePlanError, match="no verified account credential"):
            apply_raes_range_cell("req-1", 7, plan, _resolver, options, access_bindings=bindings)

    def test_an_unrealizable_binding_is_refused_before_any_cloud_call(self):
        clients = _clients()
        secret_ops, _ = _secret_ops()
        options = _apply_options(_config(), clients, secret_ops)

        plan = _access_plan()
        bindings = [{**_access_transport(), "target_address": "node.ghost"}]

        with pytest.raises(Exception, match="participant access"):
            apply_raes_range_cell("req-1", 7, plan, _resolver, options, access_bindings=bindings)
        assert not clients.instances.insert.called

    def test_no_bindings_leaves_the_instance_participant_free(self):
        clients = _clients()
        secret_ops, _ = _secret_ops()
        account_ops, _mocks = _account_secret_ops()
        options = _apply_options(
            _config(),
            clients,
            secret_ops,
            account_secret_ops=account_ops,
            credential_installer=lambda **_kwargs: {"acct.analyst": "projects/proj-1/secrets/analyst-key"},
        )

        output = apply_raes_range_cell("req-1", 7, _access_plan(), _resolver, options)

        instance = output["instances"][0]
        assert instance["participant_access_channels"] == []
        assert instance["ssh_key_secret_arn"] == ""


_VPN_REALIZATION = {
    "generation": "11111111-2222-3333-4444-555555555555",
    "target_ref": "node.web#0",
    "endpoint": "203.0.113.7",
    "port": 1194,
    "secret_ref": "projects/secrets-proj/secrets/vpn-profile",
}
_VPN_ACCESS = RaesGceVpnAccess("node.web#0", ("10.49.0.0/24",))


class _FakeOpenVpn:
    """Prepared OpenVPN access double recording when the profile is minted."""

    def __init__(self, *, mintable: bool = True) -> None:
        self.mintable = mintable
        self.published = 0

    @staticmethod
    def plan_access() -> RaesGceVpnAccess:
        return _VPN_ACCESS

    def publish(self):
        if not self.mintable:
            raise ValueError("OpenVPN issuer secret has an invalid shape")
        self.published += 1
        return dict(_VPN_REALIZATION)


class TestOpenVpnPoolAccess:
    """The pool rule is part of the apply; the profile is minted after verification (#2480)."""

    def _options(self, clients, openvpn):
        secret_ops, _ = _secret_ops()
        account_ops, _ = _account_secret_ops()
        return _apply_options(
            _config("shared-vpc"),
            clients,
            secret_ops,
            account_secret_ops=account_ops,
            allocated_network_cidrs=(("net.lan", "10.9.0.0/24"),),
            credential_installer=lambda **_kwargs: {"acct.analyst": "projects/proj-1/secrets/analyst-key"},
            openvpn=openvpn,
        )

    def test_apply_admits_the_pool_and_reports_the_profile(self):
        clients = _clients()
        openvpn = _FakeOpenVpn()

        output = apply_raes_range_cell(
            "11111111-2222-3333-4444-555555555555",
            7,
            _access_plan(),
            _resolver,
            self._options(clients, openvpn),
            access_bindings=[_access_transport()],
        )

        assert output["vpn_access"] == _VPN_REALIZATION
        assert openvpn.published == 1
        rules = [call.kwargs["firewall_resource"] for call in clients.firewalls.insert.call_args_list]
        pool = next(rule for rule in rules if rule["name"] == vpn_pool_firewall_name(7))
        assert pool["source_ranges"] == ["10.49.0.0/24"]
        assert pool["allowed"] == [{"I_p_protocol": "tcp", "ports": ["22"]}]
        inserted = [call.kwargs["instance_resource"]["name"] for call in clients.instances.insert.call_args_list]
        assert not any("vpn" in name for name in inserted)

    def test_a_profile_that_cannot_be_minted_fails_and_cleans_up_by_name(self, monkeypatch):
        import raes_gcp_apply

        cleanups = []
        monkeypatch.setattr(
            raes_gcp_apply,
            "destroy_raes_range_cell",
            lambda *_args, **_kwargs: cleanups.append(_args[3].remote_access),
        )

        with pytest.raises(ValueError, match="invalid shape"):
            apply_raes_range_cell(
                "11111111-2222-3333-4444-555555555555",
                7,
                _access_plan(),
                _resolver,
                self._options(_clients(), _FakeOpenVpn(mintable=False)),
                access_bindings=[_access_transport()],
            )

        # Cleanup reconstructs the pool rule by name; it never re-validates the target's channels.
        assert cleanups == [RaesGceVpnAccess("node.web#0")]

    def test_destroy_removes_the_pool_rule(self):
        clients = _clients(exists=True)
        secret_ops, _ = _secret_ops()
        account_ops, _ = _account_secret_ops()

        destroy_raes_range_cell(
            "11111111-2222-3333-4444-555555555555",
            7,
            _access_plan(),
            RaesGceDestroyOptions(
                config=_config("shared-vpc"),
                clients=clients,
                secret_ops=secret_ops,
                account_secret_ops=account_ops,
                allocated_network_cidrs=(("net.lan", "10.9.0.0/24"),),
                remote_access=RaesGceVpnAccess("node.web#0"),
            ),
        )

        deleted = {call.kwargs["firewall"] for call in clients.firewalls.delete.call_args_list}
        assert vpn_pool_firewall_name(7) in deleted

    def test_inventory_counts_a_residual_pool_rule(self):
        from raes_gcp_inventory import inventory_raes_range_cell

        def residual(remote_access, category):
            report = inventory_raes_range_cell(
                "11111111-2222-3333-4444-555555555555",
                7,
                _access_plan(),
                RaesGceDestroyOptions(
                    config=_config("shared-vpc"),
                    clients=_clients(exists=True),
                    allocated_network_cidrs=(("net.lan", "10.9.0.0/24"),),
                    remote_access=remote_access,
                ),
            )
            return {row["category"]: row["count"] for row in report["residual_categories"]}[category]

        with_access = RaesGceVpnAccess("node.web#0")
        assert residual(with_access, "firewalls") == residual(None, "firewalls") + 1
        assert residual(with_access, "instances") == residual(None, "instances")
