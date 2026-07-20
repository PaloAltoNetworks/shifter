#!/usr/bin/env python3
"""Lint IAM scope on the per-range Polaris Bedrock agent role (#1377).

``aws_iam_role.polaris_agent`` is the participant-facing AWS credential for
the a14-kali container on a Polaris range host. It is deliberately narrow:
the trust policy binds to the shared range-instance role AND the exact
Polaris EC2 source instance (``ec2:SourceInstanceARN``), and the attached
inline policy (``aws_iam_role_policy.polaris_agent``) grants only
``bedrock:InvokeModel``/``bedrock:InvokeModelWithResponseStream`` on the two
approved inference profiles and, conditioned on
``bedrock:InferenceProfileArn``, their backing foundation models. No S3,
SSM, IAM, KMS, Secrets Manager, arbitrary STS, or wildcard Bedrock access.

This checker rejects any drift from that narrow shape:

  - Inline policy actions other than the two approved Bedrock invoke verbs
    (including any ``bedrock:*`` or full ``*`` wildcard).
  - Inline policy resources other than the four expected
    ``polaris_agent_*_inference_profile_arn`` /
    ``polaris_agent_*_backing_model_arns`` variables (including
    ``Resource = "*"`` or any other wildcard ARN).
  - A backing-model statement missing its ``bedrock:InferenceProfileArn``
    condition.
  - A trust policy whose ``Principal`` is not ``var.range_instance_role_arn``
    (a wildcard or a service principal), or that is missing the
    ``ec2:SourceInstanceARN`` condition.
  - A role missing its permissions boundary or standard Shifter tags, whose
    ``permissions_boundary`` is not set unconditionally to
    ``var.polaris_agent_permissions_boundary_arn`` (a ``null`` literal or a
    ``? :`` conditional would let an enabled role apply with no boundary),
    or whose ``lifecycle.precondition`` does not independently require that
    variable to be non-empty.

It also FAILS CLOSED on drift that would otherwise make the guard silently
pass:

  - The ``aws_iam_role.polaris_agent`` / ``aws_iam_role_policy.polaris_agent``
    resources being deleted or renamed away. The checker requires both to
    exist under their expected addresses; it does not merely validate
    whichever same-named blocks happen to still be there.
  - An inline policy statement whose ``Action`` or ``Resource`` field is
    missing entirely, or is written as an expression this parser cannot
    confidently resolve to a literal action list / the approved
    ``var.polaris_agent_*`` variables (e.g. a ``local.`` reference, a
    ternary, or any other dynamic shape). These surface as explicit
    violations rather than being read as "no forbidden content found".
  - The inline policy failing to grant both approved actions, or failing to
    reference all four approved resource variables, anywhere in the file
    (catches an emptied or gutted policy body even when the resource block
    itself is still present).

See docs/architecture/polaris-aws-agent-credentials-preflight-1377.md.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

# Resource type/name of the role and its inline policy, as defined in
# shifter/engine/provisioner/terraform/modules/range/iam.tf.
ROLE_RESOURCE_TYPE = "aws_iam_role"
POLICY_RESOURCE_TYPE = "aws_iam_role_policy"
DEFAULT_RESOURCE_NAME = "polaris_agent"

# Managed-policy attachment resource types that can grant the protected role
# extra permissions outside its single canonical inline policy. Real
# terraform-provider-aws only ships aws_iam_role_policy_attachment, but
# aws_iam_role_managed_policy_attachment is also recognized defensively in
# case a future provider/module shape introduces it.
ATTACHMENT_RESOURCE_TYPES: frozenset[str] = frozenset(
    {
        "aws_iam_role_policy_attachment",
        "aws_iam_role_managed_policy_attachment",
    }
)

# The only two actions the inline policy may grant.
_ALLOWED_ACTIONS: frozenset[str] = frozenset(
    {
        "bedrock:invokemodel",
        "bedrock:invokemodelwithresponsestream",
    }
)

# The only four variables the inline policy's Resource fields may reference.
_ALLOWED_RESOURCE_VARS: frozenset[str] = frozenset(
    {
        "polaris_agent_main_inference_profile_arn",
        "polaris_agent_small_inference_profile_arn",
        "polaris_agent_main_backing_model_arns",
        "polaris_agent_small_backing_model_arns",
    }
)

# Backing-model resource variables require the InferenceProfileArn condition
# (they are reachable ONLY through the approved inference profiles).
_BACKING_MODEL_VARS: frozenset[str] = frozenset(
    {
        "polaris_agent_main_backing_model_arns",
        "polaris_agent_small_backing_model_arns",
    }
)

_INFERENCE_PROFILE_CONDITION_KEY = "bedrock:InferenceProfileArn"
_SOURCE_INSTANCE_CONDITION_KEY = "ec2:SourceInstanceARN"
_TRUST_PRINCIPAL_VAR = "range_instance_role_arn"
_PERMISSIONS_BOUNDARY_VAR = "polaris_agent_permissions_boundary_arn"

_RESOURCE_RE = re.compile(
    r'^\s*resource\s+"(aws_iam_role|aws_iam_role_policy|aws_iam_role_policy_attachment'
    r'|aws_iam_role_managed_policy_attachment)"\s+"([^"]+)"\s*\{'
)
_ACTION_FIELD_RE = re.compile(r'Action\s*=\s*(\[[^\]]*\]|"[^"]*")', re.DOTALL)
_RESOURCE_FIELD_KEY_RE = re.compile(r"Resource\s*=\s*")
_PRINCIPAL_FIELD_RE = re.compile(r'Principal\s*=\s*(\{[^}]*\}|"[^"]*")', re.DOTALL)
_QUOTED_RE = re.compile(r'"([^"]*)"')
_VAR_REF_RE = re.compile(r"var\.([A-Za-z_][A-Za-z0-9_]*)")
_PERMISSIONS_BOUNDARY_FIELD_RE = re.compile(r"permissions_boundary\s*=\s*([^\n]+)")
_PERMISSIONS_BOUNDARY_NON_EMPTY_PRECONDITION_RE = re.compile(r'polaris_agent_permissions_boundary_arn\s*!=\s*""')
_ROLE_FIELD_RE = re.compile(r"^\s*role\s*=\s*(.+)$", re.MULTILINE)
_MANAGED_POLICY_ARNS_FIELD_RE = re.compile(r"\bmanaged_policy_arns\s*=")


@dataclass
class Violation:
    file: Path
    line: int
    reason: str

    def __str__(self) -> str:
        return f"{self.file}:{self.line}: {self.reason}"


def _brace_delta(line: str) -> int:
    return line.count("{") - line.count("}")


def _extract_resource_blocks(lines: list[str]) -> list[tuple[int, str, str, str]]:
    """Return (start_line, resource_type, resource_name, block_text)."""
    blocks: list[tuple[int, str, str, str]] = []
    idx = 0
    while idx < len(lines):
        match = _RESOURCE_RE.match(lines[idx])
        if not match:
            idx += 1
            continue

        start_idx = idx
        depth = _brace_delta(lines[idx])
        idx += 1
        while idx < len(lines) and depth > 0:
            depth += _brace_delta(lines[idx])
            idx += 1

        block = "\n".join(lines[start_idx:idx])
        blocks.append((start_idx + 1, match.group(1), match.group(2), block))
    return blocks


def _extract_statement_blocks(block_lines: list[str]) -> list[tuple[int, str]]:
    """Return (relative_line, statement_text) for IAM statement brace blocks.

    Any block carrying an ``Action`` field is a statement candidate; filtering
    on a literal ``"bedrock:`` token here would fail open on full-wildcard
    statements (``Action = "*"``).
    """
    statements: list[tuple[int, str]] = []
    idx = 0
    while idx < len(block_lines):
        if not re.match(r"^\s*\{\s*$", block_lines[idx]):
            idx += 1
            continue

        start_idx = idx
        depth = _brace_delta(block_lines[idx])
        idx += 1
        while idx < len(block_lines) and depth > 0:
            depth += _brace_delta(block_lines[idx])
            idx += 1

        statement = "\n".join(block_lines[start_idx:idx])
        if "Action" in statement:
            statements.append((start_idx + 1, statement))
    return statements


def _balanced_span(text: str, open_idx: int) -> int:
    """Return the index just past the char matching text[open_idx]."""
    open_ch = text[open_idx]
    close_ch = {"(": ")", "[": "]", "{": "}"}[open_ch]
    depth = 0
    for i in range(open_idx, len(text)):
        if text[i] == open_ch:
            depth += 1
        elif text[i] == close_ch:
            depth -= 1
            if depth == 0:
                return i + 1
    return len(text)


def _split_top_level(text: str) -> list[str]:
    """Split ``text`` on commas that are not nested inside (), [], {}, or a
    quoted string, so callers can walk the arguments of a function call or
    the elements of a bracketed list one atom at a time."""
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    in_string = False
    for i, ch in enumerate(text):
        if in_string:
            current.append(ch)
            if ch == '"' and text[i - 1] != "\\":
                in_string = False
            continue
        if ch == '"':
            in_string = True
            current.append(ch)
        elif ch in "([{":
            depth += 1
            current.append(ch)
        elif ch in ")]}":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    tail = "".join(current)
    if tail.strip():
        parts.append(tail)
    return [p.strip() for p in parts if p.strip()]


def _resource_field_raw(statement: str) -> str | None:
    """Return the raw text of a statement's Resource value, or ``None`` if
    the field is absent entirely.

    Handles the three shapes this policy uses: a quoted scalar (``"*"``), a
    bracketed list of bare ``var.x`` references, and a function call such as
    ``concat(var.x, var.y)``. Anything else (a bare reference such as
    ``local.x``, or a more complex expression such as a ternary) is
    returned verbatim through to the end of its line rather than truncated
    to a plausible-looking prefix, so the caller can recognize it as an
    unparseable shape instead of silently matching only its leading token.
    """
    match = _RESOURCE_FIELD_KEY_RE.search(statement)
    if match is None:
        return None
    idx = match.end()
    while idx < len(statement) and statement[idx].isspace():
        idx += 1
    if idx >= len(statement):
        return None

    ch = statement[idx]
    if ch == '"':
        end = statement.index('"', idx + 1) + 1
        return statement[idx:end]
    if ch in "[(":
        end = _balanced_span(statement, idx)
        return statement[idx:end]

    ident_match = re.match(r"[A-Za-z_][A-Za-z0-9_.]*", statement[idx:])
    if ident_match is None:
        return None
    end = idx + ident_match.end()

    call_idx = end
    while call_idx < len(statement) and statement[call_idx] in " \t":
        call_idx += 1
    if call_idx < len(statement) and statement[call_idx] == "(":
        return statement[idx:_balanced_span(statement, call_idx)]

    # Not a function call: this is either a bare reference (``var.x``,
    # ``local.x``) or the start of a more complex expression (a ternary, a
    # comparison, string concatenation, ...). Capture through the end of
    # the line so the resolver below sees the whole expression and can
    # reject anything beyond a single unambiguous reference, instead of
    # this function quietly truncating to just the leading identifier.
    newline_idx = statement.find("\n", end)
    line_end = newline_idx if newline_idx != -1 else len(statement)
    return statement[idx:line_end].strip()


def _resolve_scalar_atom(text: str) -> tuple[str | None, str | None]:
    """Resolve a single Resource atom to (literal, var_name); both None if
    the atom is neither a quoted literal nor a bare ``var.x`` reference."""
    text = text.strip()
    literal_match = _QUOTED_RE.fullmatch(text)
    if literal_match is not None:
        return literal_match.group(1), None
    var_match = _VAR_REF_RE.fullmatch(text)
    if var_match is not None:
        return None, var_match.group(1)
    return None, None


def _resolve_atom_list(elements: list[str]) -> tuple[list[str], list[str]] | None:
    literals: list[str] = []
    var_names: list[str] = []
    for element in elements:
        literal, var_name = _resolve_scalar_atom(element)
        if literal is None and var_name is None:
            return None
        if literal is not None:
            literals.append(literal)
        if var_name is not None:
            var_names.append(var_name)
    return literals, var_names


def _parse_resource_expr(statement: str) -> tuple[list[str], list[str]] | None:
    """Resolve a statement's Resource field to (literal ARNs, var names).

    Returns ``None`` when the field is missing, or when its value is not
    one of the shapes this policy is expected to use (a quoted scalar, a
    bracketed list of literals/``var.x`` refs, a function call over such a
    list, or a single bare ``var.x`` reference) -- e.g. a ``local.``
    reference, a ternary, or any other expression this parser cannot
    confidently resolve. Callers must treat ``None`` as "unparseable", not
    as "no resources granted".
    """
    raw = _resource_field_raw(statement)
    if raw is None:
        return None
    raw = raw.strip()

    if raw.startswith('"'):
        literal_match = _QUOTED_RE.fullmatch(raw)
        if literal_match is None:
            return None
        return [literal_match.group(1)], []

    if raw.startswith("[") and raw.endswith("]"):
        return _resolve_atom_list(_split_top_level(raw[1:-1]))

    call_match = re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*\((.*)\)", raw, re.DOTALL)
    if call_match is not None:
        return _resolve_atom_list(_split_top_level(call_match.group(1)))

    literal, var_name = _resolve_scalar_atom(raw)
    if literal is None and var_name is None:
        return None
    return ([literal] if literal is not None else [], [var_name] if var_name is not None else [])


def _parse_action_expr(statement: str) -> list[str] | None:
    """Resolve a statement's Action field to a flat list of literal action
    strings.

    Returns ``None`` when the field is missing, or when its value is not a
    quoted scalar or a bracketed list of quoted literals -- e.g. a
    ``var.``/``local.`` reference or any other dynamic expression. Callers
    must treat ``None`` as "unparseable", not as "no actions granted".
    """
    match = _ACTION_FIELD_RE.search(statement)
    if match is None:
        return None

    raw = match.group(1)
    if raw.startswith('"'):
        literal_match = _QUOTED_RE.fullmatch(raw)
        return [literal_match.group(1)] if literal_match is not None else None

    # raw is a "[...]" list per _ACTION_FIELD_RE's alternation.
    tokens: list[str] = []
    for element in _split_top_level(raw[1:-1]):
        literal_match = _QUOTED_RE.fullmatch(element)
        if literal_match is None:
            return None
        tokens.append(literal_match.group(1))
    return tokens


def _statement_action_violations(
    path: Path, line: int, statement: str
) -> tuple[list[Violation], set[str]]:
    tokens = _parse_action_expr(statement)
    if tokens is None:
        return (
            [
                Violation(
                    path,
                    line,
                    "Bedrock agent policy statement's Action could not be resolved "
                    "to a literal action or list of literal actions; only "
                    "bedrock:InvokeModel and bedrock:InvokeModelWithResponseStream "
                    "may be granted",
                )
            ],
            set(),
        )

    violations: list[Violation] = []
    seen: set[str] = set()
    for action in tokens:
        lowered = action.lower()
        seen.add(lowered)
        if lowered not in _ALLOWED_ACTIONS:
            violations.append(
                Violation(
                    path,
                    line,
                    f'Bedrock agent policy grants disallowed action "{action}"; '
                    "only bedrock:InvokeModel and bedrock:InvokeModelWithResponseStream "
                    "are permitted",
                )
            )
    return violations, seen


def _statement_resource_violations(
    path: Path, line: int, statement: str
) -> tuple[list[Violation], set[str]]:
    if _RESOURCE_FIELD_KEY_RE.search(statement) is None:
        return (
            [
                Violation(
                    path,
                    line,
                    "Bedrock agent policy statement is missing a Resource field; "
                    "every statement must scope Resource to the four approved "
                    "polaris_agent inference-profile/backing-model variables",
                )
            ],
            set(),
        )

    parsed = _parse_resource_expr(statement)
    if parsed is None:
        return (
            [
                Violation(
                    path,
                    line,
                    "Bedrock agent policy statement's Resource could not be resolved "
                    "to literal ARNs or polaris_agent variables; only the four "
                    "approved polaris_agent inference-profile/backing-model "
                    "variables are permitted",
                )
            ],
            set(),
        )

    literals, var_names = parsed
    violations: list[Violation] = []
    for token in literals:
        if token == "*" or "*" in token:
            violations.append(
                Violation(
                    path,
                    line,
                    "Bedrock agent policy Resource must not use a wildcard ARN "
                    f'("{token}")',
                )
            )
        else:
            violations.append(
                Violation(
                    path,
                    line,
                    f'Bedrock agent policy Resource references unexpected literal "{token}"; '
                    "only the four polaris_agent inference-profile/backing-model "
                    "variables are permitted",
                )
            )

    for var_name in var_names:
        if var_name not in _ALLOWED_RESOURCE_VARS:
            violations.append(
                Violation(
                    path,
                    line,
                    f"Bedrock agent policy Resource references unexpected variable "
                    f"var.{var_name}; only the four polaris_agent inference-profile/"
                    "backing-model variables are permitted",
                )
            )
    return violations, set(var_names)


def _statement_condition_violations(
    path: Path, line: int, statement: str, resource_var_names: set[str]
) -> list[Violation]:
    if (
        resource_var_names & _BACKING_MODEL_VARS
        and _INFERENCE_PROFILE_CONDITION_KEY not in statement
    ):
        return [
            Violation(
                path,
                line,
                "Bedrock agent policy statement granting access to backing "
                f"foundation models must carry a {_INFERENCE_PROFILE_CONDITION_KEY} "
                "condition scoping it to the approved inference profiles",
            )
        ]
    return []


def _policy_violations(path: Path, block_start: int, block: str) -> list[Violation]:
    violations: list[Violation] = []
    block_lines = block.splitlines()
    action_tokens_seen: set[str] = set()
    resource_vars_seen: set[str] = set()

    for relative_line, statement in _extract_statement_blocks(block_lines):
        line = block_start + relative_line - 1

        action_violations, tokens = _statement_action_violations(path, line, statement)
        violations.extend(action_violations)
        action_tokens_seen.update(tokens)

        resource_violations, var_names = _statement_resource_violations(path, line, statement)
        violations.extend(resource_violations)
        resource_vars_seen.update(var_names)

        violations.extend(_statement_condition_violations(path, line, statement, var_names))

    # Fail closed on an emptied/gutted policy body: even if every statement
    # that IS present parses cleanly, the policy as a whole must still grant
    # both approved actions and reference all four approved resource
    # variables somewhere. Silently accepting a policy that grants neither
    # (or only some) is how a deleted statement -- or a body wiped down to
    # `{}` -- would otherwise still show zero violations.
    missing_actions = _ALLOWED_ACTIONS - action_tokens_seen
    if missing_actions:
        violations.append(
            Violation(
                path,
                block_start,
                "Bedrock agent policy is missing required action(s): "
                f"{', '.join(sorted(missing_actions))}",
            )
        )

    missing_vars = _ALLOWED_RESOURCE_VARS - resource_vars_seen
    if missing_vars:
        violations.append(
            Violation(
                path,
                block_start,
                "Bedrock agent policy is missing required resource variable(s): "
                f"{', '.join('var.' + v for v in sorted(missing_vars))}",
            )
        )

    return violations


def _extract_jsonencode_block(block_text: str, field_name: str) -> str | None:
    pattern = re.escape(field_name) + r"\s*=\s*jsonencode\(\s*\{"
    match = re.search(pattern, block_text)
    if match is None:
        return None
    open_idx = match.end() - 1
    end_idx = _balanced_span(block_text, open_idx)
    return block_text[open_idx:end_idx]


def _role_trust_violations(path: Path, block_start: int, block: str) -> list[Violation]:
    violations: list[Violation] = []
    trust = _extract_jsonencode_block(block, "assume_role_policy")
    if trust is None:
        return [
            Violation(
                path,
                block_start,
                "polaris_agent role is missing an assume_role_policy trust document",
            )
        ]

    principal_match = _PRINCIPAL_FIELD_RE.search(trust)
    if principal_match is None:
        violations.append(
            Violation(path, block_start, "polaris_agent trust policy is missing a Principal")
        )
    else:
        principal_value = principal_match.group(1)
        if '"*"' in principal_value:
            violations.append(
                Violation(
                    path,
                    block_start,
                    "polaris_agent trust policy Principal must not be * (any AWS principal)",
                )
            )
        if "Service" in principal_value:
            violations.append(
                Violation(
                    path,
                    block_start,
                    "polaris_agent trust policy Principal must not be a service principal; "
                    f"it must be var.{_TRUST_PRINCIPAL_VAR}",
                )
            )
        if _TRUST_PRINCIPAL_VAR not in principal_value:
            violations.append(
                Violation(
                    path,
                    block_start,
                    f"polaris_agent trust policy Principal must reference "
                    f"var.{_TRUST_PRINCIPAL_VAR}",
                )
            )

    if _SOURCE_INSTANCE_CONDITION_KEY not in trust:
        violations.append(
            Violation(
                path,
                block_start,
                f"polaris_agent trust policy is missing the {_SOURCE_INSTANCE_CONDITION_KEY} "
                "condition binding it to the exact Polaris EC2 source instance",
            )
        )
    return violations


def _extract_all_balanced_blocks(text: str, keyword: str) -> list[str]:
    """Return every ``{...}`` block introduced by ``keyword {`` in ``text``.

    Used to isolate each ``lifecycle { precondition { ... } }`` sub-block so a
    substring search for the boundary non-empty check can't accidentally
    match unrelated text elsewhere in the resource block.
    """
    blocks: list[str] = []
    pattern = re.compile(re.escape(keyword) + r"\s*\{")
    search_from = 0
    while True:
        match = pattern.search(text, search_from)
        if match is None:
            break
        open_idx = match.end() - 1
        end_idx = _balanced_span(text, open_idx)
        blocks.append(text[open_idx:end_idx])
        search_from = end_idx
    return blocks


def _has_boundary_non_empty_precondition(block: str) -> bool:
    """Return True if some ``precondition`` block requires the boundary ARN non-empty."""
    return any(
        _PERMISSIONS_BOUNDARY_NON_EMPTY_PRECONDITION_RE.search(precondition)
        for precondition in _extract_all_balanced_blocks(block, "precondition")
    )


def _permissions_boundary_field_violation(path: Path, block_start: int, block: str) -> Violation | None:
    """Validate that permissions_boundary is set unconditionally to the approved variable.

    A ``null`` literal or a ``cond ? var.x : null`` ternary would let an
    enabled agent role (``count = var.polaris_agent_enabled ? 1 : 0``) apply
    with no permissions boundary whenever the boundary variable happened to
    be empty -- the previous checker accepted either shape merely because it
    mentioned the variable name somewhere in the block.
    """
    match = _PERMISSIONS_BOUNDARY_FIELD_RE.search(block)
    if match is None:
        return Violation(path, block_start, "polaris_agent role must set permissions_boundary")

    raw_value = match.group(1)
    comment_idx = raw_value.find("#")
    if comment_idx != -1:
        raw_value = raw_value[:comment_idx]
    raw_value = raw_value.strip()

    expected = f"var.{_PERMISSIONS_BOUNDARY_VAR}"
    if raw_value == expected:
        return None

    return Violation(
        path,
        block_start,
        f"polaris_agent role permissions_boundary must be set unconditionally to var.{_PERMISSIONS_BOUNDARY_VAR} "
        f"(an enabled agent role must always carry a non-empty permissions boundary); found {raw_value!r}",
    )


def _role_boundary_and_tags_violations(path: Path, block_start: int, block: str) -> list[Violation]:
    violations: list[Violation] = []

    boundary_violation = _permissions_boundary_field_violation(path, block_start, block)
    if boundary_violation is not None:
        violations.append(boundary_violation)

    if not _has_boundary_non_empty_precondition(block):
        violations.append(
            Violation(
                path,
                block_start,
                "polaris_agent role lifecycle.precondition must require "
                f'var.{_PERMISSIONS_BOUNDARY_VAR} != "" so an enabled role '
                "(count = var.polaris_agent_enabled ? 1 : 0) can never apply without a "
                "permissions boundary",
            )
        )

    if not re.search(r"\btags\s*=", block):
        violations.append(Violation(path, block_start, "polaris_agent role must set tags"))
    elif "common_tags" not in block:
        violations.append(
            Violation(
                path,
                block_start,
                "polaris_agent role tags must merge the shared local.common_tags",
            )
        )
    return violations


def _role_reference_pattern(resource_name: str) -> re.Pattern[str]:
    """Match a reference to ``aws_iam_role.<resource_name>`` (optionally
    indexed, e.g. ``[0].id`` / ``.name``), without matching a differently
    named role that merely shares the prefix (``polaris_agent_v2``)."""
    return re.compile(r"\baws_iam_role\." + re.escape(resource_name) + r"\b")


def _targets_protected_role(block: str, role_ref_re: re.Pattern[str]) -> bool:
    """Return True if ``block``'s ``role`` argument references the
    protected role. Falls back to scanning the whole block when no ``role``
    field is found, so a malformed/missing field still fails closed instead
    of silently passing."""
    role_match = _ROLE_FIELD_RE.search(block)
    target_text = role_match.group(1) if role_match is not None else block
    return role_ref_re.search(target_text) is not None


def _extra_inline_policy_violations(
    path: Path,
    resource_blocks: list[tuple[int, str, str, str]],
    resource_name: str,
) -> list[Violation]:
    """Reject any ``aws_iam_role_policy`` other than the single canonical
    one (named ``resource_name``) whose ``role`` argument targets the
    protected role. A malicious/careless PR could add a second inline
    policy under a different resource name and grant it arbitrary
    permissions while leaving the canonical narrow policy untouched."""
    role_ref_re = _role_reference_pattern(resource_name)
    violations: list[Violation] = []
    for start, resource_type, name, block in resource_blocks:
        if resource_type != POLICY_RESOURCE_TYPE or name == resource_name:
            continue
        if not _targets_protected_role(block, role_ref_re):
            continue
        violations.append(
            Violation(
                path,
                start,
                "extra_inline_policy_on_role: aws_iam_role_policy "
                f'"{name}" attaches an additional inline policy to '
                f"aws_iam_role.{resource_name}; only the single canonical "
                f"{POLICY_RESOURCE_TYPE}.{resource_name} inline policy may "
                "target this role",
            )
        )
    return violations


def _managed_policy_attachment_violations(
    path: Path,
    resource_blocks: list[tuple[int, str, str, str]],
    resource_name: str,
) -> list[Violation]:
    """Reject any managed-policy attachment resource whose ``role`` argument
    targets the protected role. The participant role must carry only the
    canonical narrow inline policy; a managed-policy attachment would grant
    every permission in the attached policy up to the account boundary."""
    role_ref_re = _role_reference_pattern(resource_name)
    violations: list[Violation] = []
    for start, resource_type, name, block in resource_blocks:
        if resource_type not in ATTACHMENT_RESOURCE_TYPES:
            continue
        if not _targets_protected_role(block, role_ref_re):
            continue
        violations.append(
            Violation(
                path,
                start,
                f'managed_policy_attachment_on_role: {resource_type} "{name}" '
                f"attaches a managed policy to aws_iam_role.{resource_name}; "
                "the participant role must carry only the canonical narrow "
                "inline policy, no managed-policy attachments",
            )
        )
    return violations


def _role_managed_policy_arns_violation(
    path: Path, block_start: int, block: str, resource_name: str
) -> Violation | None:
    """Reject an inline ``managed_policy_arns`` argument on the protected
    role itself, which would attach managed policies without going through
    a separate (also-checked) attachment resource."""
    if _MANAGED_POLICY_ARNS_FIELD_RE.search(block) is None:
        return None
    return Violation(
        path,
        block_start,
        f"managed_policy_arns_on_role: aws_iam_role.{resource_name} sets "
        "managed_policy_arns; the participant role must carry only the "
        "canonical narrow inline policy, no managed policies",
    )


def check_file(path: Path, resource_name: str = DEFAULT_RESOURCE_NAME) -> list[Violation]:
    lines = path.read_text().splitlines()
    blocks = _extract_resource_blocks(lines)

    role_blocks = [
        (start, block)
        for start, resource_type, name, block in blocks
        if resource_type == ROLE_RESOURCE_TYPE and name == resource_name
    ]
    policy_blocks = [
        (start, block)
        for start, resource_type, name, block in blocks
        if resource_type == POLICY_RESOURCE_TYPE and name == resource_name
    ]

    violations: list[Violation] = []

    # Fail closed if the protected resources have been deleted or renamed
    # away: validating only whichever same-named blocks happen to still
    # exist means a rename silently drops all coverage below.
    if not role_blocks:
        violations.append(
            Violation(
                path,
                1,
                f'required resource "{ROLE_RESOURCE_TYPE}" "{resource_name}" not found; '
                "the Polaris Bedrock agent role must not be removed or renamed",
            )
        )
    for block_start, block in role_blocks:
        violations.extend(_role_trust_violations(path, block_start, block))
        violations.extend(_role_boundary_and_tags_violations(path, block_start, block))
        managed_policy_arns_violation = _role_managed_policy_arns_violation(
            path, block_start, block, resource_name
        )
        if managed_policy_arns_violation is not None:
            violations.append(managed_policy_arns_violation)

    if not policy_blocks:
        violations.append(
            Violation(
                path,
                1,
                f'required resource "{POLICY_RESOURCE_TYPE}" "{resource_name}" not found; '
                "the Polaris Bedrock agent inline policy must not be removed or renamed",
            )
        )
    for block_start, block in policy_blocks:
        violations.extend(_policy_violations(path, block_start, block))

    # Fail closed on additional policy surfaces attached to the protected
    # role outside the single canonical inline policy validated above: a
    # second aws_iam_role_policy, or any managed-policy attachment,
    # targeting aws_iam_role.<resource_name> would grant the participant's
    # STS credentials extra permissions while the canonical policy (and
    # this checker's per-statement checks above) never saw them.
    violations.extend(_extra_inline_policy_violations(path, blocks, resource_name))
    violations.extend(_managed_policy_attachment_violations(path, blocks, resource_name))

    return violations


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(
            "usage: check_tf_iam_bedrock_agent_scope.py FILE.tf [FILE.tf ...]",
            file=sys.stderr,
        )
        return 2

    violations: list[Violation] = []
    for arg in argv[1:]:
        path = Path(arg)
        if not path.exists():
            print(f"{path}: file not found", file=sys.stderr)
            return 2
        if path.suffix == ".tf":
            violations.extend(check_file(path))

    if violations:
        print(
            "Polaris Bedrock agent IAM scope violations "
            f"({len(violations)} total):",
            file=sys.stderr,
        )
        for violation in violations:
            print(f"  {violation}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
