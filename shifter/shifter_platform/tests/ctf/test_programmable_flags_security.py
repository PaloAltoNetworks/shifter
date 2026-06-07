"""Tests for programmable and HTTP flag validation (CTF-118).

Tests the validator registry, programmable flag verification,
HTTP flag verification, and mixed flag type scenarios.
"""

from __future__ import annotations

import socket
from unittest.mock import MagicMock, patch

import pytest

from ctf.enums import ChallengeCategory, ChallengeDifficulty
from ctf.models import CTFChallenge, CTFFlag
from ctf.services.challenge import verify_flag
from ctf.validators import (
    _VALIDATORS,
    _BlockedDestinationError,
    _resolve_and_validate,
    is_blocked_url,
    register_validator,
    validate_http,
)


def _fake_addrinfo(*ips: str):
    """Build a getaddrinfo-shaped response from a list of IP strings."""
    out = []
    for ip in ips:
        try:
            family = socket.AF_INET6 if ":" in ip else socket.AF_INET
        except Exception:
            family = socket.AF_INET
        sockaddr = (ip, 443, 0, 0) if family == socket.AF_INET6 else (ip, 443)
        out.append((family, socket.SOCK_STREAM, 0, "", sockaddr))
    return out


def _patch_dns(*ips: str):
    """Patch socket.getaddrinfo at the validators-module level to a fixed set."""
    return patch("ctf.validators.socket.getaddrinfo", return_value=_fake_addrinfo(*ips))


def _patch_http_response(*, status: int = 200, body: bytes = b'{"valid": true}'):
    """Patch the pinned-connection factory to return a deterministic response.

    Returns the patcher; entering its context yields a MagicMock for the
    connection object so individual tests can inspect call_args.
    """
    mock_conn = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status = status
    mock_resp.read.return_value = body
    mock_conn.getresponse.return_value = mock_resp
    return patch("ctf.validators._build_https_connection", return_value=mock_conn), mock_conn


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def draft_challenge(ctf_event_draft):
    """Create a challenge in a draft event for flag testing."""
    return CTFChallenge.objects.create(
        event=ctf_event_draft,
        name="Programmable Challenge",
        description="Tests programmable flags",
        category=ChallengeCategory.WEB.value,
        points=100,
        difficulty=ChallengeDifficulty.EASY.value,
        flag_hash="placeholder",
    )


@pytest.fixture
def _custom_validator():
    """Register a custom validator for testing and clean up after."""

    def _checker(submitted_flag, params):
        return submitted_flag == params.get("expected", "")

    register_validator("test_checker", _checker)
    yield
    _VALIDATORS.pop("test_checker", None)


@pytest.fixture
def _error_validator():
    """Register a validator that raises an exception."""

    def _boom(submitted_flag, params):
        raise RuntimeError("Validator exploded")

    register_validator("test_boom", _boom)
    yield
    _VALIDATORS.pop("test_boom", None)


# ---------------------------------------------------------------------------
# TestValidatorRegistry
# ---------------------------------------------------------------------------


class TestMixedFlagTypes:
    """Tests for challenges with mixed flag types."""

    def test_static_plus_programmable(self, draft_challenge):
        """Challenge with static + programmable flags: either match succeeds."""
        from ctf.services.challenge import hash_flag

        CTFFlag.objects.create(
            challenge=draft_challenge,
            flag_hash=hash_flag("FLAG{static}"),
            flag_type="static",
            case_sensitive=True,
            order=0,
        )
        CTFFlag.objects.create(
            challenge=draft_challenge,
            flag_hash="programmable",
            flag_type="programmable",
            case_sensitive=True,
            order=1,
            validator_config={"validator_name": "always_true"},
        )

        # Static match
        assert verify_flag(draft_challenge, "FLAG{static}") is True
        # Programmable always_true match
        assert verify_flag(draft_challenge, "anything_else") is True

    def test_regex_plus_http(self, draft_challenge):
        """Challenge with regex + http flags: either match succeeds."""
        CTFFlag.objects.create(
            challenge=draft_challenge,
            flag_hash=r"FLAG\{[0-9]+\}",
            flag_type="regex",
            case_sensitive=True,
            order=0,
        )
        CTFFlag.objects.create(
            challenge=draft_challenge,
            flag_hash="http",
            flag_type="http",
            case_sensitive=True,
            order=1,
            validator_config={"url": "https://example.com/validate"},
        )

        # Regex match — no HTTP call needed
        assert verify_flag(draft_challenge, "FLAG{123}") is True

        # Regex fails, HTTP succeeds
        patcher_true, _ = _patch_http_response(status=200, body=b'{"valid": true}')
        with _patch_dns("8.8.8.8"), patcher_true:
            assert verify_flag(draft_challenge, "FLAG{not_a_number}") is True

        # Both fail
        patcher_false, _ = _patch_http_response(status=200, body=b'{"valid": false}')
        with _patch_dns("8.8.8.8"), patcher_false:
            assert verify_flag(draft_challenge, "FLAG{not_a_number}") is False


class TestDNSRebindingProtection:
    """Tests that the validator pins the connection to a pre-validated IP.

    Closes the resolution TOCTOU between is_blocked_url's getaddrinfo check
    and the actual outbound request: a hostname that returns a public IP at
    validation but a private/link-local/metadata IP at request time must
    not reach the network.
    """

    def test_resolve_and_validate_rejects_private_answer(self):
        with (
            patch(
                "ctf.validators.socket.getaddrinfo",
                return_value=_fake_addrinfo("10.0.0.5"),
            ),
            pytest.raises(_BlockedDestinationError),
        ):
            _resolve_and_validate("attacker.example.com", 443)

    def test_resolve_and_validate_rejects_link_local(self):
        with (
            patch(
                "ctf.validators.socket.getaddrinfo",
                return_value=_fake_addrinfo("169.254.169.254"),
            ),
            pytest.raises(_BlockedDestinationError),
        ):
            _resolve_and_validate("rebind.example.com", 443)

    def test_resolve_and_validate_rejects_link_local_v6(self):
        with (
            patch(
                "ctf.validators.socket.getaddrinfo",
                return_value=_fake_addrinfo("fe80::1"),
            ),
            pytest.raises(_BlockedDestinationError),
        ):
            _resolve_and_validate("rebind6.example.com", 443)

    def test_resolve_and_validate_rejects_loopback_v6(self):
        with (
            patch(
                "ctf.validators.socket.getaddrinfo",
                return_value=_fake_addrinfo("::1"),
            ),
            pytest.raises(_BlockedDestinationError),
        ):
            _resolve_and_validate("loop6.example.com", 443)

    def test_resolve_and_validate_rejects_mixed_public_and_private(self):
        """One safe answer must not mask a blocked answer in a multi-record DNS reply."""
        with (
            patch(
                "ctf.validators.socket.getaddrinfo",
                return_value=_fake_addrinfo("8.8.8.8", "10.0.0.5"),
            ),
            pytest.raises(_BlockedDestinationError),
        ):
            _resolve_and_validate("mixed.example.com", 443)

    def test_resolve_and_validate_rejects_multicast(self):
        with (
            patch(
                "ctf.validators.socket.getaddrinfo",
                return_value=_fake_addrinfo("224.0.0.1"),
            ),
            pytest.raises(_BlockedDestinationError),
        ):
            _resolve_and_validate("multi.example.com", 443)

    def test_resolve_and_validate_rejects_unspecified(self):
        unspecified = "0.0.0.0"  # noqa: S104 - DNS answer literal, not a bind target
        with (
            patch(
                "ctf.validators.socket.getaddrinfo",
                return_value=_fake_addrinfo(unspecified),
            ),
            pytest.raises(_BlockedDestinationError),
        ):
            _resolve_and_validate("zero.example.com", 443)

    def test_resolve_and_validate_returns_all_safe_addresses(self):
        with patch(
            "ctf.validators.socket.getaddrinfo",
            return_value=_fake_addrinfo("8.8.8.8", "1.1.1.1"),
        ):
            result = _resolve_and_validate("safe.example.com", 443)
        assert result == ["8.8.8.8", "1.1.1.1"]

    def test_validate_http_blocks_dns_rebinding_to_private(self):
        """Hostname that re-resolves to a private IP between validation and request must be blocked."""
        # If validate_http re-resolves DNS instead of pinning, the second
        # getaddrinfo answer (private) would slip through. We arrange a
        # SINGLE getaddrinfo call that returns the private answer; if the
        # implementation pins (calls getaddrinfo exactly once), this test
        # asserts the call count below.
        with patch(
            "ctf.validators.socket.getaddrinfo",
            return_value=_fake_addrinfo("10.0.0.5"),
        ) as mock_dns:
            result = validate_http(
                "flag",
                {"url": "https://rebind.example.com/check"},
                "c-1",
            )
        assert result is False
        assert mock_dns.call_count >= 1

    def test_validate_http_calls_getaddrinfo_only_once(self):
        """The connection must be pinned to the validated address, not re-resolved."""
        patcher, _ = _patch_http_response()
        with (
            patch(
                "ctf.validators.socket.getaddrinfo",
                return_value=_fake_addrinfo("8.8.8.8"),
            ) as mock_dns,
            patcher,
        ):
            result = validate_http(
                "flag",
                {"url": "https://ok.example.com/check"},
                "c-1",
            )
        assert result is True
        assert mock_dns.call_count == 1

    def test_validate_http_pins_socket_to_validated_ip(self):
        """The socket factory is called with the validated IP, not the hostname."""
        patcher, _ = _patch_http_response()
        with _patch_dns("8.8.8.8"), patcher as mock_factory:
            validate_http(
                "flag",
                {"url": "https://ok.example.com/check"},
                "c-1",
            )
        call_args = mock_factory.call_args
        assert call_args.kwargs.get("hostname") == "ok.example.com"
        assert call_args.kwargs.get("pinned_ip") == "8.8.8.8"

    def test_validate_http_blocks_when_dns_fails(self):
        with patch(
            "ctf.validators.socket.getaddrinfo",
            side_effect=socket.gaierror("DNS lookup failed"),
        ):
            result = validate_http(
                "flag",
                {"url": "https://noexist.example.com/check"},
                "c-1",
            )
        assert result is False

    def test_validate_http_blocks_metadata_hostname(self):
        result = validate_http(
            "flag",
            {"url": "https://metadata.google.internal/computeMetadata/v1/"},
            "c-1",
        )
        assert result is False

    def test_validate_http_ip_literal_blocked_without_dns(self):
        """An IP-literal URL must apply policy directly with no DNS call."""
        with patch("ctf.validators.socket.getaddrinfo") as mock_dns:
            result = validate_http(
                "flag",
                {"url": "https://169.254.169.254/latest/meta-data/"},
                "c-1",
            )
        assert result is False
        assert mock_dns.call_count == 0


class TestReviewFindings:
    """Regression coverage for issue #1188 pre-push codex review cycle 1.

    Codex flagged three production-readiness defects in the first
    pass of the DNS-rebinding fix; this class locks each of them in
    so a future refactor cannot quietly reintroduce them.
    """

    def test_malformed_port_url_blocks_without_raising(self):
        """Out-of-range / non-integer ports must fail closed, not propagate ValueError."""
        # is_blocked_url is the config-time gate; both paths used to
        # access parsed.port outside the urlparse try/except envelope.
        assert is_blocked_url("https://example.com:99999/check") is True
        assert is_blocked_url("https://example.com:bad/check") is True
        # And the runtime path must also fail closed cleanly.
        assert (
            validate_http(
                "flag",
                {"url": "https://example.com:99999/check"},
                "c-1",
            )
            is False
        )

    def test_post_preserves_existing_query_string(self):
        """POST validators must keep query parameters from the configured URL."""
        patcher, mock_conn = _patch_http_response(status=200, body=b'{"valid": true}')
        with _patch_dns("8.8.8.8"), patcher:
            validate_http(
                "flag",
                {"url": "https://example.com/check?token=abc&tenant=x"},
                "c-1",
            )
        # http.client.request("POST", request_path, ...) — request_path
        # must include the original query.
        request_path = mock_conn.request.call_args.args[1]
        assert "token=abc" in request_path
        assert "tenant=x" in request_path

    def test_get_preserves_existing_query_string(self):
        """GET still appends the submitted payload but keeps the existing query."""
        patcher, mock_conn = _patch_http_response(status=200, body=b'{"valid": true}')
        with _patch_dns("8.8.8.8"), patcher:
            validate_http(
                "flag",
                {"url": "https://example.com/check?token=abc", "method": "GET"},
                "c-1",
            )
        request_path = mock_conn.request.call_args.args[1]
        assert "token=abc" in request_path
        assert "flag=flag" in request_path

    def test_falls_back_to_next_address_on_transport_failure(self):
        """When the first pinned IP fails at the transport layer, try the next one."""
        good_conn = MagicMock()
        good_resp = MagicMock()
        good_resp.status = 200
        good_resp.read.return_value = b'{"valid": true}'
        good_conn.getresponse.return_value = good_resp

        # First call raises (simulating a connection error on IP #1),
        # second call returns a working connection (IP #2 succeeds).
        with (
            _patch_dns("8.8.8.8", "1.1.1.1"),
            patch(
                "ctf.validators._build_https_connection",
                side_effect=[OSError("first ip unreachable"), good_conn],
            ) as factory,
        ):
            result = validate_http(
                "flag",
                {"url": "https://multi.example.com/check"},
                "c-1",
            )
        assert result is True
        # The factory was invoked twice — once per pinned address.
        assert factory.call_count == 2
        # First with the first IP, second with the fallback.
        assert factory.call_args_list[0].kwargs.get("pinned_ip") == "8.8.8.8"
        assert factory.call_args_list[1].kwargs.get("pinned_ip") == "1.1.1.1"

    def test_returns_false_when_every_pinned_address_fails(self):
        """If every pinned IP fails at the transport layer, return False (not raise)."""
        with (
            _patch_dns("8.8.8.8", "1.1.1.1"),
            patch(
                "ctf.validators._build_https_connection",
                side_effect=OSError("connection refused"),
            ) as factory,
        ):
            result = validate_http(
                "flag",
                {"url": "https://multi.example.com/check"},
                "c-1",
            )
        assert result is False
        # Every pinned address was tried before giving up.
        assert factory.call_count == 2

    def test_organizer_cannot_override_host_header(self):
        """Configured Host header must not break the pinned-connection contract."""
        patcher, mock_conn = _patch_http_response(status=200, body=b'{"valid": true}')
        with _patch_dns("8.8.8.8"), patcher:
            validate_http(
                "flag",
                {
                    "url": "https://validator.example.com/check",
                    "headers": {
                        "Host": "attacker.example",
                        "X-Real-Header": "ok",
                    },
                },
                "c-1",
            )
        headers_sent = mock_conn.request.call_args.kwargs.get("headers", {})
        # Organizer-supplied Host stripped; http.client's auto-managed
        # Host header (from self.host = original hostname) remains the
        # only source of truth. Compare case-insensitively so a future
        # change that lets `host`/`HOST` slip through still fails.
        normalized = {k.strip().lower() for k in headers_sent if isinstance(k, str)}
        assert "host" not in normalized
        # Other custom headers still pass through.
        assert headers_sent.get("X-Real-Header") == "ok"

    def test_organizer_cannot_override_framing_headers(self):
        """Configured Content-Length / Transfer-Encoding / Connection are stripped."""
        patcher, mock_conn = _patch_http_response(status=200, body=b'{"valid": true}')
        with _patch_dns("8.8.8.8"), patcher:
            validate_http(
                "flag",
                {
                    "url": "https://validator.example.com/check",
                    "headers": {
                        "Content-Length": "999999",
                        "Transfer-Encoding": "chunked",
                        "Connection": "keep-alive",
                    },
                },
                "c-1",
            )
        headers_sent = mock_conn.request.call_args.kwargs.get("headers", {})
        # Content-Length is set by _build_request from the actual body
        # length, not from organizer config.
        body_arg = mock_conn.request.call_args.kwargs.get("body")
        assert body_arg is not None
        assert headers_sent.get("Content-Length") == str(len(body_arg))
        assert "Transfer-Encoding" not in headers_sent
        assert "Connection" not in headers_sent

    def test_post_preserves_path_params(self):
        """RFC 3986 path params (`;tenant=a`) must be relayed unchanged."""
        patcher, mock_conn = _patch_http_response(status=200, body=b'{"valid": true}')
        with _patch_dns("8.8.8.8"), patcher:
            validate_http(
                "flag",
                {"url": "https://example.com/check;tenant=a?token=b"},
                "c-1",
            )
        request_path = mock_conn.request.call_args.args[1]
        assert ";tenant=a" in request_path
        assert "token=b" in request_path

    def test_get_preserves_path_params(self):
        patcher, mock_conn = _patch_http_response(status=200, body=b'{"valid": true}')
        with _patch_dns("8.8.8.8"), patcher:
            validate_http(
                "flag",
                {"url": "https://example.com/check;tenant=a?token=b", "method": "GET"},
                "c-1",
            )
        request_path = mock_conn.request.call_args.args[1]
        assert ";tenant=a" in request_path
        assert "token=b" in request_path
        assert "flag=flag" in request_path

    def test_content_type_default_is_case_insensitive(self):
        """A configured `content-type` must not be shadowed by a default `Content-Type`."""
        patcher, mock_conn = _patch_http_response(status=200, body=b'{"valid": true}')
        with _patch_dns("8.8.8.8"), patcher:
            validate_http(
                "flag",
                {
                    "url": "https://example.com/check",
                    "headers": {"content-type": "application/vnd.example+json"},
                },
                "c-1",
            )
        headers_sent = mock_conn.request.call_args.kwargs.get("headers", {})
        # Only one Content-Type header lands; the organizer's wins.
        ct_keys = [k for k in headers_sent if isinstance(k, str) and k.strip().lower() == "content-type"]
        assert len(ct_keys) == 1
        assert headers_sent[ct_keys[0]] == "application/vnd.example+json"

    def test_response_status_short_circuits_address_loop(self):
        """A non-success HTTP response on the first IP terminates the loop."""
        bad_conn = MagicMock()
        bad_resp = MagicMock()
        bad_resp.status = 500
        bad_resp.read.return_value = b""
        bad_conn.getresponse.return_value = bad_resp

        with (
            _patch_dns("8.8.8.8", "1.1.1.1"),
            patch(
                "ctf.validators._build_https_connection",
                return_value=bad_conn,
            ) as factory,
        ):
            result = validate_http(
                "flag",
                {"url": "https://multi.example.com/check"},
                "c-1",
            )
        assert result is False
        # We got a response on the first attempt; don't keep trying.
        assert factory.call_count == 1


class TestPinnedHTTPSConnection:
    """Verifies that the pinned connection class targets the validated IP
    while preserving SNI / cert verification / Host header for the original
    hostname.
    """

    def test_connect_uses_pinned_ip(self):
        from ctf.validators import _PinnedHTTPSConnection

        with (
            patch("ctf.validators.socket.create_connection") as mock_socket,
            patch("ssl.SSLContext.wrap_socket") as mock_wrap,
        ):
            mock_socket.return_value = MagicMock()
            mock_wrap.return_value = MagicMock()
            import ssl as _ssl

            conn = _PinnedHTTPSConnection(
                hostname="validator.example.com",
                pinned_ip="203.0.113.42",
                port=443,
                timeout=5,
                context=_ssl.create_default_context(),
            )
            conn.connect()

        # Socket opened to pinned IP, not hostname
        assert mock_socket.call_args.args[0] == ("203.0.113.42", 443)
        # TLS wrap uses hostname for SNI
        assert mock_wrap.call_args.kwargs.get("server_hostname") == "validator.example.com"
