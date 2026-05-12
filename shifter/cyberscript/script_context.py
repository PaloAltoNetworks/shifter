"""Validated execution context for experiment scripts.

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
   instance IDs (`i-[0-9a-f]{8,17}`) are structurally safe to interpolate
   into shell text. Display names may contain spaces, punctuation, and
   unicode (e.g. "Workstation 1", "Domain Controller"); they are
   metadata only.
3. **The Claude prompt's single-quote encoder is the only surviving
   ad-hoc shell encoder.** It lives inside `render_claude_command` and
   operates on the already-validated `PromptText`. The prompt may carry
   shell metacharacters (`$`, `;`, backticks, `|`); single-quote
   wrapping neutralises them at the shell layer without altering the
   semantic content of the prompt itself.
"""

from __future__ import annotations

import ipaddress
import re
from typing import Annotated, Any, Final, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    ValidationError,
    model_validator,
)
from pydantic_core import InitErrorDetails, PydanticCustomError

from cyberscript.template_vars import (
    ALLOWED_PROPERTIES,
    extract_variables,
    resolve_template,
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
# Target-specific value validators
# ---------------------------------------------------------------------------

_INSTANCE_ID_PATTERN = re.compile(r"^i-[0-9a-f]{8,17}$")
_S3_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._/=+-]+$")
# Detects ANY `{{...}}` substring that survived `resolve_template`. The
# resolver's grammar only matches `{{\w+\.\w+}}`, so placeholders whose
# instance name contains a space (e.g. `{{Domain Controller.ip}}`) pass
# through untouched. This catches those without rejecting a legitimate
# literal `{{` that lacks a closing `}}`.
_UNRESOLVED_PLACEHOLDER = re.compile(r"\{\{[^{}]+\}\}")

# Matches the persisted `FileAsset.s3_key` column width
# (`cms/models/assets.py: CharField(max_length=500)`). Keeping the
# execution-time cap aligned with the persisted contract prevents a
# normalized key from passing this validator yet failing at `asset.save()`.
_MAX_S3_KEY = 500
_MAX_DISPLAY_NAME = 100
_MAX_PROMPT_TEXT = 8192
_ALLOWED_CONTROL_CHARS = frozenset({"\t", "\n", "\r"})

AI_EXPERIMENT_EXECUTION_POLICY_VERSION: Final = "ai-experiment-execution-v1"


def build_ai_execution_policy_payload() -> dict[str, object]:
    """Return the auditable policy contract for AI experiment execution.

    The executor receives this payload with each command batch so incident
    review can tie a run back to the code-level policy that allowed Claude
    Code to run with skipped prompts. Keep this in lockstep with
    docs/architecture/ai-experiment-execution-boundary.md.
    """
    return {
        "version": AI_EXPERIMENT_EXECUTION_POLICY_VERSION,
        "claude_code": {
            "prompt_delivery": "validated_single_argument",
            "transcript_artifact_required": True,
        },
    }


def _validate_instance_id(v: str) -> str:
    """Validate the AWS EC2 instance ID format consumed by the SSM executor.

    Today's experiment dispatch path lands in AWS SSM RunCommand, which
    only accepts EC2 instance IDs of the form `i-[0-9a-f]{8,17}`.
    Plan-time validation against the same contract surfaces dispatch
    failures at experiment build time rather than as cryptic SSM errors
    at execution time. Broadening this pattern requires an explicit
    provider-aware execution-target change in the orchestrator and
    ECS task config.

    Error messages never echo the rejected value (per cycle-4 #4 — keeps
    user-controlled data out of orchestration errors and logs).
    """
    if not _INSTANCE_ID_PATTERN.fullmatch(v):
        raise ValueError(
            "instance_id must match 'i-' followed by 8..17 lowercase hex characters"
        )
    return v


def _validate_private_ip(v: str | None) -> str | None:
    """Validate canonical IPv4 dotted-quad. Error messages do not echo input."""
    if v is None:
        return None
    try:
        canonical = str(ipaddress.IPv4Address(v))
    except ValueError as exc:
        # ipaddress.AddressValueError subclasses ValueError; one except clause covers both.
        raise ValueError("private_ip must be an IPv4 dotted-quad") from exc
    if canonical != v:
        raise ValueError("private_ip must be in canonical IPv4 form")
    return v


def _validate_s3_key(v: str) -> str:
    """Validate an execution-time S3 key. Error messages do not echo input."""
    if not v:
        raise ValueError("script_s3_key cannot be empty")
    if len(v) > _MAX_S3_KEY:
        raise ValueError(
            f"script_s3_key exceeds {_MAX_S3_KEY} characters"
        )
    if v.startswith("/"):
        raise ValueError("script_s3_key must not start with '/'")
    if ".." in v:
        raise ValueError("script_s3_key must not contain '..'")
    if not _S3_KEY_PATTERN.fullmatch(v):
        raise ValueError(
            "script_s3_key may only contain [A-Za-z0-9._/=+-]"
        )
    return v


def _reject_control_chars(field: str, value: str) -> None:
    """Raise if `value` contains any disallowed control character.

    The error message names the field but not the codepoint, so the raw
    byte never appears in orchestration errors / logs.
    """
    for ch in value:
        cp = ord(ch)
        if cp == 0x7F or (cp < 0x20 and ch not in _ALLOWED_CONTROL_CHARS):
            raise ValueError(
                f"{field} contains a disallowed control character"
            )


def _validate_display_name(v: str) -> str:
    """Validate a display name. Error messages do not echo input."""
    if not v or not v.strip():
        raise ValueError("name cannot be empty or whitespace-only")
    if len(v) > _MAX_DISPLAY_NAME:
        raise ValueError(
            f"name exceeds {_MAX_DISPLAY_NAME} characters"
        )
    _reject_control_chars("name", v)
    return v


def _validate_prompt_text(v: str) -> str:
    """Validate the resolved prompt body. Error messages do not echo input."""
    if not v:
        raise ValueError("claude_prompt_resolved cannot be empty")
    if len(v) > _MAX_PROMPT_TEXT:
        raise ValueError(
            f"claude_prompt_resolved exceeds {_MAX_PROMPT_TEXT} characters"
        )
    _reject_control_chars("claude_prompt_resolved", v)
    return v


InstanceIdValue = Annotated[str, AfterValidator(_validate_instance_id)]
PrivateIpValue = Annotated[str, AfterValidator(_validate_private_ip)]
S3KeySegment = Annotated[str, AfterValidator(_validate_s3_key)]
DisplayName = Annotated[str, AfterValidator(_validate_display_name)]
PromptText = Annotated[str, AfterValidator(_validate_prompt_text)]


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


# Single registry that pairs each allowed template property with the
# typed validator that protects it. Iteration in
# `_validate_template_substitutions` is driven off `ALLOWED_PROPERTIES`
# (defined in `cyberscript.template_vars` and the source of truth for
# which template variables exist) so adding a new property forces both
# the template parser AND the execution validator to grow together.
_PROPERTY_VALIDATORS: dict[str, Any] = {
    "ip": _validate_private_ip,
    "name": _validate_display_name,
    "instance_id": _validate_instance_id,
}

_missing_property_validators = ALLOWED_PROPERTIES - _PROPERTY_VALIDATORS.keys()
if _missing_property_validators:
    raise ImportError(
        "cyberscript.script_context: missing typed validators for template "
        f"properties {_missing_property_validators}. Update _PROPERTY_VALIDATORS "
        "in lockstep with cyberscript.template_vars.ALLOWED_PROPERTIES."
    )


def _validate_template_substitutions(
    instance_data: dict[str, dict[str, Any]],
    referenced: list[tuple[str, str]],
) -> dict[str, dict[str, str]]:
    """Re-validate template substitution values through typed validators.

    `instance_data` is produced upstream by
    `cyberscript.template_vars.build_instance_data` from raw
    `provisioned_instances`; the values have not yet passed
    `ScriptExecutionContext`'s type boundary. This helper validates ONLY
    the (instance_name, property) pairs the template actually references
    (per Finding cycle-4 #2 — one script must not fail because an
    unrelated provisioned instance has a malformed value). Returns a
    dict in the same shape `resolve_template` expects, populated only
    with the referenced fields.

    Raises :class:`ValueError` if any referenced value fails validation
    or if a referenced property is not in `ALLOWED_PROPERTIES`.
    """
    validated: dict[str, dict[str, str]] = {}
    for instance_name, prop in referenced:
        if prop not in ALLOWED_PROPERTIES:
            raise ValueError(
                f"claude_prompt_template: unsupported property '{prop}' on "
                f"'{instance_name}' (allowed: {sorted(ALLOWED_PROPERTIES)})"
            )
        props = instance_data.get(instance_name)
        if not isinstance(props, dict):
            # Unknown instance — let resolve_template raise the canonical
            # "instance not found" message rather than duplicating it here.
            continue
        value = props.get(prop)
        if not value:
            # Missing value — same handling: let resolve_template surface
            # the "property not found" message.
            continue
        validator = _PROPERTY_VALIDATORS[prop]
        entry = validated.setdefault(instance_name, {})
        entry[prop] = validator(str(value)) or ""
    return validated


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
                raise ValueError(
                    "script_s3_key is required when script_type='python'"
                )
            if self.claude_prompt_resolved is not None:
                raise ValueError(
                    "claude_prompt_resolved must be None when script_type='python'"
                )
        else:  # claude_code
            if self.claude_prompt_resolved is None:
                raise ValueError(
                    "claude_prompt_resolved is required when script_type='claude_code'"
                )
            if self.script_s3_key is not None:
                raise ValueError(
                    "script_s3_key must be None when script_type='claude_code'"
                )
        return self

    # ----- rendering ------------------------------------------------------

    def render_command(self) -> str:
        """Return the SSM-ready shell command for this script."""
        if self.script_type == "python":
            return self.render_python_command()
        return self.render_claude_command()

    def render_python_command(self) -> str:
        """Build the `aws s3 cp … && python3 … | tee …` pipeline.

        The path segment is the instance ID (structurally `i-[0-9a-f]{8,17}`)
        and the S3 key is whitelist-validated; both are safe to interpolate
        directly into shell text.
        """
        seg = self.instance.instance_id
        s3 = self.script_s3_key
        return (
            f"aws s3 cp s3://${{BUCKET_NAME}}/{s3} /tmp/script_{seg}.py "
            f"&& python3 /tmp/script_{seg}.py "
            f"2>&1 | tee /tmp/output_{seg}.log"
        )

    def render_claude_command(self) -> str:
        """Build the `claude … -p '…' | tee …` invocation.

        Applies POSIX single-quote encoding to the validated prompt
        (`'foo'\\''bar'` for an embedded single quote), then wraps the
        result in `'…'`. Shell metacharacters inside the prompt are
        neutralised by the single-quoted argument and never reach the
        shell interpreter.
        """
        encoded = self.claude_prompt_resolved.replace("'", "'\\''")
        return (
            "claude --dangerously-skip-permissions "
            "--output-format stream-json "
            f"-p '{encoded}' "
            "2>&1 | tee /tmp/claude_output.json"
        )

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

        Resolution errors from `cyberscript.template_vars.resolve_template`
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
