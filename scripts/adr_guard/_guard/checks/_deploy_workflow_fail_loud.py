"""ADR-003-R3: deploy-verification steps fail the run instead of warning.

A verification step that exits 0 when the thing it verifies did not happen turns
a broken deploy into a green run, so the Guacamole stabilization wait and the
engine ECS task-definition update must both `exit 1` on failure.
"""
from __future__ import annotations

from pathlib import Path

from .._common import (
    Violation,
    is_guard_source_path,
)
from .._workflow_model import _PLATFORM_WORKFLOW_PATH
from ._deploy_workflow_plan_scope import _DEPLOY_WORKFLOW_PATH
from ._deploy_workflow_text import (
    _noncomment_contains,
    _workflow_step_block,
)


_FAIL_LOUD_CHECK = "deploy-verification-fail-loud"
_FAIL_LOUD_RULE = "ADR-003-R3"
_ENGINE_WORKFLOW_PATH = ".github/workflows/_shifter-engine.yml"
_GUAC_STABILIZE_STEP = "Wait for Guacamole ECS services to stabilize"
_ENGINE_TASKDEF_STEP = "Update ECS task definition"
# The engine ECS task-family skip is only acceptable behind this explicit
# bootstrap input (mirrors gcp_require_active_certificate); its presence in the
# step proves the skip is gated rather than unconditional.
_ENGINE_BOOTSTRAP_INPUT = "first_deploy"


def _fail_loud_relevant(files: list[str] | None) -> bool:
    """True when a changed file can affect ADR-003-R3 deploy-verification steps."""
    if files is None:
        return True
    relevant = {
        _PLATFORM_WORKFLOW_PATH,
        _ENGINE_WORKFLOW_PATH,
        _DEPLOY_WORKFLOW_PATH,
    }
    return any(path in relevant or is_guard_source_path(path) for path in files)


def _fail_loud_violation(path: str, message: str) -> Violation:
    """Build an ADR-003-R3 violation for the deploy-verification fail-loud check."""
    return Violation(_FAIL_LOUD_CHECK, _FAIL_LOUD_RULE, path, message)


def _guacamole_timeout_handler_message(tail: list[str]) -> str | None:
    """Describe a timeout handler that does not fail the deploy, or None."""
    if not _noncomment_contains(tail, "exit 1") or _noncomment_contains(tail, "exit 0"):
        return (
            f"`{_GUAC_STABILIZE_STEP}` step must fail the deploy on stabilization "
            "timeout: the handler after the polling loop must `exit 1` (not warn and "
            "exit 0). Raise the timeout if first boot needs longer, but do not "
            "downgrade a timeout to a warning"
        )
    return None


def _guacamole_timeout_message(platform_text: str) -> str | None:
    """Describe why the Guacamole stabilization wait is not fail-loud, or None."""
    block = _workflow_step_block(platform_text, _GUAC_STABILIZE_STEP)
    if not block:
        return (
            f"`{_GUAC_STABILIZE_STEP}` step is missing; ADR-003-R3 cannot verify "
            "the Guacamole stabilization timeout fails the deploy"
        )
    # The stabilization poll is the last `while ... done` loop in the step; its
    # closing `done` separates the loop body from the timeout handler tail.
    done_idx = max(
        (i for i, line in enumerate(block) if line.strip() == "done"),
        default=None,
    )
    if done_idx is None:
        return (
            f"`{_GUAC_STABILIZE_STEP}` step has no polling loop; ADR-003-R3 expects "
            "a stabilization wait whose timeout fails the deploy"
        )
    return _guacamole_timeout_handler_message(block[done_idx + 1 :])


def _check_guacamole_timeout_fails(platform_text: str) -> list[Violation]:
    """Require the Guacamole stabilization wait to fail the deploy on timeout."""
    message = _guacamole_timeout_message(platform_text)
    if message is None:
        return []
    return [_fail_loud_violation(_PLATFORM_WORKFLOW_PATH, message)]


def _check_engine_task_family_fails(engine_text: str) -> list[Violation]:
    """Require a missing engine ECS task family to fail the deploy."""
    block = _workflow_step_block(engine_text, _ENGINE_TASKDEF_STEP)
    if not block:
        return [
            _fail_loud_violation(
                _ENGINE_WORKFLOW_PATH,
                f"`{_ENGINE_TASKDEF_STEP}` step is missing; ADR-003-R3 cannot verify "
                "a missing engine task family fails the deploy",
            )
        ]
    violations: list[Violation] = []
    if not _noncomment_contains(block, "exit 1"):
        violations.append(
            _fail_loud_violation(
                _ENGINE_WORKFLOW_PATH,
                f"`{_ENGINE_TASKDEF_STEP}` step must `exit 1` when the ECS task "
                "definition family cannot be described, so a missing/typo'd family "
                "fails the deploy instead of skipping silently",
            )
        )
    if not _noncomment_contains(block, _ENGINE_BOOTSTRAP_INPUT):
        violations.append(
            _fail_loud_violation(
                _ENGINE_WORKFLOW_PATH,
                f"`{_ENGINE_TASKDEF_STEP}` step must gate any missing-family skip on the "
                f"explicit `{_ENGINE_BOOTSTRAP_INPUT}` bootstrap input; an unconditional "
                "`exit 0` skip lets a typo'd family skip every deploy forever",
            )
        )
    return violations


def check_deploy_verification_fail_loud(
    repo_root: Path, files: list[str] | None
) -> list[Violation]:
    """Require deploy-verification steps to fail loud (ADR-003-R3).

    Two deploy steps must fail the run when the thing they verify did not
    happen, rather than warning and exiting 0:

    - `_shifter-platform.yml`'s Guacamole stabilization wait must `exit 1` on
      timeout (the FAILED circuit-breaker branch already does).
    - `_shifter-engine.yml`'s task-definition update must `exit 1` when the ECS
      task family cannot be described, with the only skip gated behind the
      explicit `first_deploy` bootstrap input.
    """
    if not _fail_loud_relevant(files):
        return []

    violations: list[Violation] = []
    platform_path = repo_root / _PLATFORM_WORKFLOW_PATH
    engine_path = repo_root / _ENGINE_WORKFLOW_PATH

    if not platform_path.exists():
        violations.append(
            _fail_loud_violation(
                _PLATFORM_WORKFLOW_PATH,
                "Required workflow is missing; ADR-003-R3 cannot verify the Guacamole "
                "stabilization timeout fails the deploy",
            )
        )
    else:
        violations.extend(_check_guacamole_timeout_fails(platform_path.read_text(encoding="utf-8")))

    if not engine_path.exists():
        violations.append(
            _fail_loud_violation(
                _ENGINE_WORKFLOW_PATH,
                "Required workflow is missing; ADR-003-R3 cannot verify a missing engine "
                "task family fails the deploy",
            )
        )
    else:
        violations.extend(_check_engine_task_family_fails(engine_path.read_text(encoding="utf-8")))

    return violations
