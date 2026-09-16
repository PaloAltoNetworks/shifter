"""Tests for the staged browser security policy baseline (#1520, ADR-036).

Covers the code-owned CSP candidate shape, the validated report-only|enforce
mode seam, the global Referrer-Policy / Permissions-Policy / Reporting-Endpoints
values, and that real middleware responses carry the report-only headers on a
representative legacy view and the SPA host.
"""

from __future__ import annotations

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import Client
from django.utils.csp import CSP

from config import _browser_security as bs

_FORBIDDEN_SOURCES = frozenset(
    {
        str(CSP.UNSAFE_INLINE),
        str(CSP.UNSAFE_EVAL),
        str(CSP.UNSAFE_HASHES),
        "*",
        "http:",
        "https:",
        "data:",
    }
)


def _all_sources(candidate: dict) -> list[str]:
    sources: list[str] = []
    for values in candidate.values():
        sources.extend(str(v) for v in values)
    return sources


def test_candidate_is_deny_by_default():
    candidate = bs.build_browser_csp()
    for directive in (
        "default-src",
        "base-uri",
        "object-src",
        "frame-src",
        "media-src",
        "worker-src",
        "frame-ancestors",
        "script-src-attr",
        "style-src-attr",
    ):
        assert candidate[directive] == [CSP.NONE], directive


def test_candidate_has_no_unsafe_or_wildcard_sources():
    candidate = bs.build_browser_csp()
    # data: is permitted only for images; no other directive may carry it.
    for directive, values in candidate.items():
        rendered = {str(v) for v in values}
        forbidden = _FORBIDDEN_SOURCES - ({"data:"} if directive == "img-src" else set())
        assert not (rendered & forbidden), (directive, rendered & forbidden)


def test_candidate_scripts_and_styles_deny_attribute_variants():
    candidate = bs.build_browser_csp()
    assert candidate["script-src-attr"] == [CSP.NONE]
    assert candidate["style-src-attr"] == [CSP.NONE]
    # No nonce/unsafe-inline in report-only: inline debt is revealed, not allowed.
    assert CSP.NONCE not in candidate["script-src"]
    assert str(CSP.UNSAFE_INLINE) not in _all_sources(candidate)


def test_candidate_routes_reports_to_same_origin_collector():
    candidate = bs.build_browser_csp()
    assert candidate["report-uri"] == [bs.CSP_REPORT_PATH]
    assert candidate["report-to"] == ["csp"]
    assert bs.CSP_REPORT_PATH == "/security/csp-report/"


def test_candidate_allows_self_and_known_origins_only():
    candidate = bs.build_browser_csp()
    assert CSP.SELF in candidate["script-src"]
    assert CSP.SELF in candidate["connect-src"]
    # Every non-sentinel source is an exact https origin (or a bounded scheme).
    for directive in ("script-src", "style-src", "connect-src"):
        for value in candidate[directive]:
            text = str(value)
            if text in {str(CSP.SELF), str(CSP.NONE)}:
                continue
            assert text.startswith("https://"), (directive, text)


def test_storage_connect_origins_raises_for_unsupported_provider(monkeypatch):
    """A future third backend must fail closed rather than silently receiving the
    AWS S3 signed-upload CSP origins (the previous ``gcp ? gcs : aws`` shape
    treated any non-gcp value as AWS)."""
    monkeypatch.setattr(bs, "CLOUD_PROVIDER", "azure")

    with pytest.raises(ImproperlyConfigured, match="azure"):
        bs._storage_connect_origins()


def test_candidate_includes_each_required_dependency_origin():
    # Guard against a merge/refactor silently dropping a required origin: the
    # shape check above would still pass, but Identity Platform login or signed
    # uploads would break under enforcement.
    candidate = bs.build_browser_csp()
    assert bs._FIREBASE_SDK_ORIGIN in candidate["script-src"]
    for origin in bs._AUTH_API_ORIGINS:
        assert origin in candidate["connect-src"], origin
    storage_origins = bs._storage_connect_origins()
    assert storage_origins, "expected at least one signed-upload storage origin"
    for origin in storage_origins:
        assert origin in candidate["connect-src"], origin


def test_candidate_trusts_no_public_package_cdn():
    # ADR-036: jsDelivr/unpkg are self-hosted, so they must not be script/style
    # authorities. This is the codex-review guard against a promoted policy that
    # remains bypassable via attacker-published CDN packages.
    candidate = bs.build_browser_csp()
    banned = ("jsdelivr", "unpkg", "cdnjs")
    for directive in ("script-src", "style-src"):
        for value in candidate[directive]:
            text = str(value).lower()
            assert not any(host in text for host in banned), (directive, text)


def test_report_only_mode_selection():
    candidate = bs.build_browser_csp()
    enforce, report_only = bs.csp_settings_for_mode("report-only", candidate)
    assert enforce == {}
    assert report_only == candidate


def test_enforce_mode_selection():
    candidate = bs.build_browser_csp()
    enforce, report_only = bs.csp_settings_for_mode("enforce", candidate)
    assert enforce == candidate
    assert report_only == {}


def test_resolve_mode_is_case_insensitive_and_trimmed():
    assert bs.resolve_csp_mode("  ENFORCE ") == "enforce"
    assert bs.resolve_csp_mode("report-only") == "report-only"


def test_invalid_mode_raises_improperly_configured():
    with pytest.raises(ImproperlyConfigured):
        bs.resolve_csp_mode("audit")


def test_default_mode_is_report_only():
    assert bs.BROWSER_CSP_MODE == "report-only"
    assert bs.SECURE_CSP == {}
    assert bs.build_browser_csp() == bs.SECURE_CSP_REPORT_ONLY


def test_referrer_policy_is_explicit_same_origin():
    assert bs.SECURE_REFERRER_POLICY == "same-origin"


def test_permissions_policy_denies_capabilities_but_keeps_clipboard():
    for feature in ("camera", "microphone", "geolocation", "payment", "usb"):
        assert f"{feature}=()" in bs.PERMISSIONS_POLICY
    assert "clipboard" not in bs.PERMISSIONS_POLICY


def test_reporting_endpoints_header_points_at_collector():
    assert bs.REPORTING_ENDPOINTS_HEADER == 'csp="/security/csp-report/"'


@pytest.mark.django_db
def test_legacy_response_carries_report_only_headers():
    resp = Client().get("/privacy/")
    assert resp.status_code == 200
    assert "Content-Security-Policy-Report-Only" in resp.headers
    assert "Content-Security-Policy" not in resp.headers
    assert resp.headers["Referrer-Policy"] == "same-origin"
    assert resp.headers["Permissions-Policy"] == bs.PERMISSIONS_POLICY
    assert resp.headers["Reporting-Endpoints"] == bs.REPORTING_ENDPOINTS_HEADER


@pytest.mark.django_db
def test_spa_host_response_carries_report_only_headers(django_user_model):
    user = django_user_model.objects.create_user(username="op", email="op@example.com", password="pw", is_staff=True)
    client = Client()
    client.force_login(user)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Content-Security-Policy-Report-Only" in resp.headers
    assert resp.headers["Referrer-Policy"] == "same-origin"
    assert resp.headers["Permissions-Policy"] == bs.PERMISSIONS_POLICY
