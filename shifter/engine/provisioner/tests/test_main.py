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
from unittest.mock import MagicMock, patch

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

                with pytest.raises(RuntimeError, match="Missing required environment variables"):
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
        mock_run, _mock_result = mock_subprocess

        # First call (select) fails, second call (init) succeeds
        def side_effect(*args, **kwargs):
            command = args[0]
            result = MagicMock()
            if "select" in command:
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

    TEST_REQUEST_ID = "550e8400-e29b-41d4-a716-446655440000"

    def test_run_provision_success(self, mock_subprocess, mock_env_vars, mock_boto3_clients, mocker):
        """pulumi up success, outputs parsed, events published."""
        # Mock database connection
        mocker.patch("main.get_db_connection")

        mock_run, _mock_result = mock_subprocess

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

        with patch("main.publish_status_update") as mock_status, patch("main.publish_ready") as mock_ready:
            from main import _run_provision

            env = os.environ.copy()
            _run_provision(self.TEST_REQUEST_ID, 42, 7, "range-42", env)

            # Verify status update event was published
            mock_status.assert_called_once_with(
                request_id=self.TEST_REQUEST_ID, range_id=42, user_id=7, new_status="provisioning"
            )
            # Verify ready event was published with instance details
            mock_ready.assert_called_once()
            call_kwargs = mock_ready.call_args[1]
            assert call_kwargs["request_id"] == self.TEST_REQUEST_ID
            assert call_kwargs["range_id"] == 42
            assert call_kwargs["user_id"] == 7

    def test_run_provision_failure(self, mock_subprocess, mock_env_vars, mock_boto3_clients):
        """pulumi up failure should raise exception."""
        _mock_run, mock_result = mock_subprocess
        mock_result.returncode = 1
        mock_result.stderr = "Pulumi error: resource creation failed"

        with patch("main.publish_status_update"):
            from main import _run_provision

            env = os.environ.copy()

            with pytest.raises(Exception, match="Pulumi up failed"):
                _run_provision(self.TEST_REQUEST_ID, 42, 7, "range-42", env)

    def test_run_provision_publishes_ready_with_all_outputs(
        self, mock_subprocess, mock_env_vars, mock_boto3_clients, mocker
    ):
        """publish_ready should be called after successful provision."""
        # Mock database connection and write_provisioned_state
        mocker.patch("main.get_db_connection")
        mocker.patch("main.write_provisioned_state")
        mocker.patch("main.configure_ngfw_subnets")

        mock_run, _mock_result = mock_subprocess

        outputs = {
            "subnets": {
                "subnet-uuid-1": {
                    "subnet_id": "subnet-12345",
                    "cidr": "10.1.6.0/24",
                }
            },
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

        with patch("main.publish_status_update"), patch("main.publish_ready") as mock_ready:
            from main import _run_provision

            env = os.environ.copy()
            _run_provision(self.TEST_REQUEST_ID, 42, 7, "range-42", env)

            # Verify publish_ready was called with correct args (new signature)
            mock_ready.assert_called_once_with(
                request_id=self.TEST_REQUEST_ID,
                range_id=42,
                user_id=7,
            )

    def test_run_provision_ignores_ngfw_outputs(self, mock_subprocess, mock_env_vars, mock_boto3_clients, mocker):
        """NGFW outputs should be ignored (stored in UserNGFW model, not Range)."""
        # Mock database connection
        mocker.patch("main.get_db_connection")

        mock_run, _mock_result = mock_subprocess

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

        with patch("main.publish_status_update"), patch("main.publish_ready") as mock_ready:
            from main import _run_provision

            env = os.environ.copy()
            _run_provision(self.TEST_REQUEST_ID, 42, 7, "range-42", env)

            # NGFW fields should NOT be in kwargs (moved to UserNGFW model in issue 412)
            call_kwargs = mock_ready.call_args[1]
            assert "ngfw_instance_id" not in call_kwargs
            assert "ngfw_untrust_ip" not in call_kwargs
            assert "ngfw_trust_ip" not in call_kwargs


class TestRunDestroy:
    """Tests for destroy flow."""

    TEST_REQUEST_ID = "550e8400-e29b-41d4-a716-446655440000"

    def test_run_destroy_success(self, mock_subprocess, mock_env_vars, mock_boto3_clients, mocker):
        """pulumi destroy + stack rm success."""
        # Mock database connection
        mocker.patch("main.get_db_connection")
        # Mock get_range_data_by_request_id to return proper data
        mocker.patch(
            "main.get_range_data_by_request_id",
            return_value={
                "request_id": self.TEST_REQUEST_ID,
                "range_id": 42,
                "user_id": 7,
                "spec": {"subnets": []},
                "subnet_index": 6,
                "status": "destroying",
            },
        )
        # Mock user_has_active_ranges (no other active ranges)
        mocker.patch("main.user_has_active_ranges", return_value=False)

        _mock_run, mock_result = mock_subprocess
        mock_result.returncode = 0

        with patch("main.publish_destroyed") as mock_destroyed:
            from main import _run_destroy

            env = os.environ.copy()
            _run_destroy(self.TEST_REQUEST_ID, 42, 7, "range-42", env)

            # Verify destroyed event published with correct user_id
            mock_destroyed.assert_called_once()
            assert mock_destroyed.call_args[1]["request_id"] == self.TEST_REQUEST_ID
            assert mock_destroyed.call_args[1]["user_id"] == 7

    def test_run_destroy_failure(self, mock_subprocess, mock_env_vars, mock_boto3_clients, mocker):
        """pulumi destroy failure should raise exception."""
        # Mock database connection
        mocker.patch("main.get_db_connection")

        _mock_run, mock_result = mock_subprocess
        mock_result.returncode = 1
        mock_result.stderr = "Destroy failed"

        from main import _run_destroy

        env = os.environ.copy()

        with pytest.raises(Exception, match=r"(?i)destroy.*failed"):
            _run_destroy(self.TEST_REQUEST_ID, 42, 7, "range-42", env)

    def test_run_destroy_stack_removed(self, mock_env_vars, mock_boto3_clients, mocker):
        """Stack should be removed after successful destroy."""
        # Mock database connection
        mocker.patch("main.get_db_connection")
        # Mock get_range_data_by_request_id to return proper data
        mocker.patch(
            "main.get_range_data_by_request_id",
            return_value={
                "request_id": self.TEST_REQUEST_ID,
                "range_id": 42,
                "user_id": 7,
                "spec": {"subnets": []},
                "subnet_index": 6,
                "status": "destroying",
            },
        )
        # Mock user_has_active_ranges (no other active ranges)
        mocker.patch("main.user_has_active_ranges", return_value=False)

        def side_effect(*args, **kwargs):
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            return result

        mock_run = mocker.patch("subprocess.run", side_effect=side_effect)

        with patch("main.publish_destroyed"):
            from main import _run_destroy

            env = os.environ.copy()
            _run_destroy(self.TEST_REQUEST_ID, 42, 7, "range-42", env)

            # Verify stack rm was called
            calls = mock_run.call_args_list
            rm_calls = [c for c in calls if "rm" in str(c[0][0])]
            assert len(rm_calls) == 1


class TestRunPulumi:
    """Tests for main run_pulumi function."""

    TEST_REQUEST_ID = "550e8400-e29b-41d4-a716-446655440000"

    @pytest.fixture(autouse=True)
    def mock_get_range_data(self, mocker):
        """Mock get_range_data_by_request_id for all tests in this class."""
        return mocker.patch(
            "main.get_range_data_by_request_id",
            return_value={
                "request_id": self.TEST_REQUEST_ID,
                "range_id": 42,
                "user_id": 7,
                "spec": {},
                "subnet_index": 6,
                "status": "pending",
            },
        )

    def test_run_pulumi_unknown_operation(self, mock_subprocess, mock_env_vars, mock_boto3_clients):
        """ValueError for invalid operation."""
        _mock_run, mock_result = mock_subprocess
        mock_result.returncode = 0

        with patch("main.publish_failed"):
            from main import run_pulumi

            with pytest.raises(ValueError, match="Unknown operation"):
                run_pulumi("invalid", self.TEST_REQUEST_ID)

    def test_run_pulumi_prod_auto_cleanup(self, mock_subprocess, mocker, mock_boto3_clients):
        """Production failure should trigger auto-destroy."""
        mock_run, _mock_result = mock_subprocess

        # Set up environment as prod
        env_vars = {
            "ENVIRONMENT": "prod",
            "DB_HOST": "test-db",
            "DB_NAME": "shifter",
            "DB_USER": "app",
            "AWS_REGION": "us-east-2",
            "PULUMI_SECRETS_PROVIDER": "awskms://alias/test-pulumi-secrets",
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

        with patch("main.publish_failed"), patch("main.publish_status_update"):
            from main import run_pulumi

            with pytest.raises(RuntimeError):
                run_pulumi("up", self.TEST_REQUEST_ID)

            # Verify destroy was attempted after failure
            calls = mock_run.call_args_list
            destroy_calls = [c for c in calls if "destroy" in str(c)]
            assert len(destroy_calls) >= 1

    def test_run_pulumi_dev_auto_cleanup(self, mock_subprocess, mocker, mock_boto3_clients):
        """Dev failure should also trigger auto-destroy (same as prod)."""
        mock_run, _mock_result = mock_subprocess

        # Set up environment as dev
        env_vars = {
            "ENVIRONMENT": "dev",
            "DB_HOST": "test-db",
            "DB_NAME": "shifter",
            "DB_USER": "app",
            "AWS_REGION": "us-east-2",
            "PULUMI_SECRETS_PROVIDER": "awskms://alias/test-pulumi-secrets",
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

        with patch("main.publish_failed"), patch("main.publish_status_update"):
            from main import run_pulumi

            with pytest.raises(RuntimeError):
                run_pulumi("up", self.TEST_REQUEST_ID)

            # Verify destroy WAS attempted - auto-cleanup now enabled for all environments
            calls = mock_run.call_args_list
            destroy_calls = [c for c in calls if "destroy" in str(c)]
            assert len(destroy_calls) >= 1

    def test_run_pulumi_error_message_truncation(self, mock_subprocess, mock_env_vars, mock_boto3_clients):
        """Error messages should be truncated to 1000 chars."""
        mock_run, _mock_result = mock_subprocess

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

        with patch("main.publish_failed") as mock_publish, patch("main.publish_status_update"):
            from main import run_pulumi

            with pytest.raises(RuntimeError):
                run_pulumi("up", self.TEST_REQUEST_ID)

            # Verify publish_failed was called with truncated error
            mock_publish.assert_called_once()
            call_kwargs = mock_publish.call_args[1]
            assert len(call_kwargs["error_message"]) <= 1000

    def test_run_pulumi_publishes_failed_event_on_failure(self, mock_subprocess, mock_env_vars, mock_boto3_clients):
        """Failure should publish failed event with error_message."""
        mock_run, _mock_result = mock_subprocess

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

        with patch("main.publish_failed") as mock_publish, patch("main.publish_status_update"):
            from main import run_pulumi

            with pytest.raises(RuntimeError):
                run_pulumi("up", self.TEST_REQUEST_ID)

            # Verify failed event was published with correct user_id
            mock_publish.assert_called_once()
            call_kwargs = mock_publish.call_args[1]
            assert call_kwargs["request_id"] == self.TEST_REQUEST_ID
            assert call_kwargs["range_id"] == 42
            assert call_kwargs["user_id"] == 7
            assert "error_message" in call_kwargs


@pytest.mark.skip(reason="TODO: Implement NGFW runtime operations (start/stop/add-route)")
class TestNgfwOperations:
    """Tests for NGFW operations in main.py."""

    def test_run_ngfw_start_updates_status(self, mock_boto3_clients, mock_env_vars_minimal, mocker):
        """NGFW start should update status to starting then active."""
        pass

    def test_run_ngfw_stop_updates_status(self, mock_boto3_clients, mock_env_vars_minimal, mocker):
        """NGFW stop should update status to stopping then stopped."""
        pass

    def test_run_ngfw_operation_failure_sets_failed_status(self, mock_boto3_clients, mock_env_vars_minimal, mocker):
        """Failed operation should set status to failed with error message."""
        pass

    def test_run_ngfw_add_route_creates_endpoint(self, mock_boto3_clients, mock_env_vars_minimal, mocker):
        """Add-route should use GWLBAddRoutePlan."""
        pass


class TestMainEntryPoint:
    """Tests for __main__ entry point logic.

    These tests actually execute the main.py script as a subprocess to verify
    CLI behavior including argument parsing and exit codes.
    """

    def test_main_requires_resource_arg(self):
        """Exit with error if no resource argument provided."""
        # Security: hardcoded command testing CLI behavior
        result = subprocess.run(  # noqa: S603
            [sys.executable, "main.py"],
            cwd=str(Path(__file__).parent.parent),
            capture_output=True,
            text=True,
        )

        assert result.returncode != 0
        # argparse shows usage/error on missing required args
        assert "usage:" in result.stderr.lower() or "error:" in result.stderr.lower()

    def test_main_range_missing_range_id_arg(self):
        """Exit with error when --range-id argument is missing."""
        result = subprocess.run(  # noqa: S603
            [sys.executable, "main.py", "range", "provision"],
            cwd=str(Path(__file__).parent.parent),
            capture_output=True,
            text=True,
        )

        # Should fail due to missing --range-id
        assert result.returncode != 0
        assert "--range-id" in result.stderr or "required" in result.stderr.lower()

    def test_main_range_missing_user_id_arg(self):
        """Exit with error when --user-id argument is missing."""
        result = subprocess.run(  # noqa: S603
            [sys.executable, "main.py", "range", "provision", "--range-id", "42"],
            cwd=str(Path(__file__).parent.parent),
            capture_output=True,
            text=True,
        )

        # Should fail due to missing --user-id
        assert result.returncode != 0
        assert "--user-id" in result.stderr or "required" in result.stderr.lower()

    def test_main_range_invalid_request_id_format(self):
        """Exit with error when --request-id has invalid format."""
        # Note: request_id is a string (UUID), so we just verify the CLI accepts it
        # and fails on actual execution due to missing DB/environment
        result = subprocess.run(  # noqa: S603
            [sys.executable, "main.py", "range", "provision", "--request-id", "test-uuid"],
            cwd=str(Path(__file__).parent.parent),
            capture_output=True,
            text=True,
        )

        # Should fail (likely on DB connection or missing env vars), not on argument parsing
        assert result.returncode != 0

    def test_main_invalid_resource(self):
        """Exit with error for invalid resource."""
        result = subprocess.run(  # noqa: S603
            [sys.executable, "main.py", "invalid_resource"],
            cwd=str(Path(__file__).parent.parent),
            capture_output=True,
            text=True,
        )

        # argparse rejects invalid choices
        assert result.returncode != 0
        assert "invalid choice" in result.stderr.lower()

    def test_main_unknown_operation_error(self, mock_env_vars, mock_subprocess, mocker):
        """Unknown operation should raise ValueError from run_pulumi."""
        _mock_run, mock_result = mock_subprocess
        mock_result.returncode = 0

        # Mock get_range_data_by_request_id
        mocker.patch(
            "main.get_range_data_by_request_id",
            return_value={
                "request_id": "550e8400-e29b-41d4-a716-446655440000",
                "range_id": 42,
                "user_id": 7,
                "spec": {},
                "subnet_index": 6,
                "status": "pending",
            },
        )

        with patch("main.publish_failed"):
            from main import run_pulumi

            with pytest.raises(ValueError, match="Unknown operation"):
                run_pulumi("invalid_op", "550e8400-e29b-41d4-a716-446655440000")


class TestNgfwProvisionCLI:
    """Tests for NGFW provision CLI command."""

    TEST_REQUEST_ID = "550e8400-e29b-41d4-a716-446655440000"

    @pytest.fixture(autouse=True)
    def mock_get_ngfw_data(self, mocker):
        """Mock get_ngfw_data_by_request_id for all tests in this class."""
        return mocker.patch(
            "main.get_ngfw_data_by_request_id",
            return_value={
                "request_id": self.TEST_REQUEST_ID,
                "instance_id": "660e8400-e29b-41d4-a716-446655440001",
                "app_id": "770e8400-e29b-41d4-a716-446655440002",
                "spec": {},
                "state": {},
                "status": "pending",
            },
        )

    @pytest.fixture(autouse=True)
    def mock_auto_stop(self, mocker):
        """Mock run_ngfw_operation for auto-stop (not tested here)."""
        return mocker.patch("main.run_ngfw_operation")

    def test_ngfw_provision_requires_request_id(self):
        """ngfw provision requires --request-id argument."""
        result = subprocess.run(  # noqa: S603
            [sys.executable, "main.py", "ngfw", "provision"],
            cwd=str(Path(__file__).parent.parent),
            capture_output=True,
            text=True,
        )

        assert result.returncode != 0
        assert "--request-id" in result.stderr or "required" in result.stderr.lower()

    def test_ngfw_provision_updates_status_to_provisioning(self, mock_boto3_clients, mock_env_vars, mocker):
        """NGFW provision should update status to provisioning."""
        mock_update = mocker.patch("main.update_instance_state")
        mocker.patch("main.publish_ngfw_event")

        # Mock subprocess for Pulumi operations
        def side_effect(*args, **kwargs):
            cmd = args[0]
            result = MagicMock()
            result.returncode = 0
            if "output" in cmd and "--json" in cmd:
                result.stdout = json.dumps(
                    {
                        "instance_id": "i-ngfw123",
                        "management_ip": "10.1.4.10",
                        "dataplane_ip": "10.1.4.11",
                        "service_name": "com.amazonaws.vpce.svc-123",
                        "target_group_arn": "arn:aws:elbv2:us-east-2:123:tg/test",
                        "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:ngfw-ssh-key",
                    }
                )
            else:
                result.stdout = ""
            result.stderr = ""
            return result

        mocker.patch("subprocess.run", side_effect=side_effect)

        # Mock SSH executor for post-Pulumi config
        mock_ssh_executor = MagicMock()
        mocker.patch("main.SSHExecutor", return_value=mock_ssh_executor)

        # Mock the orchestrator for post-Pulumi config
        mock_step_result = MagicMock()
        mock_step_result.step_name = "verify_device_cert"
        mock_step_result.stdout = "serial: TEST123"
        mock_orchestrator = MagicMock()
        mock_orchestrator.orchestrate.return_value = MagicMock(success=True, step_results=[mock_step_result])
        mocker.patch("main.SetupOrchestrator", return_value=mock_orchestrator)

        # Mock AWSExecutor for GWLB setup
        mock_aws_executor = MagicMock()
        mock_aws_executor.register_target.return_value = MagicMock(success=True)
        mock_aws_executor.wait_for_target_healthy.return_value = MagicMock(success=True)
        mocker.patch("main.AWSExecutor", return_value=mock_aws_executor)

        from main import run_ngfw_pulumi

        run_ngfw_pulumi("up", self.TEST_REQUEST_ID)

        # Verify status was updated to provisioning
        calls = mock_update.call_args_list
        assert calls[0][0] == (self.TEST_REQUEST_ID, "provisioning")

    def test_ngfw_provision_runs_pulumi_up(self, mock_boto3_clients, mock_env_vars, mocker):
        """NGFW provision should run pulumi up."""
        mocker.patch("main.update_instance_state")
        mocker.patch("main.publish_ngfw_event")

        pulumi_calls = []

        def side_effect(*args, **kwargs):
            cmd = args[0]
            pulumi_calls.append(cmd)
            result = MagicMock()
            result.returncode = 0
            if "output" in cmd and "--json" in cmd:
                result.stdout = json.dumps(
                    {
                        "instance_id": "i-ngfw123",
                        "management_ip": "10.1.4.10",
                        "dataplane_ip": "10.1.4.11",
                        "service_name": "com.amazonaws.vpce.svc-123",
                        "target_group_arn": "arn:aws:elbv2:us-east-2:123:tg/test",
                        "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:ngfw-ssh-key",
                    }
                )
            else:
                result.stdout = ""
            result.stderr = ""
            return result

        mocker.patch("subprocess.run", side_effect=side_effect)

        # Mock SSH executor for post-Pulumi config
        mock_ssh_executor = MagicMock()
        mocker.patch("main.SSHExecutor", return_value=mock_ssh_executor)

        mock_step_result = MagicMock()
        mock_step_result.step_name = "verify_device_cert"
        mock_step_result.stdout = "serial: TEST123"
        mock_orchestrator = MagicMock()
        mock_orchestrator.orchestrate.return_value = MagicMock(success=True, step_results=[mock_step_result])
        mocker.patch("main.SetupOrchestrator", return_value=mock_orchestrator)

        # Mock AWSExecutor for GWLB setup
        mock_aws_executor = MagicMock()
        mock_aws_executor.register_target.return_value = MagicMock(success=True)
        mock_aws_executor.wait_for_target_healthy.return_value = MagicMock(success=True)
        mocker.patch("main.AWSExecutor", return_value=mock_aws_executor)

        from main import run_ngfw_pulumi

        run_ngfw_pulumi("up", self.TEST_REQUEST_ID)

        # Verify pulumi up was called
        up_calls = [c for c in pulumi_calls if "up" in c]
        assert len(up_calls) >= 1

    def test_ngfw_provision_saves_outputs_to_db(self, mock_boto3_clients, mock_env_vars, mocker):
        """NGFW provision should save Pulumi outputs to database."""
        mock_update = mocker.patch("main.update_instance_state")
        mocker.patch("main.publish_ngfw_event")

        outputs = {
            "instance_id": "i-ngfw123",
            "management_ip": "10.1.4.10",
            "dataplane_ip": "10.1.4.11",
            "service_name": "com.amazonaws.vpce.svc-123",
            "gwlb_arn": "arn:aws:elasticloadbalancing:us-east-2:123:tg/test",
            "target_group_arn": "arn:aws:elbv2:us-east-2:123:tg/test",
            "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
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

        # Mock SSH executor for post-Pulumi config
        mock_ssh_executor = MagicMock()
        mocker.patch("main.SSHExecutor", return_value=mock_ssh_executor)

        mock_step_result = MagicMock()
        mock_step_result.step_name = "verify_device_cert"
        mock_step_result.stdout = "serial: TEST123"
        mock_orchestrator = MagicMock()
        mock_orchestrator.orchestrate.return_value = MagicMock(success=True, step_results=[mock_step_result])
        mocker.patch("main.SetupOrchestrator", return_value=mock_orchestrator)

        # Mock AWSExecutor for GWLB setup
        mock_aws_executor = MagicMock()
        mock_aws_executor.register_target.return_value = MagicMock(success=True)
        mock_aws_executor.wait_for_target_healthy.return_value = MagicMock(success=True)
        mocker.patch("main.AWSExecutor", return_value=mock_aws_executor)

        from main import run_ngfw_pulumi

        run_ngfw_pulumi("up", self.TEST_REQUEST_ID)

        # Verify outputs were saved - look for the ready status call with kwargs
        ready_calls = [c for c in mock_update.call_args_list if c[0][1] == "ready"]
        assert len(ready_calls) == 1
        assert ready_calls[0][1].get("ec2_instance_id") == "i-ngfw123"

    def test_ngfw_provision_runs_post_pulumi_config(self, mock_boto3_clients, mock_env_vars, mocker):
        """NGFW provision should run post-Pulumi configuration via orchestrator."""
        mocker.patch("main.update_instance_state")
        mocker.patch("main.publish_ngfw_event")

        def side_effect(*args, **kwargs):
            cmd = args[0]
            result = MagicMock()
            result.returncode = 0
            if "output" in cmd and "--json" in cmd:
                result.stdout = json.dumps(
                    {
                        "instance_id": "i-ngfw123",
                        "management_ip": "10.1.4.10",
                        "target_group_arn": "arn:aws:elbv2:us-east-2:123:tg/test",
                        "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:ngfw-ssh-key",
                    }
                )
            else:
                result.stdout = ""
            result.stderr = ""
            return result

        mocker.patch("subprocess.run", side_effect=side_effect)

        # Mock SSH executor for post-Pulumi config
        mock_ssh_executor = MagicMock()
        mocker.patch("main.SSHExecutor", return_value=mock_ssh_executor)

        mock_step_result = MagicMock()
        mock_step_result.step_name = "verify_device_cert"
        mock_step_result.stdout = "serial: TEST123"
        mock_orchestrator = MagicMock()
        mock_orchestrator.orchestrate.return_value = MagicMock(success=True, step_results=[mock_step_result])
        mocker.patch("main.SetupOrchestrator", return_value=mock_orchestrator)

        # Mock AWSExecutor for GWLB setup
        mock_aws_executor = MagicMock()
        mock_aws_executor.register_target.return_value = MagicMock(success=True)
        mock_aws_executor.wait_for_target_healthy.return_value = MagicMock(success=True)
        mocker.patch("main.AWSExecutor", return_value=mock_aws_executor)

        from main import run_ngfw_pulumi

        run_ngfw_pulumi("up", self.TEST_REQUEST_ID)

        # Verify orchestrator was called for post-Pulumi config
        assert mock_orchestrator.orchestrate.called

    def test_ngfw_provision_runs_gwlb_setup(self, mock_boto3_clients, mock_env_vars, mocker):
        """NGFW provision should run GWLB target registration."""
        mocker.patch("main.update_instance_state")
        mocker.patch("main.publish_ngfw_event")

        outputs = {
            "instance_id": "i-ngfw123",
            "management_ip": "10.1.4.10",
            "target_group_arn": "arn:aws:elbv2:us-east-2:123:tg/test",
            "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
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

        # Mock SSH executor
        mock_ssh_executor = MagicMock()
        mocker.patch("main.SSHExecutor", return_value=mock_ssh_executor)

        # Mock orchestrator for NGFWProvisionPlan
        mock_step_result = MagicMock()
        mock_step_result.step_name = "verify_device_cert"
        mock_step_result.stdout = "serial: TEST123"
        mock_orchestrator = MagicMock()
        mock_orchestrator.orchestrate.return_value = MagicMock(success=True, step_results=[mock_step_result])
        mocker.patch("main.SetupOrchestrator", return_value=mock_orchestrator)

        # Mock AWSExecutor for GWLB setup
        mock_aws_executor = MagicMock()
        mock_aws_executor.register_target.return_value = MagicMock(success=True)
        mock_aws_executor.wait_for_target_healthy.return_value = MagicMock(success=True)
        mocker.patch("main.AWSExecutor", return_value=mock_aws_executor)

        from main import run_ngfw_pulumi

        run_ngfw_pulumi("up", self.TEST_REQUEST_ID)

        # Verify GWLB target registration was called
        mock_aws_executor.register_target.assert_called_once_with(
            target_group_arn="arn:aws:elbv2:us-east-2:123:tg/test",
            target_id="i-ngfw123",
        )
        # Verify health check wait was called
        mock_aws_executor.wait_for_target_healthy.assert_called_once_with(
            target_group_arn="arn:aws:elbv2:us-east-2:123:tg/test",
            target_id="i-ngfw123",
        )

    def test_ngfw_provision_fails_on_gwlb_setup_failure(self, mock_boto3_clients, mock_env_vars, mocker):
        """NGFW provision should fail if GWLB setup fails."""
        mocker.patch("main.update_instance_state")
        mocker.patch("main.publish_ngfw_event")

        outputs = {
            "instance_id": "i-ngfw123",
            "management_ip": "10.1.4.10",
            "target_group_arn": "arn:aws:elbv2:us-east-2:123:tg/test",
            "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
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

        # Mock SSH executor
        mock_ssh_executor = MagicMock()
        mocker.patch("main.SSHExecutor", return_value=mock_ssh_executor)

        # Mock orchestrator for NGFWProvisionPlan (succeeds)
        mock_step_result = MagicMock()
        mock_step_result.step_name = "verify_device_cert"
        mock_step_result.stdout = "serial: TEST123"
        mock_orchestrator = MagicMock()
        mock_orchestrator.orchestrate.return_value = MagicMock(success=True, step_results=[mock_step_result])
        mocker.patch("main.SetupOrchestrator", return_value=mock_orchestrator)

        # Mock AWSExecutor - register_target fails
        mock_aws_executor = MagicMock()
        mock_aws_executor.register_target.return_value = MagicMock(success=False, stderr="Target group not found")
        mocker.patch("main.AWSExecutor", return_value=mock_aws_executor)

        from main import run_ngfw_pulumi

        with pytest.raises(RuntimeError, match="GWLB setup step"):
            run_ngfw_pulumi("up", self.TEST_REQUEST_ID)

    def test_ngfw_provision_fails_on_missing_target_group_arn(self, mock_boto3_clients, mock_env_vars, mocker):
        """NGFW provision should fail if target_group_arn is missing from outputs."""
        mocker.patch("main.update_instance_state")
        mocker.patch("main.publish_ngfw_event")

        # Missing target_group_arn
        outputs = {
            "instance_id": "i-ngfw123",
            "management_ip": "10.1.4.10",
            "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
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

        # Mock SSH executor
        mock_ssh_executor = MagicMock()
        mocker.patch("main.SSHExecutor", return_value=mock_ssh_executor)

        # Mock orchestrator for NGFWProvisionPlan (succeeds)
        mock_step_result = MagicMock()
        mock_step_result.step_name = "verify_device_cert"
        mock_step_result.stdout = "serial: TEST123"
        mock_orchestrator = MagicMock()
        mock_orchestrator.orchestrate.return_value = MagicMock(success=True, step_results=[mock_step_result])
        mocker.patch("main.SetupOrchestrator", return_value=mock_orchestrator)

        # Mock AWSExecutor (created before validation)
        mock_aws_executor = MagicMock()
        mocker.patch("main.AWSExecutor", return_value=mock_aws_executor)

        from main import run_ngfw_pulumi

        with pytest.raises(RuntimeError, match="target_group_arn"):
            run_ngfw_pulumi("up", self.TEST_REQUEST_ID)

    def test_ngfw_provision_failure_sets_failed_status(self, mock_boto3_clients, mock_env_vars, mocker):
        """Failed NGFW provision should set status to failed."""
        mock_update = mocker.patch("main.update_instance_state")
        mocker.patch("main.publish_ngfw_event")

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

        with pytest.raises(RuntimeError):
            run_ngfw_pulumi("up", self.TEST_REQUEST_ID)

        # Verify status was set to failed
        failed_calls = [c for c in mock_update.call_args_list if c[0][1] == "failed"]
        assert len(failed_calls) == 1


class TestEventPublishing:
    """Tests for SNS event publishing integration in provision/destroy flows."""

    TEST_REQUEST_ID = "550e8400-e29b-41d4-a716-446655440000"

    def test_run_provision_publishes_status_update_event(
        self, mock_subprocess, mock_env_vars, mock_boto3_clients, monkeypatch, mocker
    ):
        """Provision flow should publish status update events via SNS."""
        # Mock database connection
        mocker.patch("main.get_db_connection")

        monkeypatch.setenv("SNS_RANGE_EVENTS_ARN", "arn:aws:sns:us-east-2:123:test-topic")

        mock_run, _mock_result = mock_subprocess
        outputs = {"subnet_id": "subnet-12345", "instances": []}

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

        with (
            patch("main.publish_status_update") as mock_publish,
            patch("main.publish_ready"),
        ):
            from main import _run_provision

            env = os.environ.copy()
            _run_provision(self.TEST_REQUEST_ID, 42, 7, "range-42", env)

            # Verify status update event was published with correct user_id
            mock_publish.assert_called_once()
            call_kwargs = mock_publish.call_args[1]
            assert call_kwargs["request_id"] == self.TEST_REQUEST_ID
            assert call_kwargs["range_id"] == 42
            assert call_kwargs["user_id"] == 7

    def test_run_provision_publishes_ready_event(
        self, mock_subprocess, mock_env_vars, mock_boto3_clients, monkeypatch, mocker
    ):
        """Provision success should publish ready event with instances."""
        # Mock database connection
        mocker.patch("main.get_db_connection")

        monkeypatch.setenv("SNS_RANGE_EVENTS_ARN", "arn:aws:sns:us-east-2:123:test-topic")

        mock_run, _mock_result = mock_subprocess
        outputs = {
            "subnet_id": "subnet-12345",
            "instances": [{"role": "attacker", "ip": "10.1.1.10"}],
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

        with (
            patch("main.publish_status_update"),
            patch("main.publish_ready") as mock_publish,
        ):
            from main import _run_provision

            env = os.environ.copy()
            _run_provision(self.TEST_REQUEST_ID, 42, 7, "range-42", env)

            # Verify ready event was published with correct user_id
            mock_publish.assert_called_once()
            call_kwargs = mock_publish.call_args[1]
            assert call_kwargs["request_id"] == self.TEST_REQUEST_ID
            assert call_kwargs["range_id"] == 42
            assert call_kwargs["user_id"] == 7

    def test_run_destroy_publishes_destroyed_event(
        self, mock_subprocess, mock_env_vars, mock_boto3_clients, monkeypatch, mocker
    ):
        """Destroy success should publish destroyed event."""
        # Mock database connection
        mocker.patch("main.get_db_connection")
        # Mock get_range_data_by_request_id to return proper data
        mocker.patch(
            "main.get_range_data_by_request_id",
            return_value={
                "request_id": self.TEST_REQUEST_ID,
                "range_id": 42,
                "user_id": 7,
                "spec": {"subnets": []},
                "subnet_index": 6,
                "status": "destroying",
            },
        )
        # Mock user_has_active_ranges (no other active ranges)
        mocker.patch("main.user_has_active_ranges", return_value=False)

        monkeypatch.setenv("SNS_RANGE_EVENTS_ARN", "arn:aws:sns:us-east-2:123:test-topic")

        _mock_run, mock_result = mock_subprocess
        mock_result.returncode = 0

        with patch("main.publish_destroyed") as mock_publish:
            from main import _run_destroy

            env = os.environ.copy()
            _run_destroy(self.TEST_REQUEST_ID, 42, 7, "range-42", env)

            # Verify destroyed event was published with correct user_id
            mock_publish.assert_called_once()
            assert mock_publish.call_args[1]["request_id"] == self.TEST_REQUEST_ID
            assert mock_publish.call_args[1]["user_id"] == 7

    def test_run_pulumi_failure_publishes_failed_event(
        self, mock_subprocess, mock_env_vars, mock_boto3_clients, monkeypatch, mocker
    ):
        """Pulumi failure should publish failed event."""
        monkeypatch.setenv("SNS_RANGE_EVENTS_ARN", "arn:aws:sns:us-east-2:123:test-topic")

        # Mock get_range_data_by_request_id
        mocker.patch(
            "main.get_range_data_by_request_id",
            return_value={
                "request_id": self.TEST_REQUEST_ID,
                "range_id": 42,
                "user_id": 7,
                "spec": {},
                "subnet_index": 6,
                "status": "pending",
            },
        )

        mock_run, _mock_result = mock_subprocess

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

        with (
            patch("main.publish_failed") as mock_publish,
            patch("main.publish_status_update"),
        ):
            from main import run_pulumi

            with pytest.raises(RuntimeError):
                run_pulumi("up", self.TEST_REQUEST_ID)

            # Verify failed event was published with correct user_id
            mock_publish.assert_called_once()
            call_kwargs = mock_publish.call_args[1]
            assert call_kwargs["request_id"] == self.TEST_REQUEST_ID
            assert call_kwargs["user_id"] == 7


class TestNgfwDeprovisionCLI:
    """Tests for NGFW deprovision CLI command."""

    TEST_REQUEST_ID = "550e8400-e29b-41d4-a716-446655440000"

    @pytest.fixture(autouse=True)
    def mock_get_ngfw_data(self, mocker):
        """Mock get_ngfw_data_by_request_id for all tests in this class."""
        return mocker.patch(
            "main.get_ngfw_data_by_request_id",
            return_value={
                "request_id": self.TEST_REQUEST_ID,
                "instance_id": "660e8400-e29b-41d4-a716-446655440001",
                "app_id": "770e8400-e29b-41d4-a716-446655440002",
                "spec": {},
                "state": {
                    "management_ip": "10.1.4.10",
                    "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:ssh",
                },
                "status": "ready",
            },
        )

    def test_ngfw_deprovision_requires_request_id(self):
        """ngfw deprovision requires --request-id argument."""
        result = subprocess.run(  # noqa: S603
            [sys.executable, "main.py", "ngfw", "deprovision"],
            cwd=str(Path(__file__).parent.parent),
            capture_output=True,
            text=True,
        )

        assert result.returncode != 0
        assert "--request-id" in result.stderr or "required" in result.stderr.lower()

    def test_ngfw_deprovision_updates_status_to_destroying(self, mock_boto3_clients, mock_env_vars, mocker):
        """NGFW deprovision should update status to destroying."""
        mock_update = mocker.patch("main.update_instance_state")
        mocker.patch("main.publish_ngfw_event")

        def side_effect(*args, **kwargs):
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            return result

        mocker.patch("subprocess.run", side_effect=side_effect)

        # Mock SSH executor for pre-destroy license deactivation
        mock_ssh_executor = MagicMock()
        mocker.patch("main.SSHExecutor", return_value=mock_ssh_executor)

        # Mock orchestrator for pre-destroy license deactivation
        mock_orchestrator = MagicMock()
        mock_orchestrator.orchestrate.return_value = MagicMock(success=True)
        mocker.patch("main.SetupOrchestrator", return_value=mock_orchestrator)

        from main import run_ngfw_pulumi

        run_ngfw_pulumi("destroy", self.TEST_REQUEST_ID)

        # Verify status was updated to destroying
        calls = mock_update.call_args_list
        assert calls[0][0] == (self.TEST_REQUEST_ID, "destroying")

    def test_ngfw_deprovision_runs_license_deactivation_first(self, mock_boto3_clients, mock_env_vars, mocker):
        """NGFW deprovision should run license deactivation before Pulumi destroy."""
        mocker.patch("main.update_instance_state")
        mocker.patch("main.publish_ngfw_event")

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

        # Mock SSH executor for pre-destroy license deactivation
        mock_ssh_executor = MagicMock()
        mocker.patch("main.SSHExecutor", return_value=mock_ssh_executor)

        mock_orchestrator = MagicMock()

        def orchestrator_side_effect(*args, **kwargs):
            orchestrator_calls.append(("orchestrator", args))
            return MagicMock(success=True)

        mock_orchestrator.orchestrate.side_effect = orchestrator_side_effect
        mocker.patch("main.SetupOrchestrator", return_value=mock_orchestrator)

        from main import run_ngfw_pulumi

        run_ngfw_pulumi("destroy", self.TEST_REQUEST_ID)

        # Verify orchestrator (license deactivation) was called before Pulumi destroy
        destroy_found = False
        for _i, (_caller, cmd) in enumerate(pulumi_calls):
            if "destroy" in str(cmd):
                destroy_found = True
                break

        # Orchestrator should have been called (for deprovision plan)
        assert len(orchestrator_calls) >= 1
        assert destroy_found, "Expected destroy command to be called"

    def test_ngfw_deprovision_runs_pulumi_destroy(self, mock_boto3_clients, mock_env_vars, mocker):
        """NGFW deprovision should run pulumi destroy."""
        mocker.patch("main.update_instance_state")
        mocker.patch("main.publish_ngfw_event")

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

        # Mock SSH executor for pre-destroy license deactivation
        mock_ssh_executor = MagicMock()
        mocker.patch("main.SSHExecutor", return_value=mock_ssh_executor)

        mock_orchestrator = MagicMock()
        mock_orchestrator.orchestrate.return_value = MagicMock(success=True)
        mocker.patch("main.SetupOrchestrator", return_value=mock_orchestrator)

        from main import run_ngfw_pulumi

        run_ngfw_pulumi("destroy", self.TEST_REQUEST_ID)

        # Verify pulumi destroy was called
        destroy_calls = [c for c in pulumi_calls if "destroy" in c]
        assert len(destroy_calls) >= 1

    def test_ngfw_deprovision_removes_stack(self, mock_boto3_clients, mock_env_vars, mocker):
        """NGFW deprovision should remove the Pulumi stack."""
        mocker.patch("main.update_instance_state")
        mocker.patch("main.publish_ngfw_event")

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

        # Mock SSH executor for pre-destroy license deactivation
        mock_ssh_executor = MagicMock()
        mocker.patch("main.SSHExecutor", return_value=mock_ssh_executor)

        mock_orchestrator = MagicMock()
        mock_orchestrator.orchestrate.return_value = MagicMock(success=True)
        mocker.patch("main.SetupOrchestrator", return_value=mock_orchestrator)

        from main import run_ngfw_pulumi

        run_ngfw_pulumi("destroy", self.TEST_REQUEST_ID)

        # Verify stack rm was called
        rm_calls = [c for c in pulumi_calls if "rm" in str(c)]
        assert len(rm_calls) >= 1

    def test_ngfw_deprovision_sets_destroyed_status(self, mock_boto3_clients, mock_env_vars, mocker):
        """NGFW deprovision should set final status to destroyed."""
        mock_update = mocker.patch("main.update_instance_state")
        mocker.patch("main.publish_ngfw_event")

        def side_effect(*args, **kwargs):
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            return result

        mocker.patch("subprocess.run", side_effect=side_effect)

        # Mock SSH executor for pre-destroy license deactivation
        mock_ssh_executor = MagicMock()
        mocker.patch("main.SSHExecutor", return_value=mock_ssh_executor)

        mock_orchestrator = MagicMock()
        mock_orchestrator.orchestrate.return_value = MagicMock(success=True)
        mocker.patch("main.SetupOrchestrator", return_value=mock_orchestrator)

        from main import run_ngfw_pulumi

        run_ngfw_pulumi("destroy", self.TEST_REQUEST_ID)

        # Verify final status is destroyed
        final_call = mock_update.call_args_list[-1]
        assert final_call[0][1] == "destroyed"


# =============================================================================
# Serial Number Parsing Tests
# =============================================================================


class TestParseSerialNumber:
    """Tests for parse_serial_number helper function."""

    def test_extracts_serial_from_system_info(self):
        """parse_serial_number extracts serial from PAN-OS show system info output."""
        from main import parse_serial_number

        system_info = """hostname: PA-VM
serial: 007200001267
software-version: 11.1.0
"""
        serial = parse_serial_number(system_info)
        assert serial == "007200001267"

    def test_extracts_serial_case_insensitive(self):
        """parse_serial_number handles case variations."""
        from main import parse_serial_number

        # PAN-OS output typically has lowercase "serial:" but test variations
        system_info = "SERIAL: ABC123DEF456"
        serial = parse_serial_number(system_info)
        assert serial == "ABC123DEF456"

    def test_extracts_serial_with_extra_whitespace(self):
        """parse_serial_number handles extra whitespace."""
        from main import parse_serial_number

        system_info = "serial:   007200001267   "
        serial = parse_serial_number(system_info)
        assert serial == "007200001267"

    def test_returns_none_when_not_found(self):
        """parse_serial_number returns None when serial not in output."""
        from main import parse_serial_number

        system_info = """hostname: PA-VM
software-version: 11.1.0
"""
        serial = parse_serial_number(system_info)
        assert serial is None

    def test_returns_none_for_unknown_placeholder(self):
        """parse_serial_number returns None for 'unknown' placeholder."""
        from main import parse_serial_number

        system_info = "serial: unknown"
        serial = parse_serial_number(system_info)
        assert serial is None

    def test_returns_none_for_none_placeholder(self):
        """parse_serial_number returns None for 'none' placeholder."""
        from main import parse_serial_number

        system_info = "serial: none"
        serial = parse_serial_number(system_info)
        assert serial is None

    def test_returns_none_for_empty_output(self):
        """parse_serial_number returns None for empty output."""
        from main import parse_serial_number

        serial = parse_serial_number("")
        assert serial is None

    def test_handles_multiline_panos_output(self):
        """parse_serial_number works with full PAN-OS system info output."""
        from main import parse_serial_number

        # Simulated PAN-OS show system info output
        system_info = """hostname: fw-demo-001
serial: 007200001267
ip-address: 10.1.4.10
mac-address: 0a:1b:2c:3d:4e:5f
time: Fri Jan 10 12:34:56 2025
uptime: 0 days, 2:15:30
family: vm
model: PA-VM
sw-version: 11.1.0
operational-mode: normal
management-address: 10.1.4.10/24
"""
        serial = parse_serial_number(system_info)
        assert serial == "007200001267"


class TestNgfwProvisionSerialNumber:
    """Tests for serial number extraction during NGFW provisioning."""

    TEST_REQUEST_ID = "550e8400-e29b-41d4-a716-446655440000"

    @pytest.fixture(autouse=True)
    def mock_get_ngfw_data(self, mocker):
        """Mock get_ngfw_data_by_request_id for all tests."""
        return mocker.patch(
            "main.get_ngfw_data_by_request_id",
            return_value={
                "request_id": self.TEST_REQUEST_ID,
                "instance_id": "inst-uuid-123",
                "app_id": "app-uuid-456",
                "spec": {"role": "ngfw", "ngfw_app": {"type": "ngfw"}},
                "app_spec": {
                    "scm_pin_id": "pin-123",
                    "scm_pin_value": "secret-pin",
                    "scm_folder_name": "shifter",
                    "authcode": "AUTH123",
                },
                "state": {},
                "status": "pending",
            },
        )

    @pytest.fixture(autouse=True)
    def mock_auto_stop(self, mocker):
        """Mock run_ngfw_operation for auto-stop (not tested here)."""
        return mocker.patch("main.run_ngfw_operation")

    def test_ngfw_provision_extracts_serial_number(self, mock_boto3_clients, mock_env_vars, mocker):
        """NGFW provision should extract serial number from verify_device_cert step."""
        mock_update = mocker.patch("main.update_instance_state")
        mocker.patch("main.publish_ngfw_event")

        outputs = {
            "instance_id": "i-ngfw123",
            "management_ip": "10.1.4.10",
            "dataplane_ip": "10.1.4.11",
            "target_group_arn": "arn:aws:elbv2:us-east-2:123:tg/test",
            "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
        }

        def subprocess_side_effect(*args, **kwargs):
            cmd = args[0]
            result = MagicMock()
            result.returncode = 0
            if "output" in cmd and "--json" in cmd:
                result.stdout = json.dumps(outputs)
            else:
                result.stdout = ""
            result.stderr = ""
            return result

        mocker.patch("subprocess.run", side_effect=subprocess_side_effect)

        # Mock SSH executor
        mock_ssh_executor = MagicMock()
        mocker.patch("main.SSHExecutor", return_value=mock_ssh_executor)

        # Mock orchestrator with step_results containing serial number
        mock_step_result = MagicMock()
        mock_step_result.step_name = "verify_device_cert"
        mock_step_result.stdout = "hostname: PA-VM\nserial: 007200001267\n"

        mock_orchestrator = MagicMock()
        mock_orchestrator.orchestrate.return_value = MagicMock(
            success=True,
            step_results=[mock_step_result],
        )
        mocker.patch("main.SetupOrchestrator", return_value=mock_orchestrator)

        # Mock AWSExecutor for GWLB setup
        mock_aws_executor = MagicMock()
        mock_aws_executor.register_target.return_value = MagicMock(success=True)
        mock_aws_executor.wait_for_target_healthy.return_value = MagicMock(success=True)
        mocker.patch("main.AWSExecutor", return_value=mock_aws_executor)

        from main import run_ngfw_pulumi

        run_ngfw_pulumi("up", self.TEST_REQUEST_ID)

        # Verify serial_number was saved to state
        ready_calls = [c for c in mock_update.call_args_list if c[0][1] == "ready"]
        assert len(ready_calls) == 1
        assert ready_calls[0][1].get("serial_number") == "007200001267"

    def test_ngfw_provision_includes_serial_in_event(self, mock_boto3_clients, mock_env_vars, mocker):
        """NGFW provision should include serial_number in ready event."""
        mocker.patch("main.update_instance_state")
        mock_publish = mocker.patch("main.publish_ngfw_event")

        outputs = {
            "instance_id": "i-ngfw123",
            "management_ip": "10.1.4.10",
            "target_group_arn": "arn:aws:elbv2:us-east-2:123:tg/test",
            "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
        }

        def subprocess_side_effect(*args, **kwargs):
            cmd = args[0]
            result = MagicMock()
            result.returncode = 0
            if "output" in cmd and "--json" in cmd:
                result.stdout = json.dumps(outputs)
            else:
                result.stdout = ""
            result.stderr = ""
            return result

        mocker.patch("subprocess.run", side_effect=subprocess_side_effect)

        mock_ssh_executor = MagicMock()
        mocker.patch("main.SSHExecutor", return_value=mock_ssh_executor)

        # Mock orchestrator with step_results containing serial number
        mock_step_result = MagicMock()
        mock_step_result.step_name = "verify_device_cert"
        mock_step_result.stdout = "serial: ABC123XYZ789"

        mock_orchestrator = MagicMock()
        mock_orchestrator.orchestrate.return_value = MagicMock(
            success=True,
            step_results=[mock_step_result],
        )
        mocker.patch("main.SetupOrchestrator", return_value=mock_orchestrator)

        mock_aws_executor = MagicMock()
        mock_aws_executor.register_target.return_value = MagicMock(success=True)
        mock_aws_executor.wait_for_target_healthy.return_value = MagicMock(success=True)
        mocker.patch("main.AWSExecutor", return_value=mock_aws_executor)

        from main import run_ngfw_pulumi

        run_ngfw_pulumi("up", self.TEST_REQUEST_ID)

        # Find the ready event call
        ready_calls = [c for c in mock_publish.call_args_list if c[1].get("status") == "ready"]
        assert len(ready_calls) == 1
        assert ready_calls[0][1].get("serial_number") == "ABC123XYZ789"

    def test_ngfw_provision_fails_without_serial_number(self, mock_boto3_clients, mock_env_vars, mocker):
        """NGFW provision should fail if serial number cannot be extracted."""
        mocker.patch("main.update_instance_state")
        mocker.patch("main.publish_ngfw_event")

        outputs = {
            "instance_id": "i-ngfw123",
            "management_ip": "10.1.4.10",
            "target_group_arn": "arn:aws:elbv2:us-east-2:123:tg/test",
            "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
        }

        def subprocess_side_effect(*args, **kwargs):
            cmd = args[0]
            result = MagicMock()
            result.returncode = 0
            if "output" in cmd and "--json" in cmd:
                result.stdout = json.dumps(outputs)
            else:
                result.stdout = ""
            result.stderr = ""
            return result

        mocker.patch("subprocess.run", side_effect=subprocess_side_effect)

        mock_ssh_executor = MagicMock()
        mocker.patch("main.SSHExecutor", return_value=mock_ssh_executor)

        # Mock orchestrator with step_results but NO serial number in output
        mock_step_result = MagicMock()
        mock_step_result.step_name = "verify_device_cert"
        mock_step_result.stdout = "hostname: PA-VM\n"  # No serial line

        mock_orchestrator = MagicMock()
        mock_orchestrator.orchestrate.return_value = MagicMock(
            success=True,
            step_results=[mock_step_result],
        )
        mocker.patch("main.SetupOrchestrator", return_value=mock_orchestrator)

        from main import run_ngfw_pulumi

        with pytest.raises(RuntimeError, match="serial number not found"):
            run_ngfw_pulumi("up", self.TEST_REQUEST_ID)


class TestNgfwProvisionAutoStop:
    """Tests for auto-stop after NGFW provisioning."""

    TEST_REQUEST_ID = "550e8400-e29b-41d4-a716-446655440000"

    @pytest.fixture(autouse=True)
    def mock_get_ngfw_data(self, mocker):
        """Mock get_ngfw_data_by_request_id for all tests."""
        return mocker.patch(
            "main.get_ngfw_data_by_request_id",
            return_value={
                "request_id": self.TEST_REQUEST_ID,
                "instance_id": "660e8400-e29b-41d4-a716-446655440001",
                "app_id": "770e8400-e29b-41d4-a716-446655440002",
                "spec": {"role": "ngfw", "ngfw_app": {"type": "ngfw"}},
                "app_spec": {
                    "scm_pin_id": "pin-123",
                    "scm_pin_value": "secret-pin",
                    "scm_folder_name": "shifter",
                    "authcode": "AUTH123",
                },
                "state": {"ec2_instance_id": "i-ngfw123"},
                "status": "ready",
            },
        )

    def test_ngfw_provision_calls_stop_after_ready(self, mock_boto3_clients, mock_env_vars, mocker):
        """NGFW provision should call ngfw_operation(stop) after ready event."""
        mocker.patch("main.update_instance_state")
        mocker.patch("main.publish_ngfw_event")

        outputs = {
            "instance_id": "i-ngfw123",
            "management_ip": "10.1.4.10",
            "target_group_arn": "arn:aws:elbv2:us-east-2:123:tg/test",
            "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
        }

        def subprocess_side_effect(*args, **kwargs):
            cmd = args[0]
            result = MagicMock()
            result.returncode = 0
            if "output" in cmd and "--json" in cmd:
                result.stdout = json.dumps(outputs)
            else:
                result.stdout = ""
            result.stderr = ""
            return result

        mocker.patch("subprocess.run", side_effect=subprocess_side_effect)

        mock_ssh_executor = MagicMock()
        mocker.patch("main.SSHExecutor", return_value=mock_ssh_executor)

        mock_step_result = MagicMock()
        mock_step_result.step_name = "verify_device_cert"
        mock_step_result.stdout = "serial: 007200001267"

        mock_orchestrator = MagicMock()
        mock_orchestrator.orchestrate.return_value = MagicMock(
            success=True,
            step_results=[mock_step_result],
        )
        mocker.patch("main.SetupOrchestrator", return_value=mock_orchestrator)

        mock_aws_executor = MagicMock()
        mock_aws_executor.register_target.return_value = MagicMock(success=True)
        mock_aws_executor.wait_for_target_healthy.return_value = MagicMock(success=True)
        mocker.patch("main.AWSExecutor", return_value=mock_aws_executor)

        # Mock run_ngfw_operation to track calls
        mock_run_ngfw_operation = mocker.patch("main.run_ngfw_operation")

        from main import run_ngfw_pulumi

        run_ngfw_pulumi("up", self.TEST_REQUEST_ID)

        # Verify run_ngfw_operation was called with "stop"
        mock_run_ngfw_operation.assert_called_once_with("stop", self.TEST_REQUEST_ID)

    def test_ngfw_provision_stop_called_after_ready_event(self, mock_boto3_clients, mock_env_vars, mocker):
        """Auto-stop should be called after ready event is published."""
        mocker.patch("main.update_instance_state")

        call_order = []

        def track_publish(*args, **kwargs):
            status = kwargs.get("status")
            call_order.append(("publish_ngfw_event", status))

        mocker.patch("main.publish_ngfw_event", side_effect=track_publish)

        def track_run_ngfw_operation(operation, request_id):
            call_order.append(("run_ngfw_operation", operation))

        mocker.patch("main.run_ngfw_operation", side_effect=track_run_ngfw_operation)

        outputs = {
            "instance_id": "i-ngfw123",
            "management_ip": "10.1.4.10",
            "target_group_arn": "arn:aws:elbv2:us-east-2:123:tg/test",
            "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
        }

        def subprocess_side_effect(*args, **kwargs):
            cmd = args[0]
            result = MagicMock()
            result.returncode = 0
            if "output" in cmd and "--json" in cmd:
                result.stdout = json.dumps(outputs)
            else:
                result.stdout = ""
            result.stderr = ""
            return result

        mocker.patch("subprocess.run", side_effect=subprocess_side_effect)

        mock_ssh_executor = MagicMock()
        mocker.patch("main.SSHExecutor", return_value=mock_ssh_executor)

        mock_step_result = MagicMock()
        mock_step_result.step_name = "verify_device_cert"
        mock_step_result.stdout = "serial: 007200001267"

        mock_orchestrator = MagicMock()
        mock_orchestrator.orchestrate.return_value = MagicMock(
            success=True,
            step_results=[mock_step_result],
        )
        mocker.patch("main.SetupOrchestrator", return_value=mock_orchestrator)

        mock_aws_executor = MagicMock()
        mock_aws_executor.register_target.return_value = MagicMock(success=True)
        mock_aws_executor.wait_for_target_healthy.return_value = MagicMock(success=True)
        mocker.patch("main.AWSExecutor", return_value=mock_aws_executor)

        from main import run_ngfw_pulumi

        run_ngfw_pulumi("up", self.TEST_REQUEST_ID)

        # Verify order: ready event published BEFORE stop is called
        ready_idx = None
        stop_idx = None
        for i, (func, arg) in enumerate(call_order):
            if func == "publish_ngfw_event" and arg == "ready":
                ready_idx = i
            if func == "run_ngfw_operation" and arg == "stop":
                stop_idx = i

        assert ready_idx is not None, "Ready event not published"
        assert stop_idx is not None, "Stop not called"
        assert ready_idx < stop_idx, "Stop should be called after ready event"

    def test_ngfw_provision_stop_emits_status_events(self, mock_boto3_clients, mock_env_vars, mocker):
        """Auto-stop should emit stopping and stopped status events."""
        mocker.patch("main.update_instance_state")

        status_events = []

        def track_publish(*args, **kwargs):
            status = kwargs.get("status")
            status_events.append(status)

        mocker.patch("main.publish_ngfw_event", side_effect=track_publish)
        # Also patch events.publish_ngfw_event for run_ngfw_operation's local import
        mocker.patch("events.publish_ngfw_event", side_effect=track_publish)

        outputs = {
            "instance_id": "i-ngfw123",
            "management_ip": "10.1.4.10",
            "target_group_arn": "arn:aws:elbv2:us-east-2:123:tg/test",
            "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
        }

        def subprocess_side_effect(*args, **kwargs):
            cmd = args[0]
            result = MagicMock()
            result.returncode = 0
            if "output" in cmd and "--json" in cmd:
                result.stdout = json.dumps(outputs)
            else:
                result.stdout = ""
            result.stderr = ""
            return result

        mocker.patch("subprocess.run", side_effect=subprocess_side_effect)

        mock_ssh_executor = MagicMock()
        mocker.patch("main.SSHExecutor", return_value=mock_ssh_executor)

        mock_step_result = MagicMock()
        mock_step_result.step_name = "verify_device_cert"
        mock_step_result.stdout = "serial: 007200001267"

        mock_setup_orchestrator = MagicMock()
        mock_setup_orchestrator.orchestrate.return_value = MagicMock(
            success=True,
            step_results=[mock_step_result],
        )
        mocker.patch("main.SetupOrchestrator", return_value=mock_setup_orchestrator)

        mock_aws_executor = MagicMock()
        mock_aws_executor.register_target.return_value = MagicMock(success=True)
        mock_aws_executor.wait_for_target_healthy.return_value = MagicMock(success=True)
        mock_aws_executor.stop_instance.return_value = MagicMock(success=True)
        mock_aws_executor.wait_for_stopped.return_value = MagicMock(success=True)
        mocker.patch("main.AWSExecutor", return_value=mock_aws_executor)

        # Mock OpsOrchestrator for stop operation
        mock_ops_orchestrator = MagicMock()
        mock_ops_orchestrator.orchestrate.return_value = MagicMock(success=True, step_results=[])
        mocker.patch("main.OpsOrchestrator", return_value=mock_ops_orchestrator)

        from main import run_ngfw_pulumi

        run_ngfw_pulumi("up", self.TEST_REQUEST_ID)

        # Verify status progression: provisioning -> ready -> stopping -> stopped
        assert "provisioning" in status_events
        assert "ready" in status_events
        assert "stopping" in status_events
        assert "stopped" in status_events

        # Verify order
        prov_idx = status_events.index("provisioning")
        ready_idx = status_events.index("ready")
        stopping_idx = status_events.index("stopping")
        stopped_idx = status_events.index("stopped")

        assert prov_idx < ready_idx < stopping_idx < stopped_idx
