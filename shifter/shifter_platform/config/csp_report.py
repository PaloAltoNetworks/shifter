"""Bounded same-origin CSP violation report collector (ADR-036-R3).

Transport and observability plumbing, not a business API. A POST-only,
anonymous, narrowly CSRF-exempt endpoint (browsers post reports without an
application CSRF token) that accepts the legacy ``application/csp-report`` object
and the Reporting API ``application/reports+json`` batch, bounds and sanitizes
every attacker-controlled field, emits one structured event through the existing
ECS log pipeline, and returns fixed empty responses. It performs no
authenticated or domain mutation, has no model/repository/audit/outbox, and
never returns parser exceptions, report contents, or the platform error
envelope. See ``docs/architecture/browser-security-policy-preflight-1520.md``.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from shared.log_sanitize import safe_log_value

if TYPE_CHECKING:
    from django.http import HttpRequest

logger = logging.getLogger(__name__)

# Bounds. A CSP report is small; anything larger is discarded rather than parsed.
_MAX_BODY_BYTES = 16 * 1024
_MAX_REPORTS_PER_BATCH = 50
_MAX_FIELD_LEN = 512
_MAX_DIRECTIVE_LEN = 128
_MAX_DISPOSITION_LEN = 32

_LEGACY_MEDIA = "application/csp-report"
_REPORTS_MEDIA = "application/reports+json"
_ACCEPTED_MEDIA = frozenset({_LEGACY_MEDIA, _REPORTS_MEDIA})
_CSP_REPORT_TYPE = "csp-violation"


def _origin_and_path(raw: object) -> str:
    """Return a bounded ``scheme://host/path`` with query, fragment, and
    credentials stripped. Every URL field in a report is attacker-controlled."""
    if not isinstance(raw, str) or not raw:
        return ""
    parts = urlsplit(raw)
    has_origin = bool(parts.scheme and parts.hostname)
    base = f"{parts.scheme}://{parts.hostname}{parts.path}" if has_origin else (parts.path or raw)
    return base[:_MAX_FIELD_LEN]


def _field(raw: object, max_len: int) -> str:
    """Coerce a report field to a bounded string (drops non-scalars)."""
    if raw is None or isinstance(raw, (dict, list)):
        return ""
    return str(raw)[:max_len]


def _extract_report_batch(payload: object) -> list[dict[str, object]] | None:
    """Extract violation bodies from a Reporting API ``reports+json`` batch."""
    if not isinstance(payload, list):
        return None
    return [
        item["body"]
        for item in payload
        if isinstance(item, dict) and item.get("type") == _CSP_REPORT_TYPE and isinstance(item.get("body"), dict)
    ]


def _extract_reports(payload: object, content_type: str | None) -> list[dict[str, object]] | None:
    """Normalize either report envelope to a list of violation bodies.

    Returns ``None`` when the payload shape is not a recognized report envelope.
    """
    if content_type == _REPORTS_MEDIA:
        return _extract_report_batch(payload)
    # Legacy application/csp-report: {"csp-report": {...}}.
    if isinstance(payload, dict) and isinstance(payload.get("csp-report"), dict):
        return [payload["csp-report"]]
    return None


def _log_violation(request: HttpRequest, body: dict[str, object]) -> None:
    """Emit one bounded, sanitized ECS event for a single violation."""
    directive = _field(
        body.get("effective-directive") or body.get("effectiveDirective") or body.get("violated-directive"),
        _MAX_DIRECTIVE_LEN,
    )
    disposition = _field(body.get("disposition"), _MAX_DISPOSITION_LEN)
    blocked = _origin_and_path(body.get("blocked-uri") or body.get("blockedURL"))
    document = _origin_and_path(body.get("document-uri") or body.get("documentURL"))
    # Sanitize once and reuse for both the formatted message and the structured
    # ``extra`` fields: every value is attacker-controlled, and the ``extra``
    # sink reaches log output through the ECS pipeline just as the message does
    # (CodeQL ``py/log-injection``).
    safe_directive = safe_log_value(directive, _MAX_DIRECTIVE_LEN)
    safe_disposition = safe_log_value(disposition, _MAX_DISPOSITION_LEN)
    safe_blocked = safe_log_value(blocked, _MAX_FIELD_LEN)
    safe_document = safe_log_value(document, _MAX_FIELD_LEN)
    logger.info(
        "csp.violation directive=%s disposition=%s blocked=%s document=%s",
        safe_directive,
        safe_disposition,
        safe_blocked,
        safe_document,
        extra={
            "csp_directive": safe_directive,
            "csp_disposition": safe_disposition,
            "csp_blocked_origin": safe_blocked,
            "csp_document_origin": safe_document,
            "request": request,
        },
    )


def _rejection_status(request: HttpRequest) -> int | None:
    """Return an HTTP error status for an unacceptable request, else ``None``."""
    if request.content_type not in _ACCEPTED_MEDIA:
        return 415
    if len(request.body) > _MAX_BODY_BYTES:
        return 413
    return None


def _parse_reports(request: HttpRequest) -> list[dict[str, object]] | None:
    """Parse and normalize the report payload; ``None`` when malformed.

    ``UnicodeDecodeError`` is a subclass of ``ValueError``, so one clause covers
    both a bad UTF-8 body and invalid JSON.
    """
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except ValueError:
        return None
    return _extract_reports(payload, request.content_type)


# Anonymous report sink: browsers post CSP reports without a CSRF token and the
# view performs no authenticated or domain mutation (ADR-036-R3).
@csrf_exempt  # NOSONAR
@require_POST
def csp_report(request: HttpRequest) -> HttpResponse:
    """Accept and log a browser CSP violation report; return a fixed empty body."""
    rejection = _rejection_status(request)
    if rejection is not None:
        return HttpResponse(status=rejection)
    reports = _parse_reports(request)
    if reports is None:
        return HttpResponse(status=400)
    for body in reports[:_MAX_REPORTS_PER_BATCH]:
        _log_violation(request, body)
    return HttpResponse(status=204)
