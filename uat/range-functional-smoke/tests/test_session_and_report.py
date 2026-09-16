"""Credential handling, TOTP derivation, and evidence redaction."""

from __future__ import annotations

import os

import httpx
import pytest

from range_functional_smoke import report, session
from range_functional_smoke.profile import RunProfile
from range_functional_smoke.results import REQUIRED_CHECKS, CheckCode, RunResults, Status

# RFC 6238 appendix B reference secret ("12345678901234567890") in base32.
RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"


@pytest.fixture
def session_file(tmp_path):
    path = tmp_path / "session.key"
    path.write_text("abc123sessionkey", encoding="utf-8")
    path.chmod(0o600)
    return path


class TestTotp:
    @pytest.mark.parametrize(
        "at_time,expected",
        [(59, "287082"), (1111111109, "081804"), (1234567890, "005924"), (2000000000, "279037")],
    )
    def test_matches_rfc_6238_vectors(self, at_time, expected):
        assert session.totp_code(RFC_SECRET, at_time=at_time) == expected

    def test_accepts_spaced_lowercase_unpadded_secrets(self):
        spaced = " ".join(RFC_SECRET[i : i + 4] for i in range(0, len(RFC_SECRET), 4)).lower()
        assert session.totp_code(spaced, at_time=59) == "287082"

    def test_rejects_a_non_base32_secret(self):
        with pytest.raises(session.SessionError, match="base32"):
            session.totp_code("not!base32!", at_time=59)


class TestSessionFile:
    def test_reads_a_0600_file(self, session_file):
        assert session.load_session_cookie(str(session_file)) == "abc123sessionkey"

    @pytest.mark.parametrize("mode", [0o644, 0o660, 0o604])
    def test_refuses_a_group_or_world_readable_session(self, session_file, mode):
        os.chmod(session_file, mode)
        with pytest.raises(session.SessionError, match="chmod 600"):
            session.load_session_cookie(str(session_file))

    def test_refuses_an_empty_or_missing_file(self, tmp_path, session_file):
        session_file.write_text("   ", encoding="utf-8")
        with pytest.raises(session.SessionError, match="empty"):
            session.load_session_cookie(str(session_file))
        with pytest.raises(session.SessionError, match="not readable"):
            session.load_session_cookie(str(tmp_path / "absent"))


class TestCredentialSecrecy:
    def test_secret_fields_stay_out_of_repr(self):
        credential = session.Credential(
            email="qat@example.com", password="hunter2", totp_secret=RFC_SECRET, api_key="AIzaKEY"
        )
        rendered = repr(credential)
        for secret in ("hunter2", RFC_SECRET, "AIzaKEY", "qat@example.com"):
            assert secret not in rendered

    @pytest.mark.parametrize("missing", ["email", "password", "totp_secret", "api_key"])
    def test_incomplete_credentials_are_refused(self, missing):
        fields = {"email": "a@b.c", "password": "p", "totp_secret": RFC_SECRET, "api_key": "k"} | {missing: ""}
        with pytest.raises(session.SessionError, match=missing):
            session.Credential(**fields)


class TestTransportFailuresStayFailClosed:
    """A live target that cannot be reached must still produce a verdict.

    DNS failure, refused connection, TLS error, and read timeout are ordinary
    outcomes against a real deployment. If they escape as raw httpx exceptions
    they blow past the runner's SessionError boundary and the run dies with a
    traceback instead of a fail-closed report.
    """

    @pytest.mark.parametrize(
        "exc",
        [
            httpx.ConnectError("refused"),
            httpx.ConnectTimeout("timed out"),
            httpx.ReadTimeout("slow"),
            httpx.RemoteProtocolError("bad protocol"),
            OSError("dns"),
        ],
    )
    async def test_transport_errors_become_session_errors(self, exc):
        class Boom:
            async def request(self, *_args, **_kwargs):
                raise exc

        with pytest.raises(session.SessionError) as caught:
            await session._request(Boom(), "GET", "https://p.example.com/", label="login page")
        assert "could not reach the target" in str(caught.value)

    async def test_the_authored_message_leaks_no_url_or_credential(self):
        class Boom:
            async def request(self, *_args, **_kwargs):
                raise httpx.ConnectError("connection refused to https://secret.internal/?token=abc")

        with pytest.raises(session.SessionError) as caught:
            await session._request(Boom(), "POST", "https://secret.internal/", label="session exchange")
        rendered = str(caught.value)
        assert "secret.internal" not in rendered
        assert "token=abc" not in rendered


class TestReport:
    @pytest.fixture
    def profile(self):
        return RunProfile(origin="https://gcp.example.com", environment="gcp-dev")

    def test_passing_run_renders_a_pass_verdict(self, profile):
        results = RunResults()
        for code in REQUIRED_CHECKS:
            results.record(code, Status.PASSED, "ok")
        rendered = report.render(results, profile, run_id="abc123")
        assert "**PASS**" in rendered
        assert "`guacamole_session_connected` (required)" in rendered

    def test_missing_checks_are_named_as_failures(self, profile):
        results = RunResults()
        results.record(CheckCode.RANGE_OWNED_READY, Status.PASSED, "ok")
        rendered = report.render(results, profile, run_id="abc123")
        assert "**FAIL**" in rendered
        assert "never ran" in rendered
        assert "guacamole_session_connected" in rendered

    @pytest.mark.parametrize(
        "leak",
        [
            "sessionid=abc123",
            "token: eyJhbGciOi",
            "Bearer eyJhbGciOi",
            "password=hunter2",
            "host 10.50.2.3",
            "guest 192.168.1.7",
            "peer 172.16.0.9",
        ],
    )
    def test_redaction_covers_credential_material_and_private_addresses(self, leak):
        assert "[redacted]" in report.redact(leak)

    def test_public_identifiers_survive_redaction(self):
        text = "owned range 6 (polaris) is ready"
        assert report.redact(text) == text
