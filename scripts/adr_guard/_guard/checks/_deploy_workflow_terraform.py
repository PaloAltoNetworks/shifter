"""ADR-003-R2 Terraform lock-timeout and saved-plan apply integrity.

Every Terraform-running reusable workflow must wait for the state lock rather
than failing, and its `apply` job must apply a saved plan it created itself
instead of running a fresh `terraform apply -auto-approve`.
"""
from __future__ import annotations

import shlex

from .._common import Violation
from ._deploy_workflow_plan_scope import _plan_scope_violation
from ._deploy_workflow_text import _workflow_job_block


_TERRAFORM_PLAN_FILE = "tfplan"
_RUN_STEP_PREFIX = "- run:"
_LOCK_TIMEOUT_FLAG = "-lock-timeout=5m"
# Shell operators that end the argument list of a `terraform plan` invocation.
_SHELL_SEPARATORS = frozenset({"&&", "||", ";", "|"})
# Comments and echoed help text mention Terraform commands without running them.
_NON_COMMAND_LINE_PREFIXES = ("#", "echo ")


def _command_tokens(stripped_line: str) -> list[str]:
    """Shell tokens of a workflow line, unwrapping a `- run:` step prefix."""
    if stripped_line.startswith(_RUN_STEP_PREFIX):
        command = stripped_line.split(":", 1)[1].strip()
    else:
        command = stripped_line
    try:
        return shlex.split(command, comments=True)
    except ValueError:
        return command.split()


def _terraform_plan_arguments(stripped_line: str) -> list[str] | None:
    """Arguments of the line's first `terraform plan`, or None when it has none."""
    tokens = _command_tokens(stripped_line)
    for index, token in enumerate(tokens[:-1]):
        if token != "terraform" or tokens[index + 1] != "plan":
            continue
        plan_tokens: list[str] = []
        for plan_token in tokens[index + 2 :]:
            if plan_token in _SHELL_SEPARATORS:
                break
            plan_tokens.append(plan_token)
        return plan_tokens
    return None


def _terraform_plan_has_lock_timeout(stripped_line: str) -> bool:
    """True when the line's `terraform plan` passes `-lock-timeout=5m`."""
    plan_tokens = _terraform_plan_arguments(stripped_line)
    return plan_tokens is not None and _LOCK_TIMEOUT_FLAG in plan_tokens


def _terraform_plan_writes_saved_plan(stripped_line: str) -> bool:
    """True when the line's `terraform plan` writes the plan to `tfplan`."""
    plan_tokens = _terraform_plan_arguments(stripped_line)
    if plan_tokens is None:
        return False
    if f"-out={_TERRAFORM_PLAN_FILE}" in plan_tokens:
        return True
    return any(
        plan_token == "-out"
        and next_index + 1 < len(plan_tokens)
        and plan_tokens[next_index + 1] == _TERRAFORM_PLAN_FILE
        for next_index, plan_token in enumerate(plan_tokens)
    )


def _terraform_apply_uses_saved_plan(stripped_line: str) -> bool:
    """True when the line applies the saved `tfplan` under a lock timeout."""
    tokens = _command_tokens(stripped_line)
    for index, token in enumerate(tokens[:-1]):
        if token != "terraform" or tokens[index + 1] != "apply":
            continue
        apply_tokens = tokens[index + 2 :]
        return (
            _LOCK_TIMEOUT_FLAG in apply_tokens
            and _TERRAFORM_PLAN_FILE in apply_tokens
            and "-auto-approve" not in apply_tokens
        )
    return False


def _line_removes_tfplan(stripped_line: str) -> bool:
    """True when the line deletes the saved Terraform plan file."""
    if _TERRAFORM_PLAN_FILE not in stripped_line:
        return False
    tokens = _command_tokens(stripped_line)
    return "rm" in tokens and _TERRAFORM_PLAN_FILE in tokens


def _check_terraform_plan_lock_timeout(workflow_text: str, path: str) -> list[Violation]:
    """Require every `terraform plan` command to pass `-lock-timeout=5m`."""
    violations: list[Violation] = []
    for lineno, line in enumerate(workflow_text.splitlines(), start=1):
        stripped = line.strip()
        if "terraform plan" not in stripped:
            continue
        if stripped.startswith(_NON_COMMAND_LINE_PREFIXES):
            continue
        if _terraform_plan_has_lock_timeout(stripped):
            continue
        violations.append(
            _plan_scope_violation(
                f"{path}:{lineno}",
                "AWS Terraform plan commands must include `-lock-timeout=5m` "
                "so legitimate concurrent plans wait for the state lock instead of failing",
            )
        )
    return violations


def _saved_plan_apply_indices(apply_block: list[str]) -> tuple[int | None, int | None]:
    """Indices of the first `terraform plan` / `terraform apply` lines in a job block."""
    plan_idx: int | None = None
    command_idx: int | None = None
    for index, line in enumerate(apply_block):
        stripped = line.strip()
        if stripped.startswith(_NON_COMMAND_LINE_PREFIXES):
            continue
        if plan_idx is None and "terraform plan" in stripped:
            plan_idx = index
        if command_idx is None and "terraform apply" in stripped:
            command_idx = index
    return plan_idx, command_idx


def _saved_plan_creation_violations(
    path: str, apply_block: list[str], plan_idx: int | None
) -> list[Violation]:
    """Violations about how the `apply` job creates its saved plan."""
    if plan_idx is None:
        return [
            _plan_scope_violation(
                path,
                "The Terraform `apply` job must create a local saved Terraform plan "
                "(`terraform plan -lock-timeout=5m -out=tfplan`) immediately before "
                "applying, avoiding raw binary plan artifacts while ensuring apply "
                "executes a reviewed saved plan",
            )
        ]
    if not _terraform_plan_writes_saved_plan(apply_block[plan_idx]):
        return [
            _plan_scope_violation(
                path,
                "The Terraform `apply` job's local plan command must write `-out=tfplan` "
                "so the subsequent apply consumes a saved plan file",
            )
        ]
    return []


def _saved_plan_apply_command_violations(
    path: str, plan_idx: int | None, command_idx: int | None
) -> list[Violation]:
    """Violations about the presence and ordering of the `terraform apply` command."""
    if command_idx is None:
        return [
            _plan_scope_violation(
                path,
                "The Terraform `apply` job must run `terraform apply -lock-timeout=5m "
                "tfplan` after creating the saved plan",
            )
        ]
    if plan_idx is not None and plan_idx > command_idx:
        return [
            _plan_scope_violation(
                path,
                "The Terraform `apply` job must create the saved `tfplan` before "
                "running `terraform apply`",
            )
        ]
    return []


def _removes_tfplan_before_apply(
    stripped: str, index: int, plan_idx: int | None, command_idx: int | None
) -> bool:
    """True when a line between plan creation and apply deletes the saved plan."""
    if plan_idx is None or command_idx is None:
        return False
    return plan_idx < index < command_idx and _line_removes_tfplan(stripped)


def _saved_plan_apply_line_violations(
    path: str, apply_block: list[str], plan_idx: int | None, command_idx: int | None
) -> list[Violation]:
    """Violations raised by individual lines of the `apply` job block."""
    violations: list[Violation] = []
    for index, line in enumerate(apply_block):
        stripped = line.strip()
        if stripped.startswith(_NON_COMMAND_LINE_PREFIXES):
            continue
        if _removes_tfplan_before_apply(stripped, index, plan_idx, command_idx):
            violations.append(
                _plan_scope_violation(
                    path,
                    "The Terraform `apply` job must not remove `tfplan` before applying; "
                    "Service Discovery checks and Terraform apply must consume the same "
                    "saved plan file",
                )
            )
        if "terraform apply" in stripped and not _terraform_apply_uses_saved_plan(stripped):
            violations.append(
                _plan_scope_violation(
                    path,
                    "Terraform apply commands must apply the saved Terraform plan with "
                    "`terraform apply -lock-timeout=5m tfplan`, not run a fresh "
                    "`terraform apply -auto-approve`",
                )
            )
    return violations


def _check_saved_plan_apply_contract(workflow_text: str, path: str) -> list[Violation]:
    """Require the apply job to create and consume a local saved Terraform plan."""
    plan_block = _workflow_job_block(workflow_text, "plan")
    apply_block = _workflow_job_block(workflow_text, "apply")

    if not plan_block:
        return [
            _plan_scope_violation(
                path,
                "Terraform workflow is missing a `plan` job; ADR-003-R2 cannot verify "
                "saved-plan apply integrity",
            )
        ]
    if not apply_block:
        return [
            _plan_scope_violation(
                path,
                "Terraform workflow is missing an `apply` job; ADR-003-R2 cannot verify "
                "saved-plan apply integrity",
            )
        ]

    plan_idx, command_idx = _saved_plan_apply_indices(apply_block)
    violations: list[Violation] = []
    violations.extend(_saved_plan_creation_violations(path, apply_block, plan_idx))
    violations.extend(_saved_plan_apply_command_violations(path, plan_idx, command_idx))
    violations.extend(
        _saved_plan_apply_line_violations(path, apply_block, plan_idx, command_idx)
    )
    return violations


def _check_terraform_workflow_integrity(workflow_text: str, path: str) -> list[Violation]:
    """Lock-timeout and saved-plan apply violations for one Terraform workflow."""
    violations: list[Violation] = []
    violations.extend(_check_terraform_plan_lock_timeout(workflow_text, path))
    violations.extend(_check_saved_plan_apply_contract(workflow_text, path))
    return violations
