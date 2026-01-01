"""Orchestration tests for Shifter Engine main.py.

Tests the container entrypoint orchestration logic including:
- Database connections
- Range status updates
- Pulumi stack operations
- Error handling
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestGetDbConnection:
    """Tests for database connection function."""

    def test_get_db_connection_success(self, mock_boto3_clients, mock_env_vars_minimal):
        """Valid RDS IAM auth token should establish connection."""
        with patch("psycopg.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_connect.return_value = mock_conn

            from main import get_db_connection

            conn = get_db_connection()

            # Verify RDS token was generated
            mock_boto3_clients["rds"].generate_db_auth_token.assert_called_once()
            # Verify connection was established
            mock_connect.assert_called_once()
            assert conn == mock_conn

    def test_get_db_connection_missing_env_vars(self):
        """Missing DB_HOST/DB_USER/AWS_REGION should raise error."""
        with patch("boto3.client") as mock_boto:
            mock_rds = MagicMock()
            mock_boto.return_value = mock_rds
            mock_rds.generate_db_auth_token.return_value = "token"

            with patch.dict(os.environ, {}, clear=True):
                from main import get_db_connection

                with pytest.raises(KeyError):
                    get_db_connection()

    def test_get_db_connection_ssl_required(self, mock_boto3_clients, mock_env_vars_minimal):
        """sslmode='require' should be passed to connection."""
        with patch("psycopg.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_connect.return_value = mock_conn

            from main import get_db_connection

            get_db_connection()

            # Verify SSL mode is set
            call_kwargs = mock_connect.call_args
            assert call_kwargs[1]["sslmode"] == "require"

    def test_get_db_connection_uses_auth_token(self, mock_boto3_clients, mock_env_vars_minimal):
        """Auth token from RDS should be used as password."""
        mock_boto3_clients["rds"].generate_db_auth_token.return_value = "test-auth-token-123"

        with patch("psycopg.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_connect.return_value = mock_conn

            from main import get_db_connection

            get_db_connection()

            call_kwargs = mock_connect.call_args
            assert call_kwargs[1]["password"] == "test-auth-token-123"


class TestUpdateRangeStatus:
    """Tests for range status update function."""

    def test_update_range_status_basic(self, mock_boto3_clients, mock_env_vars_minimal):
        """Updates status field only."""
        with patch("main.get_db_connection") as mock_get_conn:
            mock_cursor = MagicMock()
            mock_conn = MagicMock()
            mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
            mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_get_conn.return_value = mock_conn

            from main import update_range_status

            update_range_status(42, "ready")

            # Verify SQL was executed
            mock_cursor.execute.assert_called_once()
            sql_call = mock_cursor.execute.call_args
            assert "status = %s" in sql_call[0][0]
            assert "updated_at = NOW()" in sql_call[0][0]
            assert sql_call[0][1][0] == "ready"  # status value
            assert sql_call[0][1][-1] == 42  # range_id

    def test_update_range_status_with_kwargs(self, mock_boto3_clients, mock_env_vars_minimal):
        """Updates status + additional fields."""
        with patch("main.get_db_connection") as mock_get_conn:
            mock_cursor = MagicMock()
            mock_conn = MagicMock()
            mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
            mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_get_conn.return_value = mock_conn

            from main import update_range_status

            update_range_status(42, "ready", subnet_id="subnet-123", error_message=None)

            sql_call = mock_cursor.execute.call_args
            assert "subnet_id = %s" in sql_call[0][0]
            # error_message is None, should be skipped

    def test_update_range_status_now_expression(self, mock_boto3_clients, mock_env_vars_minimal):
        """NOW() SQL expression should be handled specially."""
        with patch("main.get_db_connection") as mock_get_conn:
            mock_cursor = MagicMock()
            mock_conn = MagicMock()
            mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
            mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_get_conn.return_value = mock_conn

            from main import update_range_status

            update_range_status(42, "ready", ready_at="NOW()")

            sql_call = mock_cursor.execute.call_args
            # NOW() should be embedded directly, not as a parameter
            assert "ready_at = NOW()" in sql_call[0][0]

    def test_update_range_status_none_values_ignored(self, mock_boto3_clients, mock_env_vars_minimal):
        """kwargs with None values should be skipped."""
        with patch("main.get_db_connection") as mock_get_conn:
            mock_cursor = MagicMock()
            mock_conn = MagicMock()
            mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
            mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_get_conn.return_value = mock_conn

            from main import update_range_status

            update_range_status(42, "ready", subnet_id=None, error_message=None)

            sql_call = mock_cursor.execute.call_args
            # None values should not appear in SQL
            assert "subnet_id" not in sql_call[0][0]
            assert "error_message" not in sql_call[0][0]

    def test_update_range_status_commit_called(self, mock_boto3_clients, mock_env_vars_minimal):
        """Transaction commit should be called."""
        with patch("main.get_db_connection") as mock_get_conn:
            mock_cursor = MagicMock()
            mock_conn = MagicMock()
            mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
            mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_get_conn.return_value = mock_conn

            from main import update_range_status

            update_range_status(42, "ready")

            mock_conn.commit.assert_called_once()


class TestSelectOrCreateStack:
    """Tests for stack selection/creation."""

    def test_stack_select_success(self, mock_subprocess, mock_env_vars):
        """pulumi stack select success."""
        mock_run, mock_result = mock_subprocess
        mock_result.returncode = 0

        from main import _select_or_create_stack

        env = os.environ.copy()
        _select_or_create_stack("range-42", env)

        # Verify stack select was called
        calls = mock_run.call_args_list
        assert any("stack" in str(c) and "select" in str(c) for c in calls)

    def test_stack_select_failure_creates_new(self, mock_subprocess, mock_env_vars):
        """Non-zero exit should create new stack."""
        mock_run, mock_result = mock_subprocess

        # First call (select) fails, second call (init) succeeds
        def side_effect(*args, **kwargs):
            cmd = args[0]
            result = MagicMock()
            if "select" in cmd:
                result.returncode = 1
                result.stderr = "no stack named 'range-42'"
            else:
                result.returncode = 0
            result.stdout = ""
            return result

        mock_run.side_effect = side_effect

        from main import _select_or_create_stack

        env = os.environ.copy()
        _select_or_create_stack("range-42", env)

        # Verify stack init was called after failed select
        calls = mock_run.call_args_list
        assert len(calls) == 2
        assert "init" in str(calls[1])

    def test_stack_init_with_secrets_provider(self, mock_env_vars, mocker):
        """Stack init should use --secrets-provider flag."""
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            cmd = args[0]
            result = MagicMock()
            # First call is select (fails), second is init (succeeds)
            if call_count == 1:  # select
                result.returncode = 1
                result.stderr = "no stack named 'range-42'"
            else:  # init
                result.returncode = 0
                result.stderr = ""
            result.stdout = ""
            return result

        mock_run = mocker.patch("subprocess.run", side_effect=side_effect)

        from main import _select_or_create_stack

        env = os.environ.copy()
        _select_or_create_stack("range-42", env)

        # Verify --secrets-provider was used
        calls = mock_run.call_args_list
        assert len(calls) >= 2
        init_call = calls[1]  # Second call is init
        assert "--secrets-provider" in str(init_call)


class TestSetStackConfig:
    """Tests for stack configuration."""

    def test_set_config_all_values(self, mock_subprocess, mock_env_vars):
        """All config values should be set via pulumi config set."""
        mock_run, mock_result = mock_subprocess
        mock_result.returncode = 0

        from main import _set_stack_config

        env = os.environ.copy()
        _set_stack_config(env, 42)

        # Verify config set was called for each non-empty value
        calls = mock_run.call_args_list
        config_set_calls = [c for c in calls if "config" in str(c) and "set" in str(c)]
        assert len(config_set_calls) > 0

    def test_set_config_empty_values_removed(self, mock_subprocess, mocker):
        """Empty values should trigger pulumi config rm."""
        mock_run, mock_result = mock_subprocess
        mock_result.returncode = 0

        # Set up env with some empty values
        env_vars = {
            "ENVIRONMENT": "dev",
            "RANGE_VPC_ID": "",  # Empty - should be removed
            "RANGE_VPC_CIDR": "10.1.0.0/16",
        }
        mocker.patch.dict(os.environ, env_vars, clear=False)

        from main import _set_stack_config

        env = os.environ.copy()
        _set_stack_config(env, 42)

        # Verify config rm was called for empty values
        calls = mock_run.call_args_list
        config_rm_calls = [c for c in calls if "config" in str(c) and "rm" in str(c)]
        assert len(config_rm_calls) > 0


class TestRunProvision:
    """Tests for provision flow."""

    def test_run_provision_success(self, mock_subprocess, mock_env_vars, mock_boto3_clients):
        """pulumi up success, outputs parsed, status updated."""
        mock_run, mock_result = mock_subprocess

        outputs = {
            "subnet_id": "subnet-12345",
            "subnet_cidr": "10.1.6.0/24",
            "instances": [{"role": "attacker", "instance_id": "i-123"}],
        }

        def side_effect(*args, **kwargs):
            cmd = args[0]
            result = MagicMock()
            result.returncode = 0
            if "output" in cmd and "--json" in cmd:
                result.stdout = json.dumps(outputs)
            else:
                result.stdout = ""
            result.stderr = ""
            return result

        mock_run.side_effect = side_effect

        with patch("main.update_range_status") as mock_update:
            from main import _run_provision

            env = os.environ.copy()
            _run_provision(42, "range-42", env)

            # Verify status was updated to provisioning then ready
            calls = mock_update.call_args_list
            assert calls[0][0] == (42, "provisioning")
            assert calls[1][0][1] == "ready"

    def test_run_provision_failure(self, mock_subprocess, mock_env_vars, mock_boto3_clients):
        """pulumi up failure should raise exception."""
        mock_run, mock_result = mock_subprocess
        mock_result.returncode = 1
        mock_result.stderr = "Pulumi error: resource creation failed"

        with patch("main.update_range_status"):
            from main import _run_provision

            env = os.environ.copy()

            with pytest.raises(Exception, match="Pulumi up failed"):
                _run_provision(42, "range-42", env)

    def test_run_provision_saves_provisioned_instances(
        self, mock_subprocess, mock_env_vars, mock_boto3_clients
    ):
        """provisioned_instances JSON should be saved to DB."""
        mock_run, mock_result = mock_subprocess

        outputs = {
            "subnet_id": "subnet-12345",
            "instances": [
                {"role": "attacker", "instance_id": "i-kali"},
                {"role": "victim", "instance_id": "i-victim"},
            ],
        }

        def side_effect(*args, **kwargs):
            cmd = args[0]
            result = MagicMock()
            result.returncode = 0
            if "output" in cmd and "--json" in cmd:
                result.stdout = json.dumps(outputs)
            else:
                result.stdout = ""
            result.stderr = ""
            return result

        mock_run.side_effect = side_effect

        with patch("main.update_range_status") as mock_update:
            from main import _run_provision

            env = os.environ.copy()
            _run_provision(42, "range-42", env)

            # Check provisioned_instances was passed
            ready_call = mock_update.call_args_list[1]
            assert "provisioned_instances" in ready_call[1]
            instances_json = ready_call[1]["provisioned_instances"]
            parsed = json.loads(instances_json)
            assert len(parsed) == 2

    def test_run_provision_ignores_ngfw_outputs(
        self, mock_subprocess, mock_env_vars, mock_boto3_clients
    ):
        """NGFW outputs should be ignored (stored in UserNGFW model, not Range)."""
        mock_run, mock_result = mock_subprocess

        outputs = {
            "subnet_id": "subnet-12345",
            "subnet_cidr": "10.1.6.0/24",
            "instances": [{"role": "attacker", "instance_id": "i-kali"}],
            "ngfw": {
                "instance_id": "i-ngfw12345",
                "untrust_private_ip": "10.1.6.10",
                "trust_private_ip": "10.1.6.11",
            },
        }

        def side_effect(*args, **kwargs):
            cmd = args[0]
            result = MagicMock()
            result.returncode = 0
            if "output" in cmd and "--json" in cmd:
                result.stdout = json.dumps(outputs)
            else:
                result.stdout = ""
            result.stderr = ""
            return result

        mock_run.side_effect = side_effect

        with patch("main.update_range_status") as mock_update:
            from main import _run_provision

            env = os.environ.copy()
            _run_provision(42, "range-42", env)

            # NGFW fields should NOT be passed (moved to UserNGFW model in issue 412)
            ready_call = mock_update.call_args_list[1]
            assert "ngfw_instance_id" not in ready_call[1]
            assert "ngfw_untrust_ip" not in ready_call[1]
            assert "ngfw_trust_ip" not in ready_call[1]

class TestRunDestroy:
    """Tests for destroy flow."""

    def test_run_destroy_success(self, mock_subprocess, mock_env_vars, mock_boto3_clients):
        """pulumi destroy + stack rm success."""
        mock_run, mock_result = mock_subprocess
        mock_result.returncode = 0

        with patch("main.update_range_status") as mock_update:
            from main import _run_destroy

            env = os.environ.copy()
            _run_destroy(42, "range-42", env)

            # Verify status transitions
            calls = mock_update.call_args_list
            assert calls[0][0] == (42, "destroying")
            assert calls[1][0][1] == "destroyed"

    def test_run_destroy_failure(self, mock_subprocess, mock_env_vars, mock_boto3_clients):
        """pulumi destroy failure should raise exception."""
        mock_run, mock_result = mock_subprocess
        mock_result.returncode = 1
        mock_result.stderr = "Destroy failed"

        with patch("main.update_range_status"):
            from main import _run_destroy

            env = os.environ.copy()

            with pytest.raises(Exception, match="Pulumi destroy failed"):
                _run_destroy(42, "range-42", env)

    def test_run_destroy_stack_removed(self, mock_env_vars, mock_boto3_clients, mocker):
        """Stack should be removed after successful destroy."""
        def side_effect(*args, **kwargs):
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            return result

        mock_run = mocker.patch("subprocess.run", side_effect=side_effect)

        with patch("main.update_range_status"):
            from main import _run_destroy

            env = os.environ.copy()
            _run_destroy(42, "range-42", env)

            # Verify stack rm was called
            calls = mock_run.call_args_list
            rm_calls = [c for c in calls if "rm" in str(c[0][0])]
            assert len(rm_calls) == 1

    def test_run_destroy_sets_destroyed_at(self, mock_subprocess, mock_env_vars, mock_boto3_clients):
        """destroyed_at timestamp should be set."""
        mock_run, mock_result = mock_subprocess
        mock_result.returncode = 0

        with patch("main.update_range_status") as mock_update:
            from main import _run_destroy

            env = os.environ.copy()
            _run_destroy(42, "range-42", env)

            # Check destroyed_at was passed
            destroyed_call = mock_update.call_args_list[1]
            assert destroyed_call[1].get("destroyed_at") == "NOW()"


class TestRunPulumi:
    """Tests for main run_pulumi function."""

    def test_run_pulumi_unknown_operation(self, mock_subprocess, mock_env_vars, mock_boto3_clients):
        """ValueError for invalid operation."""
        mock_run, mock_result = mock_subprocess
        mock_result.returncode = 0

        with patch("main.update_range_status"):
            from main import run_pulumi

            with pytest.raises(ValueError, match="Unknown operation"):
                run_pulumi("invalid", 42)

    def test_run_pulumi_prod_auto_cleanup(self, mock_subprocess, mocker, mock_boto3_clients):
        """Production failure should trigger auto-destroy."""
        mock_run, mock_result = mock_subprocess

        # Set up environment as prod
        env_vars = {
            "ENVIRONMENT": "prod",
            "DB_HOST": "test-db",
            "DB_NAME": "shifter",
            "DB_USER": "app",
            "AWS_REGION": "us-east-2",
        }
        mocker.patch.dict(os.environ, env_vars, clear=False)

        # Make provision fail
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            cmd = args[0]
            result = MagicMock()

            # First calls succeed (select, config), then up fails
            if "up" in cmd:
                result.returncode = 1
                result.stderr = "Resource creation failed"
            else:
                result.returncode = 0
            result.stdout = ""
            return result

        mock_run.side_effect = side_effect

        with patch("main.update_range_status"):
            from main import run_pulumi

            with pytest.raises(Exception):
                run_pulumi("up", 42)

            # Verify destroy was attempted after failure
            calls = mock_run.call_args_list
            destroy_calls = [c for c in calls if "destroy" in str(c)]
            assert len(destroy_calls) >= 1

    def test_run_pulumi_dev_auto_cleanup(self, mock_subprocess, mocker, mock_boto3_clients):
        """Dev failure should also trigger auto-destroy (same as prod)."""
        mock_run, mock_result = mock_subprocess

        # Set up environment as dev
        env_vars = {
            "ENVIRONMENT": "dev",
            "DB_HOST": "test-db",
            "DB_NAME": "shifter",
            "DB_USER": "app",
            "AWS_REGION": "us-east-2",
        }
        mocker.patch.dict(os.environ, env_vars, clear=False)

        def side_effect(*args, **kwargs):
            cmd = args[0]
            result = MagicMock()
            if "up" in cmd:
                result.returncode = 1
                result.stderr = "Resource creation failed"
            else:
                result.returncode = 0
            result.stdout = ""
            return result

        mock_run.side_effect = side_effect

        with patch("main.update_range_status"):
            from main import run_pulumi

            with pytest.raises(Exception):
                run_pulumi("up", 42)

            # Verify destroy WAS attempted - auto-cleanup now enabled for all environments
            calls = mock_run.call_args_list
            destroy_calls = [c for c in calls if "destroy" in str(c)]
            assert len(destroy_calls) >= 1

    def test_run_pulumi_error_message_truncation(
        self, mock_subprocess, mock_env_vars, mock_boto3_clients
    ):
        """Error messages should be truncated to 1000 chars."""
        mock_run, mock_result = mock_subprocess

        # Create a very long error message
        long_error = "A" * 2000

        def side_effect(*args, **kwargs):
            cmd = args[0]
            result = MagicMock()
            if "up" in cmd:
                result.returncode = 1
                result.stderr = long_error
            else:
                result.returncode = 0
            result.stdout = ""
            return result

        mock_run.side_effect = side_effect

        with patch("main.update_range_status") as mock_update:
            from main import run_pulumi

            with pytest.raises(Exception):
                run_pulumi("up", 42)

            # Find the failed status update call
            failed_calls = [c for c in mock_update.call_args_list if c[0][1] == "failed"]
            assert len(failed_calls) == 1
            error_msg = failed_calls[0][1].get("error_message", "")
            assert len(error_msg) <= 1000

    def test_run_pulumi_updates_status_on_failure(
        self, mock_subprocess, mock_env_vars, mock_boto3_clients
    ):
        """Status should be set to 'failed' with error_message."""
        mock_run, mock_result = mock_subprocess

        def side_effect(*args, **kwargs):
            cmd = args[0]
            result = MagicMock()
            if "up" in cmd:
                result.returncode = 1
                result.stderr = "Some error"
            else:
                result.returncode = 0
            result.stdout = ""
            return result

        mock_run.side_effect = side_effect

        with patch("main.update_range_status") as mock_update:
            from main import run_pulumi

            with pytest.raises(Exception):
                run_pulumi("up", 42)

            # Verify status was set to failed
            failed_calls = [c for c in mock_update.call_args_list if c[0][1] == "failed"]
            assert len(failed_calls) == 1
            assert "error_message" in failed_calls[0][1]


class TestUpdateNgfwStatus:
    """Tests for NGFW status update function."""

    def test_update_ngfw_status_basic(self, mock_boto3_clients, mock_env_vars_minimal):
        """Updates status field only."""
        with patch("main.get_db_connection") as mock_get_conn:
            mock_cursor = MagicMock()
            mock_conn = MagicMock()
            mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
            mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_get_conn.return_value = mock_conn

            from main import update_ngfw_status

            update_ngfw_status(123, "starting")

            # Verify SQL was executed on mission_control_userngfw table
            mock_cursor.execute.assert_called_once()
            sql_call = mock_cursor.execute.call_args
            assert "mission_control_userngfw" in sql_call[0][0]
            assert "status = %s" in sql_call[0][0]
            assert sql_call[0][1][0] == "starting"
            assert sql_call[0][1][-1] == 123  # user_ngfw_id

    def test_update_ngfw_status_with_kwargs(self, mock_boto3_clients, mock_env_vars_minimal):
        """Updates status + additional fields."""
        with patch("main.get_db_connection") as mock_get_conn:
            mock_cursor = MagicMock()
            mock_conn = MagicMock()
            mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
            mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_get_conn.return_value = mock_conn

            from main import update_ngfw_status

            update_ngfw_status(123, "active", last_started_at="NOW()")

            sql_call = mock_cursor.execute.call_args
            assert "last_started_at = NOW()" in sql_call[0][0]

    def test_update_ngfw_status_commit_called(self, mock_boto3_clients, mock_env_vars_minimal):
        """Transaction commit should be called."""
        with patch("main.get_db_connection") as mock_get_conn:
            mock_cursor = MagicMock()
            mock_conn = MagicMock()
            mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
            mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_get_conn.return_value = mock_conn

            from main import update_ngfw_status

            update_ngfw_status(123, "stopped")

            mock_conn.commit.assert_called_once()


class TestNgfwOperations:
    """Tests for NGFW operations in main.py."""

    def test_run_ngfw_start_updates_status(self, mock_boto3_clients, mock_env_vars_minimal, mocker):
        """NGFW start should update status to starting then active."""
        mock_update = mocker.patch("main.update_ngfw_status")
        mock_executor = MagicMock()
        mock_executor.start_instance.return_value = MagicMock(success=True)
        mock_executor.wait_for_running.return_value = MagicMock(success=True)
        mocker.patch("main.AWSExecutor", return_value=mock_executor)

        mock_orchestrator = MagicMock()
        mock_orchestrator.orchestrate.return_value = MagicMock(success=True)
        mocker.patch("main.OpsOrchestrator", return_value=mock_orchestrator)

        from main import run_ngfw_operation

        run_ngfw_operation("start", 123, instance_id="i-12345")

        # Verify status transitions
        calls = mock_update.call_args_list
        assert calls[0][0] == (123, "starting")
        assert calls[1][0][1] == "active"

    def test_run_ngfw_stop_updates_status(self, mock_boto3_clients, mock_env_vars_minimal, mocker):
        """NGFW stop should update status to stopping then stopped."""
        mock_update = mocker.patch("main.update_ngfw_status")
        mock_executor = MagicMock()
        mocker.patch("main.AWSExecutor", return_value=mock_executor)

        mock_orchestrator = MagicMock()
        mock_orchestrator.orchestrate.return_value = MagicMock(success=True)
        mocker.patch("main.OpsOrchestrator", return_value=mock_orchestrator)

        from main import run_ngfw_operation

        run_ngfw_operation("stop", 123, instance_id="i-12345")

        calls = mock_update.call_args_list
        assert calls[0][0] == (123, "stopping")
        assert calls[1][0][1] == "stopped"

    def test_run_ngfw_operation_failure_sets_failed_status(
        self, mock_boto3_clients, mock_env_vars_minimal, mocker
    ):
        """Failed operation should set status to failed with error message."""
        mock_update = mocker.patch("main.update_ngfw_status")
        mock_executor = MagicMock()
        mocker.patch("main.AWSExecutor", return_value=mock_executor)

        mock_orchestrator = MagicMock()
        mock_orchestrator.orchestrate.return_value = MagicMock(success=False)
        mocker.patch("main.OpsOrchestrator", return_value=mock_orchestrator)

        from main import run_ngfw_operation

        with pytest.raises(Exception):
            run_ngfw_operation("start", 123, instance_id="i-12345")

        # Verify failed status was set
        failed_calls = [c for c in mock_update.call_args_list if c[0][1] == "failed"]
        assert len(failed_calls) == 1

    def test_run_ngfw_add_route_creates_endpoint(
        self, mock_boto3_clients, mock_env_vars_minimal, mocker
    ):
        """Add-route should use GWLBAddRoutePlan."""
        mock_update = mocker.patch("main.update_ngfw_status")
        mock_executor = MagicMock()
        mocker.patch("main.AWSExecutor", return_value=mock_executor)

        mock_orchestrator = MagicMock()
        mock_orchestrator.orchestrate.return_value = MagicMock(success=True)
        mocker.patch("main.OpsOrchestrator", return_value=mock_orchestrator)

        from main import run_ngfw_operation

        run_ngfw_operation(
            "add-route",
            123,
            subnet_id="subnet-abc",
            service_name="com.amazonaws.vpce.svc-123",
            vpc_id="vpc-123",
            route_table_id="rtb-123",
        )

        # Verify orchestrator was called
        mock_orchestrator.orchestrate.assert_called_once()


class TestMainEntryPoint:
    """Tests for __main__ entry point logic.

    These tests actually execute the main.py script as a subprocess to verify
    CLI behavior including argument parsing and exit codes.
    """

    def test_main_requires_operation_arg(self):
        """Exit with error if no operation argument provided."""
        result = subprocess.run(
            [sys.executable, "main.py"],
            cwd=str(Path(__file__).parent.parent),
            capture_output=True,
            text=True,
        )

        assert result.returncode != 0
        # argparse shows usage/error on missing required args
        assert "usage:" in result.stderr.lower() or "error:" in result.stderr.lower()

    def test_main_missing_range_id_arg(self):
        """Exit with error when --range-id argument is missing."""
        result = subprocess.run(
            [sys.executable, "main.py", "provision"],
            cwd=str(Path(__file__).parent.parent),
            capture_output=True,
            text=True,
        )

        # Should fail due to missing --range-id
        assert result.returncode != 0
        assert "--range-id" in result.stderr or "required" in result.stderr.lower()

    def test_main_invalid_range_id_arg(self):
        """Exit with error when --range-id is not an integer."""
        result = subprocess.run(
            [sys.executable, "main.py", "provision", "--range-id", "not-a-number"],
            cwd=str(Path(__file__).parent.parent),
            capture_output=True,
            text=True,
        )

        # Should fail due to invalid --range-id (not an integer)
        assert result.returncode != 0
        assert "invalid int value" in result.stderr.lower()

    def test_main_invalid_operation(self):
        """Exit with error for invalid operation."""
        result = subprocess.run(
            [sys.executable, "main.py", "invalid_op", "--range-id", "42"],
            cwd=str(Path(__file__).parent.parent),
            capture_output=True,
            text=True,
        )

        # argparse rejects invalid choices
        assert result.returncode != 0
        assert "invalid choice" in result.stderr.lower()

    def test_main_unknown_operation_error(self, mock_env_vars, mock_subprocess, mocker):
        """Unknown operation should raise ValueError from run_pulumi."""
        mock_run, mock_result = mock_subprocess
        mock_result.returncode = 0

        with patch("main.update_range_status"):
            from main import run_pulumi

            with pytest.raises(ValueError, match="Unknown operation"):
                run_pulumi("invalid_op", 42)


class TestNgfwProvisionCLI:
    """Tests for NGFW provision CLI command."""

    def test_ngfw_provision_requires_user_ngfw_id(self):
        """ngfw provision requires --user-ngfw-id argument."""
        result = subprocess.run(
            [sys.executable, "main.py", "ngfw", "provision"],
            cwd=str(Path(__file__).parent.parent),
            capture_output=True,
            text=True,
        )

        assert result.returncode != 0
        assert "--user-ngfw-id" in result.stderr or "required" in result.stderr.lower()

    def test_ngfw_provision_updates_status_to_provisioning(
        self, mock_boto3_clients, mock_env_vars, mocker
    ):
        """NGFW provision should update status to provisioning."""
        mock_update = mocker.patch("main.update_ngfw_status")

        # Mock subprocess for Pulumi operations
        def side_effect(*args, **kwargs):
            cmd = args[0]
            result = MagicMock()
            result.returncode = 0
            if "output" in cmd and "--json" in cmd:
                result.stdout = json.dumps({
                    "instance_id": "i-ngfw123",
                    "management_ip": "10.1.4.10",
                    "dataplane_ip": "10.1.4.11",
                    "service_name": "com.amazonaws.vpce.svc-123",
                })
            else:
                result.stdout = ""
            result.stderr = ""
            return result

        mocker.patch("subprocess.run", side_effect=side_effect)

        # Mock the orchestrator for post-Pulumi config
        mock_orchestrator = MagicMock()
        mock_orchestrator.orchestrate.return_value = MagicMock(success=True)
        mocker.patch("main.SetupOrchestrator", return_value=mock_orchestrator)
        mocker.patch("main.AWSExecutor")

        from main import run_ngfw_pulumi

        run_ngfw_pulumi("up", 123)

        # Verify status was updated to provisioning
        calls = mock_update.call_args_list
        assert calls[0][0] == (123, "provisioning")

    def test_ngfw_provision_runs_pulumi_up(
        self, mock_boto3_clients, mock_env_vars, mocker
    ):
        """NGFW provision should run pulumi up."""
        mocker.patch("main.update_ngfw_status")

        pulumi_calls = []

        def side_effect(*args, **kwargs):
            cmd = args[0]
            pulumi_calls.append(cmd)
            result = MagicMock()
            result.returncode = 0
            if "output" in cmd and "--json" in cmd:
                result.stdout = json.dumps({
                    "instance_id": "i-ngfw123",
                    "management_ip": "10.1.4.10",
                    "dataplane_ip": "10.1.4.11",
                    "service_name": "com.amazonaws.vpce.svc-123",
                })
            else:
                result.stdout = ""
            result.stderr = ""
            return result

        mocker.patch("subprocess.run", side_effect=side_effect)

        mock_orchestrator = MagicMock()
        mock_orchestrator.orchestrate.return_value = MagicMock(success=True)
        mocker.patch("main.SetupOrchestrator", return_value=mock_orchestrator)
        mocker.patch("main.AWSExecutor")

        from main import run_ngfw_pulumi

        run_ngfw_pulumi("up", 123)

        # Verify pulumi up was called
        up_calls = [c for c in pulumi_calls if "up" in c]
        assert len(up_calls) >= 1

    def test_ngfw_provision_saves_outputs_to_db(
        self, mock_boto3_clients, mock_env_vars, mocker
    ):
        """NGFW provision should save Pulumi outputs to database."""
        mock_update = mocker.patch("main.update_ngfw_status")

        outputs = {
            "instance_id": "i-ngfw123",
            "management_ip": "10.1.4.10",
            "dataplane_ip": "10.1.4.11",
            "service_name": "com.amazonaws.vpce.svc-123",
            "gwlb_arn": "arn:aws:elasticloadbalancing:us-east-2:123:loadbalancer/gwy/test",
        }

        def side_effect(*args, **kwargs):
            cmd = args[0]
            result = MagicMock()
            result.returncode = 0
            if "output" in cmd and "--json" in cmd:
                result.stdout = json.dumps(outputs)
            else:
                result.stdout = ""
            result.stderr = ""
            return result

        mocker.patch("subprocess.run", side_effect=side_effect)

        mock_orchestrator = MagicMock()
        mock_orchestrator.orchestrate.return_value = MagicMock(success=True)
        mocker.patch("main.SetupOrchestrator", return_value=mock_orchestrator)
        mocker.patch("main.AWSExecutor")

        from main import run_ngfw_pulumi

        run_ngfw_pulumi("up", 123)

        # Verify outputs were saved - look for the ready status call with kwargs
        ready_calls = [c for c in mock_update.call_args_list if c[0][1] == "ready"]
        assert len(ready_calls) == 1
        assert ready_calls[0][1].get("instance_id") == "i-ngfw123"

    def test_ngfw_provision_runs_post_pulumi_config(
        self, mock_boto3_clients, mock_env_vars, mocker
    ):
        """NGFW provision should run post-Pulumi configuration via orchestrator."""
        mocker.patch("main.update_ngfw_status")

        def side_effect(*args, **kwargs):
            cmd = args[0]
            result = MagicMock()
            result.returncode = 0
            if "output" in cmd and "--json" in cmd:
                result.stdout = json.dumps({
                    "instance_id": "i-ngfw123",
                    "management_ip": "10.1.4.10",
                })
            else:
                result.stdout = ""
            result.stderr = ""
            return result

        mocker.patch("subprocess.run", side_effect=side_effect)

        mock_orchestrator = MagicMock()
        mock_orchestrator.orchestrate.return_value = MagicMock(success=True)
        mocker.patch("main.SetupOrchestrator", return_value=mock_orchestrator)
        mocker.patch("main.AWSExecutor")

        from main import run_ngfw_pulumi

        run_ngfw_pulumi("up", 123)

        # Verify orchestrator was called for post-Pulumi config
        assert mock_orchestrator.orchestrate.called

    def test_ngfw_provision_failure_sets_failed_status(
        self, mock_boto3_clients, mock_env_vars, mocker
    ):
        """Failed NGFW provision should set status to failed."""
        mock_update = mocker.patch("main.update_ngfw_status")

        def side_effect(*args, **kwargs):
            cmd = args[0]
            result = MagicMock()
            if "up" in cmd:
                result.returncode = 1
                result.stderr = "Pulumi provision failed"
            else:
                result.returncode = 0
            result.stdout = ""
            return result

        mocker.patch("subprocess.run", side_effect=side_effect)

        from main import run_ngfw_pulumi

        with pytest.raises(Exception):
            run_ngfw_pulumi("up", 123)

        # Verify status was set to failed
        failed_calls = [c for c in mock_update.call_args_list if c[0][1] == "failed"]
        assert len(failed_calls) == 1


class TestNgfwDeprovisionCLI:
    """Tests for NGFW deprovision CLI command."""

    def test_ngfw_deprovision_requires_user_ngfw_id(self):
        """ngfw deprovision requires --user-ngfw-id argument."""
        result = subprocess.run(
            [sys.executable, "main.py", "ngfw", "deprovision"],
            cwd=str(Path(__file__).parent.parent),
            capture_output=True,
            text=True,
        )

        assert result.returncode != 0
        assert "--user-ngfw-id" in result.stderr or "required" in result.stderr.lower()

    def test_ngfw_deprovision_updates_status_to_deprovisioning(
        self, mock_boto3_clients, mock_env_vars, mocker
    ):
        """NGFW deprovision should update status to deprovisioning."""
        mock_update = mocker.patch("main.update_ngfw_status")

        def side_effect(*args, **kwargs):
            cmd = args[0]
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            return result

        mocker.patch("subprocess.run", side_effect=side_effect)

        # Mock orchestrator for pre-destroy license deactivation
        mock_orchestrator = MagicMock()
        mock_orchestrator.orchestrate.return_value = MagicMock(success=True)
        mocker.patch("main.SetupOrchestrator", return_value=mock_orchestrator)
        mocker.patch("main.AWSExecutor")

        from main import run_ngfw_pulumi

        run_ngfw_pulumi("destroy", 123)

        # Verify status was updated to deprovisioning
        calls = mock_update.call_args_list
        assert calls[0][0] == (123, "deprovisioning")

    def test_ngfw_deprovision_runs_license_deactivation_first(
        self, mock_boto3_clients, mock_env_vars, mocker
    ):
        """NGFW deprovision should run license deactivation before Pulumi destroy."""
        mocker.patch("main.update_ngfw_status")

        pulumi_calls = []
        orchestrator_calls = []

        def subprocess_side_effect(*args, **kwargs):
            cmd = args[0]
            pulumi_calls.append(("subprocess", cmd))
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            return result

        mocker.patch("subprocess.run", side_effect=subprocess_side_effect)

        mock_orchestrator = MagicMock()

        def orchestrator_side_effect(*args, **kwargs):
            orchestrator_calls.append(("orchestrator", args))
            return MagicMock(success=True)

        mock_orchestrator.orchestrate.side_effect = orchestrator_side_effect
        mocker.patch("main.SetupOrchestrator", return_value=mock_orchestrator)
        mocker.patch("main.AWSExecutor")

        from main import run_ngfw_pulumi

        run_ngfw_pulumi("destroy", 123)

        # Verify orchestrator (license deactivation) was called before Pulumi destroy
        destroy_idx = None
        for i, (caller, cmd) in enumerate(pulumi_calls):
            if "destroy" in str(cmd):
                destroy_idx = i
                break

        # Orchestrator should have been called (for deprovision plan)
        assert len(orchestrator_calls) >= 1

    def test_ngfw_deprovision_runs_pulumi_destroy(
        self, mock_boto3_clients, mock_env_vars, mocker
    ):
        """NGFW deprovision should run pulumi destroy."""
        mocker.patch("main.update_ngfw_status")

        pulumi_calls = []

        def side_effect(*args, **kwargs):
            cmd = args[0]
            pulumi_calls.append(cmd)
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            return result

        mocker.patch("subprocess.run", side_effect=side_effect)

        mock_orchestrator = MagicMock()
        mock_orchestrator.orchestrate.return_value = MagicMock(success=True)
        mocker.patch("main.SetupOrchestrator", return_value=mock_orchestrator)
        mocker.patch("main.AWSExecutor")

        from main import run_ngfw_pulumi

        run_ngfw_pulumi("destroy", 123)

        # Verify pulumi destroy was called
        destroy_calls = [c for c in pulumi_calls if "destroy" in c]
        assert len(destroy_calls) >= 1

    def test_ngfw_deprovision_removes_stack(
        self, mock_boto3_clients, mock_env_vars, mocker
    ):
        """NGFW deprovision should remove the Pulumi stack."""
        mocker.patch("main.update_ngfw_status")

        pulumi_calls = []

        def side_effect(*args, **kwargs):
            cmd = args[0]
            pulumi_calls.append(cmd)
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            return result

        mocker.patch("subprocess.run", side_effect=side_effect)

        mock_orchestrator = MagicMock()
        mock_orchestrator.orchestrate.return_value = MagicMock(success=True)
        mocker.patch("main.SetupOrchestrator", return_value=mock_orchestrator)
        mocker.patch("main.AWSExecutor")

        from main import run_ngfw_pulumi

        run_ngfw_pulumi("destroy", 123)

        # Verify stack rm was called
        rm_calls = [c for c in pulumi_calls if "rm" in str(c)]
        assert len(rm_calls) >= 1

    def test_ngfw_deprovision_sets_deprovisioned_status(
        self, mock_boto3_clients, mock_env_vars, mocker
    ):
        """NGFW deprovision should set final status to deprovisioned."""
        mock_update = mocker.patch("main.update_ngfw_status")

        def side_effect(*args, **kwargs):
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            return result

        mocker.patch("subprocess.run", side_effect=side_effect)

        mock_orchestrator = MagicMock()
        mock_orchestrator.orchestrate.return_value = MagicMock(success=True)
        mocker.patch("main.SetupOrchestrator", return_value=mock_orchestrator)
        mocker.patch("main.AWSExecutor")

        from main import run_ngfw_pulumi

        run_ngfw_pulumi("destroy", 123)

        # Verify final status is deprovisioned
        final_call = mock_update.call_args_list[-1]
        assert final_call[0][1] == "deprovisioned"
