"""Fail-closed verdict composition and run-profile safety rules."""

from __future__ import annotations

import pytest

from range_functional_smoke.profile import (
    Deadlines,
    ProfileError,
    Protocol,
    RunProfile,
    is_loopback,
    reject_forbidden_keys,
    require_secure_url,
)
from range_functional_smoke.results import REQUIRED_CHECKS, CheckCode, RunResults, Status


def _all_passing() -> RunResults:
    results = RunResults()
    for code in REQUIRED_CHECKS:
        results.record(code, Status.PASSED, "ok")
    return results


class TestFailClosedVerdict:
    def test_every_required_check_passing_is_a_pass(self):
        assert _all_passing().passed

    def test_a_check_that_never_ran_is_not_a_pass(self):
        results = _all_passing()
        results.checks = [c for c in results.checks if c.code is not CheckCode.GUACAMOLE_SESSION_CONNECTED]
        assert not results.passed
        assert CheckCode.GUACAMOLE_SESSION_CONNECTED in results.missing()

    @pytest.mark.parametrize("status", [Status.FAILED, Status.BLOCKED, Status.SKIPPED, Status.TIMED_OUT, Status.ERROR])
    def test_no_non_passing_status_is_ever_a_pass(self, status):
        results = _all_passing()
        results.record(CheckCode.TERMINAL_NONCE_EXCHANGE, status, "not a pass")
        assert not results.passed
        assert results.verdict() == "fail"

    def test_bootstrap_success_without_a_connected_session_fails(self):
        """The headline rule: minting a credential is not a working Guacamole."""
        results = RunResults()
        for code in REQUIRED_CHECKS - {CheckCode.GUACAMOLE_SESSION_CONNECTED}:
            results.record(code, Status.PASSED, "ok")
        results.record(CheckCode.GUACAMOLE_SESSION_CONNECTED, Status.FAILED, "guacd never opened the session")
        assert not results.passed

    def test_a_retry_supersedes_the_earlier_attempt(self):
        results = _all_passing()
        results.record(CheckCode.TERMINAL_NONCE_EXCHANGE, Status.FAILED, "first attempt")
        assert not results.passed
        results.record(CheckCode.TERMINAL_NONCE_EXCHANGE, Status.PASSED, "retry succeeded")
        assert results.passed

    def test_detail_is_bounded_and_single_line(self):
        result = RunResults().record(CheckCode.RANGE_OWNED_READY, Status.FAILED, "a\nb\n" + "x" * 500)
        assert "\n" not in result.detail
        assert len(result.detail) <= 200


class TestProfileSafety:
    def test_valid_profile_normalises_origin_and_role(self):
        profile = RunProfile(origin="https://gcp.example.com/", environment="gcp-dev", target_role=" Attacker ")
        assert profile.origin == "https://gcp.example.com"
        assert profile.target_role == "attacker"
        assert profile.channel == "rdp"

    @pytest.mark.parametrize(
        "environment,origin",
        [
            ("prod", "https://portal.example.com"),
            ("gcp-prod", "https://portal.example.com"),
            ("anything", "https://portal.prod.example.com"),
            ("production", "https://portal.example.com"),
        ],
    )
    def test_production_looking_targets_are_refused_by_default(self, environment, origin):
        with pytest.raises(ProfileError, match="production"):
            RunProfile(origin=origin, environment=environment)

    def test_production_can_be_positively_selected(self):
        assert RunProfile(origin="https://portal.example.com", environment="prod", allow_production=True)

    @pytest.mark.parametrize("environment", ["gcp-dev", "dev", "staging", "reproduction-lab"])
    def test_non_production_environments_are_admitted(self, environment):
        assert RunProfile(origin="https://dev.example.com", environment=environment)

    @pytest.mark.parametrize(
        "origin",
        ["", "ftp://example.com", "https://", "https://example.com/portal", "https://example.com?a=1"],
    )
    def test_malformed_origins_are_refused(self, origin):
        with pytest.raises(ProfileError):
            RunProfile(origin=origin, environment="gcp-dev")

    def test_harness_never_destroys_an_operator_supplied_range(self):
        with pytest.raises(ProfileError, match="never destroys"):
            RunProfile(origin="https://dev.example.com", environment="gcp-dev", destroy_range=True)

    @pytest.mark.parametrize("bad", [{"host": "10.0.0.1"}, {"PASSWORD": "x"}, {"ssh_key": "..."}, {"port": 22}])
    def test_connection_material_is_rejected(self, bad):
        with pytest.raises(ProfileError, match="connection material"):
            reject_forbidden_keys(bad)

    def test_logical_selectors_are_allowed(self):
        reject_forbidden_keys({"target_role": "attacker", "protocol": "rdp", "environment": "gcp-dev"})

    @pytest.mark.parametrize("value", [0, -1])
    def test_deadlines_must_be_positive(self, value):
        with pytest.raises(ProfileError):
            Deadlines(run_seconds=value)


class TestTransportSecurity:
    """Credentials must never cross a network in plaintext.

    The harness carries a replayable ID token, a live session cookie (on HTTP
    *and* in the websocket handshake), and a signed Guacamole token in a tunnel
    query string. Any of them is stealable by a passive observer over http/ws.
    """

    def test_plaintext_origin_to_a_real_host_is_refused(self):
        with pytest.raises(ProfileError, match="plaintext"):
            RunProfile(origin="http://portal.example.com", environment="gcp-dev")

    def test_plaintext_is_refused_even_with_the_loopback_opt_in(self):
        """The opt-in is loopback-scoped; it is not a global downgrade switch."""
        with pytest.raises(ProfileError, match="plaintext"):
            RunProfile(origin="http://portal.example.com", environment="gcp-dev", allow_plaintext_loopback=True)

    @pytest.mark.parametrize("origin", ["http://localhost:8000", "http://127.0.0.1:18000"])
    def test_loopback_plaintext_allowed_only_behind_the_opt_in(self, origin):
        with pytest.raises(ProfileError, match="plaintext"):
            RunProfile(origin=origin, environment="local")
        assert RunProfile(origin=origin, environment="local", allow_plaintext_loopback=True)

    def test_https_needs_no_opt_in(self):
        assert RunProfile(origin="https://portal.example.com", environment="gcp-dev")

    @pytest.mark.parametrize(
        "url,ok",
        [
            ("https://p.example.com/guacamole", True),
            ("wss://p.example.com/guacamole", True),
            ("http://p.example.com/guacamole", False),
            ("ws://p.example.com/guacamole", False),
        ],
    )
    def test_secure_url_policy_covers_ws_as_well_as_http(self, url, ok):
        if ok:
            assert require_secure_url(url, what="x") == url
        else:
            with pytest.raises(ProfileError, match="plaintext"):
                require_secure_url(url, what="x")

    @pytest.mark.parametrize(
        "host,expected",
        [("localhost", True), ("127.0.0.1", True), ("::1", True), ("[::1]", True), ("example.com", False), ("", False)],
    )
    def test_loopback_detection(self, host, expected):
        assert is_loopback(host) is expected

    def test_protocol_selects_the_channel(self):
        profile = RunProfile(origin="https://dev.example.com", environment="gcp-dev", protocol=Protocol.SSH)
        assert profile.channel == "ssh"
