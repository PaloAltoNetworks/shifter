"""Tests for the executor base ports (CommandExecutor / ActionExecutor)."""

from typing import Any

from executors.aws_executor import AWSExecutor
from executors.base import ActionExecutor, CommandExecutor, CommandResult
from executors.guest_ssh_executor import GuestSSHExecutor
from executors.ssh_executor import SSHExecutor
from executors.ssm_executor import SSMExecutor


class TestExecutorImports:
    """Verify executor modules can be imported."""

    def test_base_module_imports(self):
        """Base executor module exposes both ports and the result type."""
        assert CommandResult is not None
        assert CommandExecutor is not None
        assert ActionExecutor is not None

    def test_executor_implementations_import(self):
        """Executor implementations import successfully."""
        assert SSMExecutor is not None
        assert SSHExecutor is not None
        assert GuestSSHExecutor is not None


class TestCommandExecutorPort:
    """The command-execution port describes the guest-command transports."""

    def test_script_executor_satisfies_command_port(self):
        """A guest command transport conforms to CommandExecutor at runtime."""
        assert isinstance(
            SSMExecutor(ssm_client=object(), ec2_client=object()),
            CommandExecutor,
        )

    def test_action_executor_is_not_a_command_executor(self):
        """AWSExecutor has run_command but lacks the readiness/reboot surface."""
        assert not isinstance(AWSExecutor(region_name="us-east-2"), CommandExecutor)

    def test_action_only_object_is_not_a_command_executor(self):
        """An object exposing only execute_action is not a CommandExecutor."""

        class ActionOnly:
            def execute_action(self, action: str, context: dict[str, Any]) -> CommandResult:
                return CommandResult(success=True, exit_code=0, stdout="", stderr="")

        assert not isinstance(ActionOnly(), CommandExecutor)


class TestActionExecutorPort:
    """The action-dispatch port describes provider-action executors."""

    def test_aws_executor_is_an_action_executor(self):
        """AWSExecutor conforms to the ActionExecutor port."""
        assert isinstance(AWSExecutor(region_name="us-east-2"), ActionExecutor)

    def test_command_executor_is_not_an_action_executor(self):
        """A guest command transport is not an ActionExecutor."""
        assert not isinstance(
            SSMExecutor(ssm_client=object(), ec2_client=object()),
            ActionExecutor,
        )

    def test_command_only_object_is_not_an_action_executor(self):
        """An object exposing only run_command is not an ActionExecutor."""

        class CommandOnly:
            def run_command(self, instance_id: str, script: str, **kwargs: Any) -> CommandResult:
                return CommandResult(success=True, exit_code=0, stdout="", stderr="")

        assert not isinstance(CommandOnly(), ActionExecutor)
