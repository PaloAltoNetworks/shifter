"""Validated execution context for platform scripts.

This module is the security boundary for issue #700: every value that flows
from user input into the experiment script execution layer (orchestrator →
ECS → SSM) is validated here, in one Pydantic-validated context object,
before any render method produces the final shell text.

Three principles:

1. **Whitelist at the type boundary.** Target-specific Annotated str types
   (`InstanceIdValue`, `S3KeySegment`, `PrivateIpValue`, `DisplayName`,
   `PromptText`) constrain each value to a character set safe at its
   destination. Render methods read off validated fields and never apply
   their own sanitization — there is nothing left to sanitize.
2. **Path identifier is the instance ID, not the display name.** EC2
   instance IDs (`i-[0-9a-f]{8,17}`) are the only per-instance value the
   fixed shell wrapper embeds directly. Display names may contain spaces,
   punctuation, and unicode (e.g. "Workstation 1", "Domain Controller");
   they are metadata only.
3. **Payloads cross the remote shell boundary as encoded data.** Render
   methods emit fixed Python wrappers, base64-encode user-controlled payloads,
   and invoke tools with structured argv inside the wrapper.
"""

from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationError,
    model_validator,
)
from pydantic_core import InitErrorDetails, PydanticCustomError

from shared.template_vars import extract_variables, resolve_template

from ._validators import (
    _UNRESOLVED_PLACEHOLDER,
    AI_EXPERIMENT_EXECUTION_POLICY_VERSION,
    DisplayName,
    InstanceIdValue,
    PrivateIpValue,
    PromptText,
    S3KeySegment,
    _encode_command_payload,
    _validate_template_substitutions,
    build_ai_execution_policy_payload,
)

__all__ = [
    "AI_EXPERIMENT_EXECUTION_POLICY_VERSION",
    "DisplayName",
    "InstanceIdValue",
    "InstanceValues",
    "PrivateIpValue",
    "PromptText",
    "S3KeySegment",
    "ScriptExecutionContext",
    "build_ai_execution_policy_payload",
]


# ---------------------------------------------------------------------------
# Per-instance values
# ---------------------------------------------------------------------------


class InstanceValues(BaseModel):
    """Validated per-instance values used by ScriptExecutionContext.

    `name` is display-only metadata. `instance_id` is the safe path segment
    that render methods may interpolate into shell text.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: DisplayName
    instance_id: InstanceIdValue
    private_ip: PrivateIpValue | None = None


# ---------------------------------------------------------------------------
# Script execution context
# ---------------------------------------------------------------------------


class ScriptExecutionContext(BaseModel):
    """All validated values needed to build one script's shell command.

    The orchestrator constructs one of these per script assignment via
    :py:meth:`for_python` or :py:meth:`for_claude`, then reads the rendered
    command back via :py:meth:`render_command`. Direct construction is also
    supported when the resolved prompt and validated fields are already in
    hand (used by the test suite and by callers that have already done
    template resolution).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    script_type: Literal["python", "claude_code"]
    instance: InstanceValues
    script_s3_key: S3KeySegment | None = None
    claude_prompt_resolved: PromptText | None = None

    @model_validator(mode="after")
    def _payload_matches_type(self) -> Self:
        if self.script_type == "python":
            if self.script_s3_key is None:
                raise ValueError("script_s3_key is required when script_type='python'")
            if self.claude_prompt_resolved is not None:
                raise ValueError("claude_prompt_resolved must be None when script_type='python'")
        else:  # claude_code
            if self.claude_prompt_resolved is None:
                raise ValueError("claude_prompt_resolved is required when script_type='claude_code'")
            if self.script_s3_key is not None:
                raise ValueError("script_s3_key must be None when script_type='claude_code'")
        return self

    # ----- rendering ------------------------------------------------------

    def render_command(self) -> str:
        """Return the SSM-ready shell command for this script."""
        if self.script_type == "python":
            return self.render_python_command()
        return self.render_claude_command()

    def render_python_command(self) -> str:
        """Build the SSM shell wrapper for Python script execution.

        The remote transport accepts one shell string, so the shell text stays
        a fixed wrapper. The S3 key crosses that boundary as base64 data and
        is decoded inside Python before structured argv subprocess calls.
        """
        seg = self.instance.instance_id
        s3 = _encode_command_payload(self.script_s3_key or "")
        return f"""python3 - <<'PY'
import base64
import os
import subprocess
import sys

instance_id = "{seg}"
script_s3_key = base64.urlsafe_b64decode("{s3}").decode()
bucket_name = os.environ["BUCKET_NAME"]
script_path = f"/tmp/script_{{instance_id}}.py"
output_path = f"/tmp/output_{{instance_id}}.log"

subprocess.run(
    ["aws", "s3", "cp", f"s3://{{bucket_name}}/{{script_s3_key}}", script_path],
    check=True,
)
with open(output_path, "wb") as output:
    process = subprocess.Popen(
        ["python3", script_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    assert process.stdout is not None
    for chunk in iter(lambda: process.stdout.read(8192), b""):
        sys.stdout.buffer.write(chunk)
        sys.stdout.buffer.flush()
        output.write(chunk)
        output.flush()
    raise SystemExit(process.wait())
PY"""

    def render_claude_command(self) -> str:
        """Build the SSM shell wrapper for Claude Code execution.

        The prompt crosses the shell-only SSM boundary as base64 data. The
        fixed wrapper decodes it and passes it to Claude as one argv value.
        """
        prompt = _encode_command_payload(self.claude_prompt_resolved or "")
        return f"""python3 - <<'PY'
import base64
import subprocess
import sys

prompt = base64.urlsafe_b64decode("{prompt}").decode()
output_path = "/tmp/claude_output.json"

with open(output_path, "wb") as output:
    process = subprocess.Popen(
        [
            "claude",
            "--dangerously-skip-permissions",
            "--output-format",
            "stream-json",
            "-p",
            prompt,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    assert process.stdout is not None
    for chunk in iter(lambda: process.stdout.read(8192), b""):
        sys.stdout.buffer.write(chunk)
        sys.stdout.buffer.flush()
        output.write(chunk)
        output.flush()
    raise SystemExit(process.wait())
PY"""

    # ----- factories ------------------------------------------------------

    @classmethod
    def for_python(
        cls,
        *,
        instance_name: str,
        instance_id: str,
        private_ip: str | None,
        script_s3_key: str,
    ) -> ScriptExecutionContext:
        """Build a python-script context. Raises ValidationError on any bad field."""
        return cls(
            script_type="python",
            instance=InstanceValues(
                name=instance_name,
                instance_id=instance_id,
                private_ip=private_ip,
            ),
            script_s3_key=script_s3_key,
        )

    @classmethod
    def for_claude(
        cls,
        *,
        instance_name: str,
        instance_id: str,
        private_ip: str | None,
        claude_prompt_template: str,
        instance_data: dict[str, dict[str, Any]],
    ) -> ScriptExecutionContext:
        """Build a claude-script context, resolving template variables in-flight.

        Every substitution value in ``instance_data`` is run through the same
        typed validators that protect ``InstanceValues`` (instance ID, IPv4,
        display name) before resolution. This ensures the resolved prompt
        carries only values that match the documented contract — no value
        flows into the prompt body without passing the type boundary first.

        Resolution errors from `shared.template_vars.resolve_template`
        (unknown instance / property) surface as a Pydantic
        :class:`ValidationError` with `loc=("claude_prompt_template",)` so the
        orchestrator can handle them uniformly with field-level validation
        errors.
        """
        try:
            # Address Finding cycle-4 #2: validate only the instance/property
            # pairs the template actually references, not every entry in
            # instance_data. One Claude script must not fail because an
            # unrelated provisioned instance has a malformed IP.
            referenced = extract_variables(claude_prompt_template)
            validated_data = _validate_template_substitutions(instance_data, referenced)
            resolved = resolve_template(claude_prompt_template, validated_data)
            # Reject prompts whose resolution left any `{{...}}` substring
            # behind. The resolver's grammar (`\w+\.\w+`) silently passes
            # names with spaces (e.g. `Domain Controller`), so a prompt
            # `{{Domain Controller.ip}}` would dispatch with the literal
            # placeholder still embedded. The precise regex below avoids
            # rejecting a legitimate prose-level `{{` that lacks a closing
            # `}}` (cycle-5 #1).
            if _UNRESOLVED_PLACEHOLDER.search(resolved):
                raise ValueError(
                    "claude_prompt_template: contains unresolved placeholder(s) "
                    "after template resolution (likely an unsupported instance "
                    "or property name)"
                )
        except ValueError as exc:
            # Redact the raw template body; the resolver's message already
            # names the bad instance / property without echoing the prompt.
            raise ValidationError.from_exception_data(
                cls.__name__,
                [
                    InitErrorDetails(
                        type=PydanticCustomError(
                            "template_resolve_error",
                            "claude_prompt_template: {msg}",
                            {"msg": str(exc)},
                        ),
                        loc=("claude_prompt_template",),
                        input="<redacted>",
                    ),
                ],
            ) from exc
        return cls(
            script_type="claude_code",
            instance=InstanceValues(
                name=instance_name,
                instance_id=instance_id,
                private_ip=private_ip,
            ),
            claude_prompt_resolved=resolved,
        )
