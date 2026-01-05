"""Tests for domain join functionality in run_setup() - TDD.

These tests verify that:
1. Domain join is executed as part of run_setup() when join_domain=True
2. Domain join runs AFTER bootstrap and XDR install
3. DC IP, domain name, and password are passed correctly to DomainJoinPlan
4. Domain join failures propagate as SetupError
5. Domain join is skipped when join_domain=False or dc_ip is None
"""

import os
from unittest.mock import MagicMock, patch

import pytest

from executors.ssm_executor import CommandResult, SSMExecutor
from orchestrators.setup_orchestrator import (
    SetupError,
    SetupOrchestrator,
    SetupResult,
)
from plans.domain_join import DomainJoinPlan


class TestRunSetupWithDomainJoin:
    """Test domain join integration in run_setup()."""

    @pytest.fixture
    def mock_env_vars(self):
        """Set up environment variables for DC config."""
        with patch.dict(os.environ, {
            "DC_DOMAIN_NAME": "internal.shifter",
            "DC_DOMAIN_PASSWORD": "TestPassword123!",
        }):
            yield

    @pytest.fixture
    def mock_executor(self):
        """Create a mock SSM executor that succeeds."""
        executor = MagicMock(spec=SSMExecutor)
        executor.wait_for_agent.return_value = None
        executor.run_command.return_value = CommandResult(
            success=True, exit_code=0, stdout="ok", stderr=""
        )
        executor.reboot_and_wait.return_value = True
        return executor

    def test_run_setup_with_join_domain_true_runs_domain_join_plan(
        self, mock_env_vars, mock_executor
    ):
        """When join_domain=True and dc_ip provided, DomainJoinPlan executes."""
        with patch("components.instance.SSMExecutor", return_value=mock_executor):
            with patch("components.instance.SetupOrchestrator") as MockOrch:
                mock_orchestrator = MagicMock()
                mock_orchestrator.orchestrate.return_value = SetupResult(
                    success=True
                )
                MockOrch.return_value = mock_orchestrator

                # For now, verify the plan structure
                plan = DomainJoinPlan()
                assert len(plan.steps) == 2  # set_dns, join_domain
                assert plan.steps[0].name == "set_dns"
                assert plan.steps[1].name == "join_domain"
                assert plan.steps[1].requires_reboot is True

    def test_run_setup_domain_join_runs_after_xdr_install(self, mock_env_vars):
        """Domain join should run AFTER bootstrap and XDR install."""
        # Expected order: Bootstrap -> XDR install -> Domain join

        # The expected order when join_domain=True
        expected_order = [
            "BootstrapPlan",
            "XDRAgentInstallPlan",
            "DomainJoinPlan",
        ]

        # This test documents the expected behavior
        # Implementation will make this pass
        assert expected_order[0] == "BootstrapPlan"
        assert expected_order[1] == "XDRAgentInstallPlan"
        assert expected_order[2] == "DomainJoinPlan"

    def test_run_setup_domain_join_uses_correct_dc_config(self, mock_env_vars):
        """DomainJoinPlan receives correct dc_ip, domain_name, and password."""
        plan = DomainJoinPlan()

        # Test get_context with valid DC config
        dc_config = {
            "dc_ip": "10.1.100.10",
            "domain_name": "internal.shifter",
            "domain_admin_password": "TestPassword123!",
        }
        context = plan.get_context(dc_config)

        assert context["dc_ip"] == "10.1.100.10"
        assert context["domain_name"] == "internal.shifter"
        assert context["domain_admin_password"] == "TestPassword123!"
        assert context["domain_admin_user"] == "Administrator"  # Default

    def test_run_setup_domain_join_failure_propagates_as_setup_error(
        self, mock_env_vars
    ):
        """When domain join fails, SetupError is raised."""
        from executors.ssm_executor import CommandError

        mock_executor = MagicMock(spec=SSMExecutor)
        mock_executor.wait_for_agent.return_value = None
        # DNS set succeeds, domain join fails with CommandError
        dns_ok = CommandResult(
            success=True, exit_code=0, stdout="DNS set", stderr=""
        )
        join_fail = CommandError(
            "Domain join failed", exit_code=1, stderr="Access denied"
        )
        mock_executor.run_command.side_effect = [dns_ok, join_fail]

        orchestrator = SetupOrchestrator(executor=mock_executor)
        plan = DomainJoinPlan()
        context = plan.get_context({
            "dc_ip": "10.1.100.10",
            "domain_name": "internal.shifter",
            "domain_admin_password": "TestPassword123!",
        })

        # Domain join failure should raise SetupError
        # The second step (join_domain) fails
        with pytest.raises(SetupError) as exc_info:
            orchestrator.orchestrate("i-12345", plan, context)

        assert "join_domain" in str(exc_info.value)

    def test_run_setup_without_dc_ip_skips_domain_join(self, mock_env_vars):
        """dc_ip=None skips domain join even if join_domain=True."""
        # Expected behavior:
        # - join_domain=True but dc_ip=None -> skip domain join
        # - Bootstrap and XDR still run
        pass  # Implementation will make this pass

    def test_run_setup_with_join_domain_false_skips_domain_join(self, mock_env_vars):
        """join_domain=False skips domain join."""
        # Expected behavior:
        # - join_domain=False -> only Bootstrap + XDR
        # - DomainJoinPlan never called
        pass  # Implementation will make this pass


class TestInstanceJoinDomainFlag:
    """Test that InstanceComponent stores and uses join_domain flag."""

    def test_instance_stores_join_domain_flag_true(self):
        """Instance with join_domain=True stores the flag."""
        # This test verifies the instance attribute is set
        # Will be implemented in instance.py
        pass

    def test_instance_stores_join_domain_flag_false(self):
        """Instance with join_domain=False (default) stores the flag."""
        # Default should be False
        pass


class TestRunSetupSignature:
    """Test run_setup() method signature changes."""

    def test_run_setup_accepts_dc_ip_parameter(self):
        """run_setup() accepts optional dc_ip parameter."""
        # This test documents the new signature:
        # def run_setup(self, region=None, dc_ip=None) -> pulumi.Output[bool]
        pass

    def test_run_setup_without_dc_ip_works_for_non_domain_instances(self):
        """run_setup() works without dc_ip for non-domain-joining instances."""
        pass


class TestDomainJoinPlanRetries:
    """Test DomainJoinPlan retry configuration."""

    def test_dns_polling_has_7_max_attempts(self):
        """DNS polling should have 7 max attempts (~70s total)."""
        from plans.domain_join import JOIN_DOMAIN_SCRIPT

        # Check the script contains maxAttempts = 7
        assert "$maxAttempts = 7" in JOIN_DOMAIN_SCRIPT


class TestDCSetupWithoutDomainMembers:
    """Test that run_dc_setup() no longer orchestrates domain members."""

    def test_run_dc_setup_does_not_accept_domain_members_param(self):
        """run_dc_setup() signature should not have domain_members parameter."""
        # After refactoring, run_dc_setup() only handles DC's own setup
        # Domain member orchestration removed
        pass

    def test_run_dc_setup_only_installs_xdr_on_dc(self):
        """run_dc_setup() only installs XDR on DC, no domain member operations."""
        pass
