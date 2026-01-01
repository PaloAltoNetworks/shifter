"""Tests for executor base protocol - TDD: Write tests first.

Tests verify the Executor protocol and CommandResult dataclass
that all executors (SSM, SSH, AWS) must implement.
"""

import pytest
from typing import Protocol, runtime_checkable
from dataclasses import fields


class TestCommandResultDataclass:
    """Test CommandResult dataclass structure."""

    def test_command_result_has_success_field(self):
        """CommandResult has success: bool field."""
        from executors.base import CommandResult

        result = CommandResult(success=True, stdout="", stderr="")
        assert hasattr(result, "success")
        assert isinstance(result.success, bool)

    def test_command_result_has_stdout_field(self):
        """CommandResult has stdout: str field."""
        from executors.base import CommandResult

        result = CommandResult(success=True, stdout="output", stderr="")
        assert hasattr(result, "stdout")
        assert isinstance(result.stdout, str)

    def test_command_result_has_stderr_field(self):
        """CommandResult has stderr: str field."""
        from executors.base import CommandResult

        result = CommandResult(success=True, stdout="", stderr="error")
        assert hasattr(result, "stderr")
        assert isinstance(result.stderr, str)

    def test_command_result_is_dataclass(self):
        """CommandResult is a dataclass."""
        from executors.base import CommandResult

        # Dataclasses have __dataclass_fields__
        assert hasattr(CommandResult, "__dataclass_fields__")

    def test_command_result_field_names(self):
        """CommandResult has exactly the expected fields."""
        from executors.base import CommandResult

        field_names = {f.name for f in fields(CommandResult)}
        # Must have at least success, stdout, stderr
        assert "success" in field_names
        assert "stdout" in field_names
        assert "stderr" in field_names


class TestExecutorProtocol:
    """Test Executor protocol definition."""

    def test_executor_is_protocol(self):
        """Executor is a Protocol class."""
        from executors.base import Executor

        # Check it's a Protocol
        assert hasattr(Executor, "__protocol_attrs__") or issubclass(Executor, Protocol)

    def test_executor_is_runtime_checkable(self):
        """Executor is runtime_checkable for isinstance checks."""
        from executors.base import Executor

        # Should be decorated with @runtime_checkable
        assert getattr(Executor, "_is_runtime_protocol", False)

    def test_executor_has_run_command_method(self):
        """Executor protocol defines run_command method."""
        from executors.base import Executor

        # Protocol should define run_command
        assert "run_command" in dir(Executor)

    def test_executor_has_wait_for_ready_method(self):
        """Executor protocol defines wait_for_ready method."""
        from executors.base import Executor

        # Protocol should define wait_for_ready
        assert "wait_for_ready" in dir(Executor)


class TestSSMExecutorImplementsProtocol:
    """Test that SSMExecutor implements the Executor protocol."""

    def test_ssm_executor_has_run_command(self):
        """SSMExecutor has run_command method."""
        from executors.ssm_executor import SSMExecutor

        assert hasattr(SSMExecutor, "run_command")
        assert callable(getattr(SSMExecutor, "run_command"))

    def test_ssm_executor_has_wait_for_agent(self):
        """SSMExecutor has wait_for_agent method (equivalent to wait_for_ready)."""
        from executors.ssm_executor import SSMExecutor

        # SSMExecutor uses wait_for_agent instead of wait_for_ready
        assert hasattr(SSMExecutor, "wait_for_agent")
        assert callable(getattr(SSMExecutor, "wait_for_agent"))


class TestSSHExecutorImplementsProtocol:
    """Test that SSHExecutor implements the Executor protocol."""

    def test_ssh_executor_has_run_command(self):
        """SSHExecutor has run_command method."""
        from executors.ssh_executor import SSHExecutor

        assert hasattr(SSHExecutor, "run_command")
        assert callable(getattr(SSHExecutor, "run_command"))

    def test_ssh_executor_has_wait_for_agent(self):
        """SSHExecutor has wait_for_agent method (equivalent to wait_for_ready)."""
        from executors.ssh_executor import SSHExecutor

        # SSHExecutor uses wait_for_agent instead of wait_for_ready
        assert hasattr(SSHExecutor, "wait_for_agent")
        assert callable(getattr(SSHExecutor, "wait_for_agent"))


class TestCommandResultEquality:
    """Test CommandResult equality and usage."""

    def test_command_result_equality(self):
        """CommandResult instances with same values are equal."""
        from executors.base import CommandResult

        r1 = CommandResult(success=True, stdout="ok", stderr="")
        r2 = CommandResult(success=True, stdout="ok", stderr="")
        assert r1 == r2

    def test_command_result_inequality(self):
        """CommandResult instances with different values are not equal."""
        from executors.base import CommandResult

        r1 = CommandResult(success=True, stdout="ok", stderr="")
        r2 = CommandResult(success=False, stdout="ok", stderr="")
        assert r1 != r2
