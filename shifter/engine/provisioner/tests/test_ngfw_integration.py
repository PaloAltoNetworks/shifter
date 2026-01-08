"""Integration tests for NGFW provisioner workflow.

These tests verify the non-Pulumi code paths work correctly:
1. Event-Handler Contract: Events match what Django handlers expect
2. Workflow Sequence: Events emitted in correct order
3. ID Correlation: Both ngfw_id and cms_ngfw_id propagate correctly
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

# =============================================================================
# Event-Handler Contract Tests
# =============================================================================


class TestNgfwEventHandlerCompatibility:
    """Verify provisioner events are consumable by Django handlers."""

    def test_status_event_has_required_fields_for_engine_handler(self, monkeypatch):
        """Engine handler requires: ngfw_id, user_id, new_status, error_message."""
        monkeypatch.setenv("SNS_RANGE_EVENTS_ARN", "arn:aws:sns:us-east-2:test:topic")

        with patch("events._get_sns_client") as mock_sns:
            mock_client = MagicMock()
            mock_sns.return_value = mock_client

            from events import publish_ngfw_status_update

            publish_ngfw_status_update(ngfw_id=42, cms_ngfw_id=100, user_id=5, new_status="provisioning")

            # Extract published message
            msg = json.loads(mock_client.publish.call_args.kwargs["Message"])

            # These fields are required by engine/handlers.py
            assert msg["ngfw_id"] == 42
            assert msg["user_id"] == 5
            assert msg["new_status"] == "provisioning"
            assert "error_message" in msg  # Can be None

    def test_status_event_has_required_fields_for_cms_handler(self, monkeypatch):
        """CMS handler requires: cms_ngfw_id, user_id, new_status."""
        monkeypatch.setenv("SNS_RANGE_EVENTS_ARN", "arn:aws:sns:us-east-2:test:topic")

        with patch("events._get_sns_client") as mock_sns:
            mock_client = MagicMock()
            mock_sns.return_value = mock_client

            from events import publish_ngfw_status_update

            publish_ngfw_status_update(ngfw_id=42, cms_ngfw_id=100, user_id=5, new_status="ready")

            msg = json.loads(mock_client.publish.call_args.kwargs["Message"])

            # These fields are required by cms/handlers.py
            assert msg["cms_ngfw_id"] == 100
            assert msg["user_id"] == 5
            assert msg["new_status"] == "ready"

    def test_provisioned_event_has_resource_fields_for_handlers(self, monkeypatch):
        """Ready event has resource details handlers need to store."""
        monkeypatch.setenv("SNS_RANGE_EVENTS_ARN", "arn:aws:sns:us-east-2:test:topic")

        with patch("events._get_sns_client") as mock_sns:
            mock_client = MagicMock()
            mock_sns.return_value = mock_client

            from events import publish_ngfw_ready

            publish_ngfw_ready(
                ngfw_id=42,
                cms_ngfw_id=100,
                user_id=5,
                instance_id="i-abc123",
                management_ip="10.0.1.10",
                dataplane_ip="10.0.2.10",
                service_name="com.amazonaws.vpce.svc-abc",
                gwlb_arn="arn:aws:elasticloadbalancing:gwlb",
                target_group_arn="arn:aws:elasticloadbalancing:tg",
            )

            # Find the provisioned event (second call after status update)
            calls = mock_client.publish.call_args_list
            provisioned_msg = json.loads(calls[-1].kwargs["Message"])

            # Fields handlers need to update NGFW models
            assert provisioned_msg["instance_id"] == "i-abc123"
            assert provisioned_msg["management_ip"] == "10.0.1.10"
            assert provisioned_msg["dataplane_ip"] == "10.0.2.10"
            assert provisioned_msg["service_name"] == "com.amazonaws.vpce.svc-abc"
            assert provisioned_msg["gwlb_arn"] == "arn:aws:elasticloadbalancing:gwlb"


# =============================================================================
# Workflow Sequence Tests
# =============================================================================


class TestNgfwProvisionWorkflow:
    """Integration tests for provision/deprovision workflows."""

    @pytest.fixture
    def mock_ngfw_db_record(self):
        return {
            "id": 42,
            "cms_ngfw_id": 100,
            "user_id": 5,
            "config": {"name": "test-ngfw"},
            "status": "pending",
        }

    @pytest.fixture
    def mock_env(self, monkeypatch):
        """Set required environment variables."""
        monkeypatch.setenv("AWS_REGION", "us-east-2")
        monkeypatch.setenv("ENVIRONMENT", "dev")
        monkeypatch.setenv("SNS_RANGE_EVENTS_ARN", "arn:aws:sns:us-east-2:test:topic")
        monkeypatch.setenv("DB_HOST", "test-db")
        monkeypatch.setenv("DB_NAME", "shifter")
        monkeypatch.setenv("DB_USER", "test")

    def test_provision_workflow_emits_events_in_order(self, mock_ngfw_db_record, mock_env, mocker):
        """Verify provision emits: provisioning → ready events."""
        mocker.patch("main.get_ngfw_from_db", return_value=mock_ngfw_db_record)
        mocker.patch("main.update_ngfw_status")
        mocker.patch("main._select_or_create_stack")
        mocker.patch("main._set_ngfw_stack_config")

        # Mock Pulumi to succeed with outputs
        mock_subprocess = mocker.patch("subprocess.run")
        mock_subprocess.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps(
                {
                    "instance_id": "i-abc",
                    "management_ip": "10.0.1.10",
                    "dataplane_ip": "10.0.2.10",
                    "service_name": "svc-abc",
                    "gwlb_arn": "arn:gwlb",
                    "target_group_arn": "arn:tg",
                }
            ),
        )

        # Mock orchestrator
        mock_orchestrator = MagicMock()
        mock_orchestrator.orchestrate.return_value = MagicMock(success=True)
        mocker.patch("main.SetupOrchestrator", return_value=mock_orchestrator)
        mocker.patch("main.AWSExecutor")

        # Capture event sequence
        events = []

        def capture_status(*args, **kwargs):
            events.append(("status", kwargs.get("new_status")))

        def capture_ready(**kwargs):
            events.append(("ready", kwargs.get("instance_id")))

        mocker.patch("main.publish_ngfw_status_update", side_effect=capture_status)
        mocker.patch("main.publish_ngfw_ready", side_effect=capture_ready)

        from main import run_ngfw_pulumi

        run_ngfw_pulumi("up", 42)

        # Verify sequence: provisioning status → ready event
        assert len(events) == 2
        assert events[0] == ("status", "provisioning")
        assert events[1][0] == "ready"
        assert events[1][1] == "i-abc"

    def test_deprovision_workflow_emits_events_in_order(self, mock_ngfw_db_record, mock_env, mocker):
        """Verify deprovision emits: deprovisioning → deprovisioned events."""
        mock_ngfw_db_record["status"] = "ready"
        mocker.patch("main.get_ngfw_from_db", return_value=mock_ngfw_db_record)
        mocker.patch("main.update_ngfw_status")
        mocker.patch("main._select_or_create_stack")
        mocker.patch("main._set_ngfw_stack_config")

        # Mock subprocess for Pulumi
        mock_subprocess = mocker.patch("subprocess.run")
        mock_subprocess.return_value = MagicMock(returncode=0, stdout="", stderr="")

        # Mock orchestrator (license deactivation)
        mock_orchestrator = MagicMock()
        mock_orchestrator.orchestrate.return_value = MagicMock(success=True)
        mocker.patch("main.SetupOrchestrator", return_value=mock_orchestrator)
        mocker.patch("main.AWSExecutor")

        # Capture event sequence
        events = []

        def capture_status(*args, **kwargs):
            events.append(("status", kwargs.get("new_status")))

        def capture_destroyed(**kwargs):
            events.append(("destroyed", kwargs.get("ngfw_id")))

        mocker.patch("main.publish_ngfw_status_update", side_effect=capture_status)
        mocker.patch("main.publish_ngfw_destroyed", side_effect=capture_destroyed)

        from main import run_ngfw_pulumi

        run_ngfw_pulumi("destroy", 42)

        # Verify sequence: deprovisioning status → destroyed event
        assert len(events) == 2
        assert events[0] == ("status", "deprovisioning")
        assert events[1] == ("destroyed", 42)

    def test_provision_failure_emits_failed_event_with_error(self, mock_ngfw_db_record, mock_env, mocker):
        """Failed provision emits failed event with error message."""
        mocker.patch("main.get_ngfw_from_db", return_value=mock_ngfw_db_record)
        mocker.patch("main.update_ngfw_status")
        mocker.patch("main._select_or_create_stack")
        mocker.patch("main._set_ngfw_stack_config")

        # Mock Pulumi to fail with non-zero returncode
        # (Using returncode instead of side_effect so cleanup subprocess.run also works)
        mock_subprocess = mocker.patch("subprocess.run")
        mock_subprocess.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Pulumi stack failed: resource limit exceeded",
        )

        mock_failed = mocker.patch("main.publish_ngfw_failed")
        mocker.patch("main.publish_ngfw_status_update")

        from main import run_ngfw_pulumi

        with pytest.raises(RuntimeError, match="NGFW Pulumi up failed"):
            run_ngfw_pulumi("up", 42)

        # Verify failed event was emitted with IDs and error
        mock_failed.assert_called_once()
        call_kwargs = mock_failed.call_args.kwargs
        assert call_kwargs["ngfw_id"] == 42
        assert call_kwargs["cms_ngfw_id"] == 100
        assert call_kwargs["user_id"] == 5
        assert "resource limit" in call_kwargs["error_message"]


# =============================================================================
# ID Correlation Tests
# =============================================================================


class TestNgfwIdCorrelation:
    """Verify both Engine and CMS IDs flow through correctly."""

    def test_get_ngfw_from_db_returns_both_ids(self, mocker):
        """DB lookup returns both ngfw_id and cms_ngfw_id."""
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (42, 100, 5, "{}", "pending")

        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mocker.patch("main.get_db_connection", return_value=mock_conn)

        from main import get_ngfw_from_db

        result = get_ngfw_from_db(42)

        assert result["id"] == 42  # Engine ID
        assert result["cms_ngfw_id"] == 100  # CMS ID
        assert result["user_id"] == 5

    def test_events_correlate_engine_and_cms_ids(self, monkeypatch):
        """Published events include both IDs for handler correlation."""
        monkeypatch.setenv("SNS_RANGE_EVENTS_ARN", "arn:aws:sns:us-east-2:test:topic")

        with patch("events._get_sns_client") as mock_sns:
            mock_client = MagicMock()
            mock_sns.return_value = mock_client

            from events import publish_ngfw_ready

            publish_ngfw_ready(
                ngfw_id=42,
                cms_ngfw_id=100,
                user_id=5,
                instance_id="i-abc",
                management_ip="10.0.1.10",
                dataplane_ip="10.0.2.10",
                service_name="svc",
                gwlb_arn="arn:gwlb",
                target_group_arn="arn:tg",
            )

            # Check provisioned event has both IDs
            calls = mock_client.publish.call_args_list
            provisioned_msg = json.loads(calls[-1].kwargs["Message"])

            assert provisioned_msg["ngfw_id"] == 42
            assert provisioned_msg["cms_ngfw_id"] == 100

    def test_workflow_passes_ids_from_db_to_events(self, mocker, monkeypatch):
        """IDs from get_ngfw_from_db are passed to event functions."""
        monkeypatch.setenv("AWS_REGION", "us-east-2")
        monkeypatch.setenv("ENVIRONMENT", "dev")
        monkeypatch.setenv("SNS_RANGE_EVENTS_ARN", "arn:aws:sns:us-east-2:test:topic")
        monkeypatch.setenv("DB_HOST", "test-db")
        monkeypatch.setenv("DB_NAME", "shifter")
        monkeypatch.setenv("DB_USER", "test")

        # DB returns specific IDs
        mock_db_record = {
            "id": 42,
            "cms_ngfw_id": 999,  # Distinct CMS ID
            "user_id": 77,  # Distinct user ID
            "config": {},
            "status": "pending",
        }
        mocker.patch("main.get_ngfw_from_db", return_value=mock_db_record)
        mocker.patch("main.update_ngfw_status")
        mocker.patch("main._select_or_create_stack")
        mocker.patch("main._set_ngfw_stack_config")

        # Mock Pulumi success
        mock_subprocess = mocker.patch("subprocess.run")
        mock_subprocess.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps(
                {
                    "instance_id": "i-abc",
                    "management_ip": "10.0.1.10",
                    "dataplane_ip": "10.0.2.10",
                    "service_name": "svc",
                    "gwlb_arn": "arn:gwlb",
                    "target_group_arn": "arn:tg",
                }
            ),
        )

        mock_orchestrator = MagicMock()
        mock_orchestrator.orchestrate.return_value = MagicMock(success=True)
        mocker.patch("main.SetupOrchestrator", return_value=mock_orchestrator)
        mocker.patch("main.AWSExecutor")

        # Capture IDs passed to events
        captured_ids = {}

        def capture_ready(**kwargs):
            captured_ids["ngfw_id"] = kwargs["ngfw_id"]
            captured_ids["cms_ngfw_id"] = kwargs["cms_ngfw_id"]
            captured_ids["user_id"] = kwargs["user_id"]

        mocker.patch("main.publish_ngfw_status_update")
        mocker.patch("main.publish_ngfw_ready", side_effect=capture_ready)

        from main import run_ngfw_pulumi

        run_ngfw_pulumi("up", 42)

        # Verify IDs from DB were passed through
        assert captured_ids["ngfw_id"] == 42
        assert captured_ids["cms_ngfw_id"] == 999
        assert captured_ids["user_id"] == 77
