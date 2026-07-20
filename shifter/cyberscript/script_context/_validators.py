"""Target-specific value validators for `ScriptExecutionContext`.

Every value that flows from user input into the experiment script execution
layer (orchestrator → ECS → SSM) is validated here before any render method
produces the final shell text. Whitelist at the type boundary: target-specific
Annotated str types (`InstanceIdValue`, `S3KeySegment`, `PrivateIpValue`,
`DisplayName`, `PromptText`) constrain each value to a character set safe at
its destination.
"""

from __future__ import annotations

import base64
import ipaddress
import re
from typing import Annotated, Any, Final

from pydantic import AfterValidator

from cyberscript.template_vars import ALLOWED_PROPERTIES


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
            "prompt_delivery": "encoded_shell_wrapper",
            "transcript_artifact_required": True,
        },
    }


def _encode_command_payload(value: str) -> str:
    """Encode data for fixed shell wrappers using shell-safe base64."""
    return base64.urlsafe_b64encode(value.encode()).decode()


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
        raise ValueError(f"script_s3_key exceeds {_MAX_S3_KEY} characters")
    if v.startswith("/"):
        raise ValueError("script_s3_key must not start with '/'")
    if ".." in v:
        raise ValueError("script_s3_key must not contain '..'")
    if not _S3_KEY_PATTERN.fullmatch(v):
        raise ValueError("script_s3_key may only contain [A-Za-z0-9._/=+-]")
    return v


def _reject_control_chars(field: str, value: str) -> None:
    """Raise if `value` contains any disallowed control character.

    The error message names the field but not the codepoint, so the raw
    byte never appears in orchestration errors / logs.
    """
    for ch in value:
        cp = ord(ch)
        if cp == 0x7F or (cp < 0x20 and ch not in _ALLOWED_CONTROL_CHARS):
            raise ValueError(f"{field} contains a disallowed control character")


def _validate_display_name(v: str) -> str:
    """Validate a display name. Error messages do not echo input."""
    if not v or not v.strip():
        raise ValueError("name cannot be empty or whitespace-only")
    if len(v) > _MAX_DISPLAY_NAME:
        raise ValueError(f"name exceeds {_MAX_DISPLAY_NAME} characters")
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
