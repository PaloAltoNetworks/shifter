"""Tests for the bounded CSP violation report collector (#1520, ADR-036-R3).

The collector is transport/observability plumbing: a same-origin, POST-only,
anonymous, CSRF-exempt endpoint that accepts standard browser report envelopes,
bounds and sanitizes attacker-controlled fields, emits one structured log event,
and returns fixed empty responses (204 accept / 4xx reject) with no error
envelope.
"""

from __future__ import annotations

import json
import logging

import pytest
from django.test import Client

from config import csp_report

REPORT_URL = "/security/csp-report/"

_LEGACY_REPORT = {
    "csp-report": {
        "document-uri": "https://portal.example.com/dashboard/?token=secret#frag",
        "blocked-uri": "https://evil.example.com/x.js?q=1",
        "effective-directive": "script-src",
        "violated-directive": "script-src 'self'",
        "disposition": "report",
        "status-code": 200,
        "line-number": 12,
        "column-number": 5,
    }
}

_REPORTS_JSON = [
    {
        "type": "csp-violation",
        "age": 10,
        "url": "https://portal.example.com/mission-control/",
        "body": {
            "documentURL": "https://portal.example.com/mission-control/?s=1",
            "blockedURL": "https://cdn.evil.example.com/a.js",
            "effectiveDirective": "connect-src",
            "disposition": "report",
            "statusCode": 200,
            "lineNumber": 3,
            "columnNumber": 9,
        },
    },
    {"type": "deprecation", "body": {"id": "ignored"}},
]


def _post(client: Client, payload, content_type: str):
    return client.post(REPORT_URL, data=json.dumps(payload), content_type=content_type)


@pytest.mark.django_db
def test_accepts_legacy_csp_report_returns_204():
    resp = _post(Client(), _LEGACY_REPORT, "application/csp-report")
    assert resp.status_code == 204
    assert resp.content == b""


@pytest.mark.django_db
def test_accepts_reports_json_batch_returns_204():
    resp = _post(Client(), _REPORTS_JSON, "application/reports+json")
    assert resp.status_code == 204
    assert resp.content == b""


@pytest.mark.django_db
def test_get_is_not_allowed():
    resp = Client().get(REPORT_URL)
    assert resp.status_code == 405


@pytest.mark.django_db
def test_unsupported_media_type_rejected():
    resp = _post(Client(), _LEGACY_REPORT, "application/json")
    assert resp.status_code == 415


@pytest.mark.django_db
def test_malformed_body_rejected():
    resp = Client().post(REPORT_URL, data="not-json{", content_type="application/csp-report")
    assert resp.status_code == 400


@pytest.mark.django_db
def test_oversized_body_rejected():
    huge = {"csp-report": {"document-uri": "https://portal.example.com/" + "a" * 40000}}
    resp = _post(Client(), huge, "application/csp-report")
    assert resp.status_code == 413


@pytest.mark.django_db
def test_is_csrf_exempt():
    # A CSRF-enforcing client with no token still reaches the view (204), proving
    # the collector is exempt (browsers post reports without a CSRF token).
    resp = Client(enforce_csrf_checks=True).post(
        REPORT_URL,
        data=json.dumps(_LEGACY_REPORT),
        content_type="application/csp-report",
    )
    assert resp.status_code == 204


@pytest.mark.django_db
def test_logs_sanitized_event_without_secrets(caplog):
    # The ``config`` logger sets propagate=False, so attach the capture handler
    # directly instead of relying on propagation to the root logger.
    csp_logger = logging.getLogger("config.csp_report")
    csp_logger.addHandler(caplog.handler)
    csp_logger.setLevel(logging.INFO)
    try:
        _post(Client(), _LEGACY_REPORT, "application/csp-report")
    finally:
        csp_logger.removeHandler(caplog.handler)
    records = [r for r in caplog.records if "csp" in r.getMessage().lower()]
    assert records, "expected a CSP violation log event"
    joined = " ".join(r.getMessage() for r in records)
    # Query string / fragment / raw path must be stripped from logged URLs.
    assert "token=secret" not in joined
    assert "#frag" not in joined
    assert "q=1" not in joined
    # The effective directive is retained for triage.
    assert "script-src" in joined


def test_sanitize_url_strips_query_fragment_and_credentials():
    out = csp_report._origin_and_path("https://user:pw@host.example.com:8443/a/b?secret=1#frag")
    assert "secret" not in out
    assert "#frag" not in out
    assert "user:pw" not in out
    assert out.startswith("https://host.example.com/a/b")


def test_sanitize_url_bounds_length():
    out = csp_report._origin_and_path("https://host.example.com/" + "a" * 5000)
    assert len(out) <= csp_report._MAX_FIELD_LEN
