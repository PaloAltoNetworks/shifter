"""Tests for GWLBReconcilePlan.

GWLBReconcilePlan handles drift detection between DB and VPC endpoints.
"""

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from plans.gwlb_reconcile import GWLBReconcilePlan


@dataclass
class MockGWLBReconcileInstance:
    """Mock instance for testing get_context."""

    service_name: str = "com.amazonaws.vpce.us-east-2.vpce-svc-12345"
    known_endpoint_ids: list[str] = None

    def __post_init__(self):
        if self.known_endpoint_ids is None:
            self.known_endpoint_ids = ["vpce-11111", "vpce-22222"]


class TestGWLBReconcilePlan:
    """Tests for GWLBReconcilePlan behavior."""

    def test_describe_step_uses_correct_action(self):
        """Describe step uses describe_endpoints action."""
        plan = GWLBReconcilePlan()
        describe_step = next(s for s in plan.steps if "describe" in s.name.lower() or "endpoint" in s.name.lower())
        assert describe_step.action == "describe_endpoints"
        assert "service_name" in describe_step.params


class TestGWLBReconcilePlanContext:
    """Tests for get_context method."""

    def test_get_context_returns_service_name(self):
        """get_context returns service_name."""
        plan = GWLBReconcilePlan()
        instance = MockGWLBReconcileInstance(service_name="com.amazonaws.vpce.test")
        context = plan.get_context(instance)

        assert context["service_name"] == "com.amazonaws.vpce.test"

    def test_get_context_returns_known_endpoint_ids(self):
        """get_context returns known_endpoint_ids."""
        plan = GWLBReconcilePlan()
        instance = MockGWLBReconcileInstance(known_endpoint_ids=["vpce-99999"])
        context = plan.get_context(instance)

        assert context["known_endpoint_ids"] == ["vpce-99999"]

    def test_get_context_missing_service_name_raises(self):
        """get_context raises if service_name is missing."""
        plan = GWLBReconcilePlan()
        instance = MockGWLBReconcileInstance()
        instance.service_name = None

        with pytest.raises(ValueError, match="service_name"):
            plan.get_context(instance)

    def test_get_context_empty_known_endpoint_ids_allowed(self):
        """get_context allows empty known_endpoint_ids list."""
        plan = GWLBReconcilePlan()
        instance = MockGWLBReconcileInstance(known_endpoint_ids=[])
        context = plan.get_context(instance)

        assert context["known_endpoint_ids"] == []


class TestGWLBReconcilePlanExecution:
    """Tests for plan execution with AWSExecutor."""

    def test_execute_describe_step_calls_aws_executor(self):
        """Describe step calls AWSExecutor.describe_endpoints."""
        plan = GWLBReconcilePlan()
        describe_step = next(s for s in plan.steps if "describe" in s.name.lower() or "endpoint" in s.name.lower())

        mock_executor = MagicMock()
        mock_executor.describe_endpoints.return_value = MagicMock(
            success=True,
            stdout='{"VpcEndpoints": [{"VpcEndpointId": "vpce-12345"}]}',
            stderr="",
        )

        context = {"service_name": "com.amazonaws.vpce.test"}
        params = {k: context[k] for k in describe_step.params}

        method = getattr(mock_executor, describe_step.action)
        result = method(**params)

        mock_executor.describe_endpoints.assert_called_once_with(service_name="com.amazonaws.vpce.test")
        assert result.success is True
