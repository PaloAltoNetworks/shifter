"""Tests for GWLBRemoveRoutePlan.

GWLBRemoveRoutePlan handles removing GWLB routing when a range is destroyed.
"""

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest


@dataclass
class MockRemoveRouteInstance:
    """Mock instance for testing get_context."""

    endpoint_id: str = "vpce-12345"
    route_table_id: str = "rtb-12345"


class TestGWLBRemoveRoutePlan:
    """Tests for GWLBRemoveRoutePlan behavior."""

    def test_route_deletion_before_endpoint_deletion(self):
        """Route deletion must come before endpoint deletion."""
        from plans.gwlb_remove_route import GWLBRemoveRoutePlan

        plan = GWLBRemoveRoutePlan()
        step_names = [s.name for s in plan.steps]

        route_idx = next(i for i, n in enumerate(step_names) if "route" in n.lower())
        endpoint_idx = next(i for i, n in enumerate(step_names) if "endpoint" in n.lower())
        assert route_idx < endpoint_idx

    def test_steps_use_correct_actions_and_params(self):
        """Steps use correct AWSExecutor actions with required params."""
        from plans.gwlb_remove_route import GWLBRemoveRoutePlan

        plan = GWLBRemoveRoutePlan()

        route_step = next(s for s in plan.steps if "route" in s.name.lower())
        assert route_step.action == "delete_route"
        assert "route_table_id" in route_step.params
        assert "destination" in route_step.params

        endpoint_step = next(s for s in plan.steps if "endpoint" in s.name.lower())
        assert endpoint_step.action == "delete_endpoint"
        assert "endpoint_id" in endpoint_step.params


class TestGWLBRemoveRoutePlanContext:
    """Tests for get_context method."""

    def test_get_context_returns_required_fields(self):
        """get_context returns endpoint_id, route_table_id, and default destination."""
        from plans.gwlb_remove_route import GWLBRemoveRoutePlan

        plan = GWLBRemoveRoutePlan()
        instance = MockRemoveRouteInstance(endpoint_id="vpce-99999", route_table_id="rtb-99999")
        context = plan.get_context(instance)

        assert context["endpoint_id"] == "vpce-99999"
        assert context["route_table_id"] == "rtb-99999"
        assert context["destination"] == "0.0.0.0/0"

    def test_get_context_missing_endpoint_id_raises(self):
        """get_context raises if endpoint_id is missing."""
        from plans.gwlb_remove_route import GWLBRemoveRoutePlan

        plan = GWLBRemoveRoutePlan()
        instance = MockRemoveRouteInstance()
        instance.endpoint_id = None

        with pytest.raises(ValueError, match="endpoint_id"):
            plan.get_context(instance)

    def test_get_context_missing_route_table_id_raises(self):
        """get_context raises if route_table_id is missing."""
        from plans.gwlb_remove_route import GWLBRemoveRoutePlan

        plan = GWLBRemoveRoutePlan()
        instance = MockRemoveRouteInstance()
        instance.route_table_id = None

        with pytest.raises(ValueError, match="route_table_id"):
            plan.get_context(instance)


class TestGWLBRemoveRoutePlanExecution:
    """Tests for plan execution with AWSExecutor."""

    def test_execute_delete_route_step_calls_aws_executor(self):
        """Delete route step calls AWSExecutor.delete_route."""
        from plans.gwlb_remove_route import GWLBRemoveRoutePlan

        plan = GWLBRemoveRoutePlan()
        route_step = next(s for s in plan.steps if "route" in s.name.lower())

        mock_executor = MagicMock()
        mock_executor.delete_route.return_value = MagicMock(success=True, stdout="{}", stderr="")

        context = {"route_table_id": "rtb-12345", "destination": "0.0.0.0/0"}
        params = {k: context[k] for k in route_step.params}

        method = getattr(mock_executor, route_step.action)
        result = method(**params)

        mock_executor.delete_route.assert_called_once_with(
            route_table_id="rtb-12345",
            destination="0.0.0.0/0",
        )
        assert result.success is True

    def test_execute_delete_endpoint_step_calls_aws_executor(self):
        """Delete endpoint step calls AWSExecutor.delete_endpoint."""
        from plans.gwlb_remove_route import GWLBRemoveRoutePlan

        plan = GWLBRemoveRoutePlan()
        endpoint_step = next(s for s in plan.steps if "endpoint" in s.name.lower())

        mock_executor = MagicMock()
        mock_executor.delete_endpoint.return_value = MagicMock(success=True, stdout="{}", stderr="")

        context = {"endpoint_id": "vpce-12345"}
        params = {k: context[k] for k in endpoint_step.params}

        method = getattr(mock_executor, endpoint_step.action)
        result = method(**params)

        mock_executor.delete_endpoint.assert_called_once_with(endpoint_id="vpce-12345")
        assert result.success is True
