"""Tests for bounded ACES Active Directory and SPN guest realization (#1561)."""

from __future__ import annotations

import base64
from types import SimpleNamespace
from unittest.mock import MagicMock, call

import gcp_guest_secrets
from aces_active_directory import AcesDirectorySecretOps, default_directory_secret_ops, realize_aces_active_directory
from aces_plan import AcesPlan, AcesPlanAccount, AcesPlanDomain, AcesPlanNetwork, AcesPlanNode
from plans.aces_active_directory import (
    AcesDomainAccountPlan,
    AcesDomainControllerPlan,
    AcesDomainControllerVerificationPlan,
    AcesDomainMemberPlan,
    AcesDomainMemberStatePlan,
    AcesDomainOfflineJoinProvisionPlan,
)


def _domain_plan() -> AcesPlan:
    controller = AcesPlanNode(
        address="provision.node.dc",
        name="dc",
        os_family="windows",
        count=1,
        network_addresses=("provision.network.lan",),
        domain_id="corp",
        domain_role="controller",
        controller_addresses=("provision.node.dc",),
    )
    member = AcesPlanNode(
        address="provision.node.member",
        name="member",
        os_family="windows",
        count=1,
        network_addresses=("provision.network.lan",),
        ordering_dependencies=("provision.node.dc",),
        domain_id="corp",
        domain_role="member",
        controller_addresses=("provision.node.dc",),
    )
    authority = AcesPlanAccount(
        address="provision.account.domain-admin",
        username="Administrator",
        target_address="provision.node.dc",
        password_strength="strong",
        domain_id="corp",
    )
    service = AcesPlanAccount(
        address="provision.account.web-service",
        username="svc-web",
        target_address="provision.node.member",
        spn="HTTP/member.corp.example",
        password_strength="strong",
        domain_ref="corp",
        domain_id="corp",
        ordering_dependencies=("provision.node.member",),
    )
    domain = AcesPlanDomain(
        domain_id="corp",
        profile="active_directory",
        dns_name="corp.example",
        netbios_name="CORP",
        authority_account_address=authority.address,
        controller_addresses=(controller.address,),
        member_addresses=(member.address,),
    )
    return AcesPlan(
        aces_sdl_version="0.23.0",
        nodes=(controller, member),
        networks=(AcesPlanNetwork(address="provision.network.lan", name="lan", cidr="10.70.0.0/24"),),
        accounts=(authority, service),
        domains=(domain,),
    )


def _execution() -> SimpleNamespace:
    return SimpleNamespace(
        executor=MagicMock(),
        target="10.70.0.10",
        document_name="AWS-RunPowerShellScript",
        wait_for_ready=MagicMock(return_value=True),
        close=MagicMock(),
    )


def test_default_directory_secret_ops_binds_each_secret_purpose() -> None:
    ops = default_directory_secret_ops()

    assert ops.ensure_dsrm is gcp_guest_secrets.ensure_aces_domain_dsrm_secret
    assert ops.ensure_authority is gcp_guest_secrets.ensure_aces_domain_authority_secret
    assert ops.ensure_account is gcp_guest_secrets.ensure_aces_domain_account_password_secret
    assert ops.delete_dsrm is gcp_guest_secrets.delete_aces_domain_dsrm_secret
    assert ops.delete_authority is gcp_guest_secrets.delete_aces_domain_authority_secret
    assert ops.delete_account is gcp_guest_secrets.delete_aces_domain_account_secret


def test_directory_realization_orders_controller_member_account_and_closes_channels() -> None:
    controller_bootstrap_execution = _execution()
    controller_authority_execution = _execution()
    member_execution = _execution()
    orchestrator = MagicMock()

    def _orchestrate(_target, plan, _context, _document):
        if isinstance(plan, AcesDomainControllerPlan):
            stdout = "ACES_AD_PROMOTION_APPLIED"
        elif isinstance(plan, AcesDomainMemberStatePlan):
            machine = base64.b64encode(b"MEMBER01").decode("ascii")
            stdout = f"ACES_AD_MEMBER_JOIN_REQUIRED:{machine}"
        else:
            stdout = ""
        return SimpleNamespace(success=True, step_results=[SimpleNamespace(stdout=stdout)])

    orchestrator.orchestrate.side_effect = _orchestrate
    offline_blob = base64.b64encode(b"machine-scoped-odj-package").decode("ascii")
    controller_authority_execution.executor.run_command.return_value = SimpleNamespace(
        success=True,
        stdout=offline_blob,
        stderr="",
    )
    secrets = SimpleNamespace(
        ensure_dsrm=MagicMock(return_value=("secret/dsrm", "DSRM-PASSWORD")),
        ensure_authority=MagicMock(return_value=("secret/authority", "AUTHORITY-PASSWORD")),
        ensure_account=MagicMock(return_value=("secret/account", "ACCOUNT-PASSWORD")),
        delete_dsrm=MagicMock(),
        delete_authority=MagicMock(),
        delete_account=MagicMock(),
    )

    def _execution_builder(output, **_kwargs):
        if output["uuid"] == "provision.node.member#0":
            return member_execution
        if output.get("gcp_host_ssh_username") == "Administrator":
            return controller_authority_execution
        return controller_bootstrap_execution

    secret_ops = AcesDirectorySecretOps(
        ensure_dsrm=secrets.ensure_dsrm,
        ensure_authority=secrets.ensure_authority,
        ensure_account=secrets.ensure_account,
        delete_dsrm=secrets.delete_dsrm,
        delete_authority=secrets.delete_authority,
        delete_account=secrets.delete_account,
        execution_builder=_execution_builder,
        orchestrator_factory=lambda _executor: orchestrator,
    )
    outputs = [
        {"uuid": "provision.node.dc#0", "private_ip": "10.70.0.10"},
        {"uuid": "provision.node.member#0", "private_ip": "10.70.0.11"},
    ]

    realize_aces_active_directory(range_id=7, aces_plan=_domain_plan(), instance_outputs=outputs, secret_ops=secret_ops)

    plan_types = [type(call.args[1]) for call in orchestrator.orchestrate.call_args_list]
    assert plan_types == [
        AcesDomainControllerPlan,
        AcesDomainControllerVerificationPlan,
        AcesDomainMemberStatePlan,
        AcesDomainMemberPlan,
        AcesDomainAccountPlan,
    ]
    secrets.ensure_dsrm.assert_called_once_with(7, "corp")
    secrets.ensure_authority.assert_called_once_with(7, "corp", "strong")
    secrets.ensure_account.assert_called_once_with(7, "corp", "provision.account.web-service", "strong")
    controller_bootstrap_execution.wait_for_ready.assert_called_once_with(timeout_seconds=60)
    controller_authority_execution.executor.reboot_and_wait.assert_called_once_with(
        controller_authority_execution.target,
        timeout_seconds=1200,
        document_name="AWS-RunPowerShellScript",
    )
    controller_authority_execution.wait_for_ready.assert_called_once_with(timeout_seconds=600)
    member_execution.wait_for_ready.assert_called_once()
    offline_join_call = controller_authority_execution.executor.run_command.call_args
    assert "djoin.exe /provision" in offline_join_call.args[1]
    assert "AUTHORITY-PASSWORD" not in str(offline_join_call)
    member_plan = orchestrator.orchestrate.call_args_list[3].args[1]
    assert isinstance(member_plan, AcesDomainMemberPlan)
    assert "AUTHORITY-PASSWORD" not in str(member_plan.get_context({}))
    controller_bootstrap_execution.close.assert_called_once()
    controller_authority_execution.close.assert_called_once()
    member_execution.close.assert_called_once()


def test_secret_bearing_plans_keep_values_out_of_powershell_source_and_verify_readback() -> None:
    controller = AcesDomainControllerPlan(
        dns_name="corp.example",
        netbios_name="CORP",
        authority_username="Administrator",
        dsrm_password="DSRM-PASSWORD",
        authority_password="AUTHORITY-PASSWORD",
    )
    controller_verification = AcesDomainControllerVerificationPlan(
        dns_name="corp.example",
        netbios_name="CORP",
        authority_username="Administrator",
        authority_password="AUTHORITY-PASSWORD",
    )
    member_state = AcesDomainMemberStatePlan(dns_name="corp.example", controller_ip="10.70.0.10")
    offline_join = AcesDomainOfflineJoinProvisionPlan(dns_name="corp.example", machine_name="MEMBER01")
    member = AcesDomainMemberPlan(
        dns_name="corp.example",
        controller_ip="10.70.0.10",
        offline_join_blob="OFFLINE-JOIN-BLOB",
    )
    account = AcesDomainAccountPlan(
        dns_name="corp.example",
        username="svc-web",
        password="ACCOUNT-PASSWORD",
        spn="HTTP/member.corp.example",
    )

    source = "\n".join(
        step.script
        for plan in (controller, controller_verification, member_state, offline_join, member, account)
        for step in plan.steps
    )
    assert "DSRM-PASSWORD" not in source
    assert "AUTHORITY-PASSWORD" not in source
    assert "ACCOUNT-PASSWORD" not in source
    assert "HTTP/member.corp.example" not in source
    assert "setspn.exe" in source
    assert "djoin.exe /provision" in source
    assert "djoin.exe /requestODJ" in source
    assert "Add-Computer" not in source
    assert "Get-ADUser" in source
    assert "Get-LocalUser" in source
    assert "Get-ADDomainController -Identity $env:COMPUTERNAME" in controller.steps[0].script
    assert "Get-ADDomainController -Identity $env:COMPUTERNAME" in controller_verification.verify_step.script
    assert "Get-ADDomainController -Discover" not in source + controller_verification.verify_step.script
    assert "servicePrincipalName" in source
    account_without_spn = (
        AcesDomainAccountPlan(
            dns_name="corp.example",
            username="plain-domain-user",
            password="ACCOUNT-PASSWORD",
            spn=None,
        )
        .steps[0]
        .script
    )
    assert account_without_spn.rindex("$readback = Get-ADUser") > account_without_spn.index("if ($Spn)")
    assert "if (-not $readback.Enabled)" in account_without_spn
    assert "Write-Host $_" not in source
    assert "$_.Exception" not in source
    assert all(
        step.stdin_input
        for plan in (controller, controller_verification, member_state, offline_join, member, account)
        for step in plan.steps
    )


def test_reconcile_falls_back_to_domain_authority_without_rebooting_again() -> None:
    unavailable_bootstrap = _execution()
    unavailable_bootstrap.wait_for_ready.side_effect = TimeoutError
    authority_execution = _execution()
    member_execution = _execution()
    orchestrator = MagicMock()

    def _orchestrate(_target, plan, _context, _document):
        if isinstance(plan, AcesDomainControllerPlan):
            stdout = "ACES_AD_PROMOTION_VERIFIED"
        elif isinstance(plan, AcesDomainMemberStatePlan):
            machine = base64.b64encode(b"MEMBER01").decode("ascii")
            stdout = f"ACES_AD_MEMBER_ALREADY_JOINED:{machine}"
        else:
            stdout = ""
        return SimpleNamespace(success=True, step_results=[SimpleNamespace(stdout=stdout)])

    orchestrator.orchestrate.side_effect = _orchestrate

    def _execution_builder(output, **_kwargs):
        if output["uuid"] == "provision.node.member#0":
            return member_execution
        if output.get("gcp_host_ssh_username") == "Administrator":
            return authority_execution
        return unavailable_bootstrap

    secret_ops = AcesDirectorySecretOps(
        ensure_dsrm=MagicMock(return_value=("secret/dsrm", "DSRM-PASSWORD")),
        ensure_authority=MagicMock(return_value=("secret/authority", "AUTHORITY-PASSWORD")),
        ensure_account=MagicMock(return_value=("secret/account", "ACCOUNT-PASSWORD")),
        delete_dsrm=MagicMock(),
        delete_authority=MagicMock(),
        delete_account=MagicMock(),
        execution_builder=_execution_builder,
        orchestrator_factory=lambda _executor: orchestrator,
    )
    outputs = [
        {"uuid": "provision.node.dc#0", "private_ip": "10.70.0.10"},
        {"uuid": "provision.node.member#0", "private_ip": "10.70.0.11"},
    ]

    realize_aces_active_directory(range_id=7, aces_plan=_domain_plan(), instance_outputs=outputs, secret_ops=secret_ops)

    unavailable_bootstrap.close.assert_called_once()
    authority_execution.executor.reboot_and_wait.assert_not_called()
    authority_execution.executor.run_command.assert_not_called()
    assert not any(isinstance(item.args[1], AcesDomainMemberPlan) for item in orchestrator.orchestrate.call_args_list)
    authority_execution.wait_for_ready.assert_has_calls(
        [
            call(timeout_seconds=600),
            call(timeout_seconds=600),
        ]
    )
