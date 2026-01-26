"""Tests for domain join functionality.

Tests DomainJoinPlan structure, context extraction, and error handling.
"""

from unittest.mock import MagicMock

import pytest

from executors.base import CommandResult
from executors.ssm_executor import CommandError, SSMExecutor
from orchestrators.setup_orchestrator import SetupError, SetupOrchestrator
from plans.domain_join import JOIN_DOMAIN_SCRIPT, DomainJoinPlan


class TestDomainJoinPlan:
    """Tests for DomainJoinPlan behavior."""

    def test_plan_has_correct_steps(self):
        """Plan has set_dns and join_domain steps in order."""
        plan = DomainJoinPlan()
        assert len(plan.steps) == 2
        assert plan.steps[0].name == "set_dns"
        assert plan.steps[1].name == "join_domain"

    def test_join_domain_step_requires_reboot(self):
        """Join domain step requires reboot."""
        plan = DomainJoinPlan()
        assert plan.steps[1].requires_reboot is True

    def test_get_context_returns_correct_values(self):
        """get_context extracts dc_ip, domain_name, password."""
        plan = DomainJoinPlan()
        dc_config = {
            "dc_ip": "10.1.100.10",
            "domain_name": "range42.lab",
            "domain_admin_password": "TestPassword123!",
        }
        context = plan.get_context(dc_config)

        assert context["dc_ip"] == "10.1.100.10"
        assert context["domain_name"] == "range42.lab"
        assert context["domain_admin_password"] == "TestPassword123!"
        assert context["domain_admin_user"] == "Administrator"

    def test_dns_polling_has_generous_retry_config(self):
        """DNS polling should have generous retries (~10 mins total)."""
        assert "$maxAttempts = 30" in JOIN_DOMAIN_SCRIPT
        assert "$retryDelaySeconds = 20" in JOIN_DOMAIN_SCRIPT


class TestDomainJoinErrorHandling:
    """Tests for domain join error propagation."""

    def test_domain_join_failure_propagates_as_setup_error(self):
        """When domain join fails, SetupError is raised."""
        mock_executor = MagicMock(spec=SSMExecutor)
        mock_executor.wait_for_agent.return_value = None
        dns_ok = CommandResult(success=True, exit_code=0, stdout="DNS set", stderr="")
        join_fail = CommandError("Domain join failed", exit_code=1, stderr="Access denied")
        mock_executor.run_command.side_effect = [dns_ok, join_fail]

        orchestrator = SetupOrchestrator(executor=mock_executor)
        plan = DomainJoinPlan()
        context = plan.get_context(
            {
                "dc_ip": "10.1.100.10",
                "domain_name": "range42.lab",
                "domain_admin_password": "TestPassword123!",
            }
        )

        with pytest.raises(SetupError) as exc_info:
            orchestrator.orchestrate("i-12345", plan, context)

        assert "join_domain" in str(exc_info.value)
