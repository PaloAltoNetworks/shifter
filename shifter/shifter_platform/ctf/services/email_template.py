"""Safe placeholder substitution for organizer-authored CTF email templates.

Organizer-authored ``CTFEmailTemplate.html_body`` / ``text_body`` are
untrusted content and must NOT be rendered with Django's template engine:
even ``{{ a.b.c }}`` expressions traverse attributes and call no-arg methods
on context objects, exposing data the organizer should not see (CWE-1336
server-side template injection / information exposure, issue #1095).

This module is the single CTF-owned policy shared by API validation
(``ctf.views``), model validation (``CTFEmailTemplate.clean``), render-time
substitution (``ctf.services.notification``), and the legacy-row cleanup
migration. It enforces a flat ``{{ name }}`` placeholder grammar over an
explicit per-notification-type allowlist of scalar values. Dotted attribute
access, filters, tags, comments, brackets, and unknown placeholders are all
rejected; substitution only ever emits pre-computed scalar strings.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ctf.enums import NotificationType

if TYPE_CHECKING:
    from collections.abc import Mapping

# Date format mirrors the trusted default templates' ``date:"F j, Y g:i A"``.
_DATE_FORMAT = "F j, Y g:i A"

# Flat placeholder grammar: ``{{ name }}`` where name is a simple identifier.
_PLACEHOLDER_RE = re.compile(r"{{\s*([a-z][a-z0-9_]*)\s*}}")
# Any ``{{ ... }}`` span, used to detect invalid inner content. The inner
# class excludes braces (rather than a lazy ``.*?``) so the pattern is linear
# on adversarial input like ``{{{{...`` (avoids py/polynomial-redos).
_ANY_PLACEHOLDER_RE = re.compile(r"{{([^{}]*)}}")
_VALID_NAME_RE = re.compile(r"[a-z][a-z0-9_]*")

_COMMON = frozenset({"event_name", "event_description", "event_start", "event_end"})
_PARTICIPANT = frozenset({"participant_name", "participant_email"})

# Explicit allowlist of scalar placeholder names per notification type. These
# correspond to the scalar values produced by :func:`build_safe_context` from
# the trusted render context of each notification flow.
ALLOWED_PLACEHOLDERS_BY_TYPE: dict[str, frozenset[str]] = {
    NotificationType.INVITE.value: _COMMON | _PARTICIPANT | frozenset({"registration_url"}),
    NotificationType.CREDENTIALS.value: _COMMON | _PARTICIPANT | frozenset({"access_url"}),
    NotificationType.REMINDER.value: _COMMON
    | _PARTICIPANT
    | frozenset({"access_url", "hours_before", "event_start_local", "event_timezone"}),
    NotificationType.ANNOUNCEMENT.value: _COMMON | _PARTICIPANT | frozenset({"subject", "body"}),
    NotificationType.PROVISION_FAILURE.value: _COMMON | frozenset({"failure_count"}),
    NotificationType.EVENT_START.value: _COMMON,
    NotificationType.EVENT_END.value: _COMMON,
}


def allowed_placeholders(notification_type: str) -> frozenset[str]:
    """Return the allowed placeholder names for a notification type.

    Fails closed: a notification type with no explicit entry gets an empty
    allowlist, so every type must make an intentional placeholder contract and
    a new type can never silently inherit another flow's placeholders.
    """
    return ALLOWED_PLACEHOLDERS_BY_TYPE.get(notification_type, frozenset())


def _placeholder_violations(body: str, allowed: frozenset[str]) -> list[str]:
    """Return violations for each ``{{ ... }}`` span found in *body*."""
    violations: list[str] = []
    for raw in _ANY_PLACEHOLDER_RE.findall(body):
        name = raw.strip()
        if not _VALID_NAME_RE.fullmatch(name):
            violations.append(
                "Only simple {{ name }} placeholders are allowed (no attribute access, filters, or expressions)."
            )
        elif name not in allowed:
            violations.append(f"Unknown placeholder {{{{ {name} }}}}.")
    return violations


def _dedupe(messages: list[str]) -> list[str]:
    """Return *messages* with duplicates removed, order preserved."""
    seen: set[str] = set()
    unique: list[str] = []
    for message in messages:
        if message not in seen:
            seen.add(message)
            unique.append(message)
    return unique


def find_template_violations(body: str, allowed: frozenset[str]) -> list[str]:
    """Return policy violations for a custom body (empty list = valid).

    Messages are fixed and body-safe: they never echo raw body content other
    than placeholder names that already match the flat-identifier grammar.
    """
    violations: list[str] = []
    if "{%" in body or "%}" in body:
        violations.append("Template tags ({% ... %}) are not allowed.")
    if "{#" in body or "#}" in body:
        violations.append("Template comments ({# ... #}) are not allowed.")
    violations.extend(_placeholder_violations(body, allowed))
    # Anything left after stripping valid spans means an unmatched delimiter.
    residual = _ANY_PLACEHOLDER_RE.sub("", body)
    if "{{" in residual or "}}" in residual:
        violations.append("Unbalanced template delimiters ({{ or }}).")
    return _dedupe(violations)


def build_safe_context(context: Mapping[str, object]) -> dict[str, str]:
    """Flatten a rich render context into scalar string placeholders only.

    Only an explicit set of known-safe scalar values is exposed; model
    objects (``CTFEvent``, ``CTFParticipant``, ``User``, …) are never passed
    through to the placeholder engine.
    """
    scalars: dict[str, str] = {}

    event = context.get("event")
    if event is not None:
        scalars["event_name"] = _as_text(getattr(event, "name", ""))
        scalars["event_description"] = _as_text(getattr(event, "description", ""))
        start = _format_date(getattr(event, "event_start", None))
        if start:
            scalars["event_start"] = start
        end = _format_date(getattr(event, "event_end", None))
        if end:
            scalars["event_end"] = end

    participant = context.get("participant")
    if participant is not None:
        scalars["participant_name"] = _as_text(getattr(participant, "name", ""))
        scalars["participant_email"] = _as_text(getattr(participant, "email", ""))

    for key in ("registration_url", "access_url", "event_timezone", "subject", "body"):
        value = context.get(key)
        if value is not None:
            scalars[key] = _as_text(value)

    hours_before = context.get("hours_before")
    if hours_before is not None:
        scalars["hours_before"] = _as_text(hours_before)

    local_start = _format_date(context.get("event_start_local"))
    if local_start:
        scalars["event_start_local"] = local_start

    failure_count = context.get("failure_count")
    if failure_count is not None:
        scalars["failure_count"] = _as_text(failure_count)

    return scalars


def render_safe_body(body: str, scalars: Mapping[str, str], *, escape: bool) -> str:
    """Substitute only allowlisted flat ``{{ name }}`` placeholders.

    Unknown placeholders render as the empty string. When ``escape`` is True
    (HTML bodies), substituted values are HTML-escaped to preserve the
    autoescaping the Django engine previously provided.
    """
    from django.utils.html import escape as html_escape

    def _replace(match: re.Match[str]) -> str:
        """Substitute one matched placeholder with its allowlisted scalar."""
        value = scalars.get(match.group(1), "")
        return html_escape(value) if escape else value

    return _PLACEHOLDER_RE.sub(_replace, body)


def _as_text(value: object) -> str:
    """Coerce a scalar value to a string (``None`` becomes ``""``)."""
    return "" if value is None else str(value)


def _format_date(value: object) -> str:
    """Format a date/datetime like the trusted default templates; else ``""``."""
    import datetime

    from django.template.defaultfilters import date as date_filter

    if isinstance(value, (datetime.date, datetime.datetime)):
        return date_filter(value, _DATE_FORMAT)
    return ""
