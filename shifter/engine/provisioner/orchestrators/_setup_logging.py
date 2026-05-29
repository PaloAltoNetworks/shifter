"""Logging / sensitivity / template-render helpers for SetupOrchestrator.

Provides `_SetupOrchestratorLoggingMixin`, mixed into `SetupOrchestrator`,
carrying step-success/step-failure logging, sensitive-value masking, and
the `{{ var }}` template renderer. Split out of `setup_orchestrator.py` to
keep that module under Sonar's file-length ceiling.
"""

import logging
import os
import re
from typing import Any

from executors.base import CommandResult
from orchestrators._setup_types import SetupError
from plans.base import SetupStep

# Log under the public module name (`orchestrators.setup_orchestrator`) even
# though this code lives in a split-out helper module. Tests pin caplog /
# callers pin log handlers to that logger name; keeping a single logger name
# across the package preserves that contract and keeps log output on one
# stable channel.
logger = logging.getLogger("orchestrators.setup_orchestrator")


class _SetupOrchestratorLoggingMixin:
    """Step-logging, sensitive-output masking, and template rendering.

    Mixed into `SetupOrchestrator`. Holds no orchestration state of its own;
    every method is a `@classmethod` / `@staticmethod` or expects `self` only
    so it can read instance state set up by the main class.
    """

    SENSITIVE_ENV_VARS = (
        "DC_DOMAIN_PASSWORD",
        # Defense in depth (#762): if a per-instance RDP password is ever
        # forwarded into setup orchestration as an env var (e.g., a future
        # plan that needs to chpasswd through SSM), keep the value out of
        # captured stdout/stderr.
        "RDP_PASSWORD",
        "GUEST_PASSWORD",
    )
    SENSITIVE_CONTEXT_KEY_PARTS = ("password", "secret", "token")

    def _log_step_success(
        self,
        step: SetupStep,
        result: CommandResult,
        context: dict[str, Any],
    ) -> None:
        logger.info(
            "_execute_step: completed step=%s exit_code=%d",
            step.name,
            result.exit_code,
        )
        if result.stdout:
            logger.info(
                "_execute_step: step=%s STDOUT:\n%s",
                step.name,
                self._mask_sensitive_output(result.stdout, context),
            )
        if result.stderr:
            logger.info(
                "_execute_step: step=%s STDERR:\n%s",
                step.name,
                self._mask_sensitive_output(result.stderr, context),
            )

    def _log_step_failure(
        self,
        step: SetupStep,
        result: CommandResult,
        attempt: int,
        max_retries: int,
        context: dict[str, Any],
    ) -> None:
        logger.warning(
            "_execute_step: FAILED step=%s attempt=%d/%d exit_code=%d",
            step.name,
            attempt + 1,
            max_retries + 1,
            result.exit_code,
        )
        if result.stdout:
            logger.warning(
                "_execute_step: step=%s FAILED STDOUT:\n%s",
                step.name,
                self._mask_sensitive_output(result.stdout, context),
            )
        if result.stderr:
            logger.warning(
                "_execute_step: step=%s FAILED STDERR:\n%s",
                step.name,
                self._mask_sensitive_output(result.stderr, context),
            )

    @classmethod
    def _mask_sensitive_output(cls, output: str, context: dict[str, Any] | None = None) -> str:
        """Mask known secret values before writing command output to logs."""
        if not output:
            return output

        masked_output = output
        for sensitive_value in cls._sensitive_values(context):
            masked_output = masked_output.replace(sensitive_value, "[REDACTED]")
        return masked_output

    @classmethod
    def _sensitive_values(cls, context: dict[str, Any] | None = None) -> list[str]:
        values = {value for env_var in cls.SENSITIVE_ENV_VARS if (value := os.environ.get(env_var))}

        if context:
            for key, value in context.items():
                if value is not None and cls._is_sensitive_context_key(key):
                    values.add(str(value))

        return sorted((value for value in values if value), key=len, reverse=True)

    @classmethod
    def _is_sensitive_context_key(cls, key: str) -> bool:
        normalized_key = key.lower()
        return any(part in normalized_key for part in cls.SENSITIVE_CONTEXT_KEY_PARTS)

    @staticmethod
    def _render_script(
        script: str,
        context: dict[str, Any],
        step_name: str,
    ) -> str:
        """Render a script template with context variables.

        Uses simple {{ variable }} syntax compatible with Jinja2.
        PowerShell $variables are preserved.

        Args:
            script: Script template
            context: Variables to substitute
            step_name: Step name for error messages

        Returns:
            Rendered script

        Raises:
            SetupError: If a required variable is missing
        """
        result = script

        # Find all {{ variable }} patterns
        pattern = r"\{\{\s*(\w+)\s*\}\}"
        matches = re.findall(pattern, script)

        for var_name in matches:
            if var_name not in context:
                logger.error(
                    "_render_script: missing variable=%s step=%s context_keys=%d",
                    var_name,
                    step_name,
                    len(context),
                )
                raise SetupError(
                    f"Missing template variable '{var_name}' in step '{step_name}'. "
                    "Required variables are missing from the supplied context.",
                    step_name=step_name,
                )
            # Replace {{ var }} with the value
            result = re.sub(
                r"\{\{\s*" + var_name + r"\s*\}\}",
                str(context[var_name]),
                result,
            )

        return result
