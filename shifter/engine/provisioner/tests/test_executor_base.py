"""Tests for executor base module."""

from executors.base import CommandResult, Executor
from executors.guest_ssh_executor import GuestSSHExecutor
from executors.ssh_executor import SSHExecutor
from executors.ssm_executor import SSMExecutor


class TestExecutorImports:
    """Verify executor modules can be imported."""

    def test_base_module_imports(self):
        """Base executor module imports successfully."""
        assert CommandResult is not None
        assert Executor is not None

    def test_executor_implementations_import(self):
        """Executor implementations import successfully."""
        assert SSMExecutor is not None
        assert SSHExecutor is not None
        assert GuestSSHExecutor is not None
