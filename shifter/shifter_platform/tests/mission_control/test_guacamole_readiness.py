"""Behavior tests for the first-click readiness retry in the Guacamole client.

Issue #395: when Guacamole has just minted a JSON-auth session, the very next
client request can race with the token's internal propagation and the browser
gets redirected to the Guacamole login page. ``JsonAuthGuacamoleClient`` retries
the token exchange a bounded number of times for transient classes of failure
before giving up. The retry policy comes from ``GuacamoleClientConfig`` — the
client never reads Django settings (issue #993).

The HTTP exchange is mocked at the real ``urllib`` boundary. ``time.sleep`` is
neutralised with a ``monkeypatch`` spy (a stdlib timing control, not a
first-party call-topology mock) that records the backoff delays so the retry
schedule can still be asserted without real waits.
"""

import json
import urllib.error
from io import BytesIO
from unittest.mock import patch

import pytest

_FAKE_AUTH_TOKEN = "token123"

URLOPEN = "mission_control.guacamole.urllib.request.urlopen"

# 32 hex chars = 16-byte AES-128 key (mirrors conftest.SECRET_KEY_128).
SECRET_KEY_128 = "0123456789abcdef0123456789abcdef"  # nosec B105  # NOSONAR


def _client(**config_overrides):
    """Build a client whose token exchange targets https://guac.example.com."""
    from mission_control.guacamole import GuacamoleClientConfig, JsonAuthGuacamoleClient

    defaults = {"base_url": "https://guac.example.com", "secret_key": SECRET_KEY_128}
    defaults.update(config_overrides)
    return JsonAuthGuacamoleClient(GuacamoleClientConfig(**defaults))


def _req():
    from mission_control.guacamole import GuacSSHUrlRequest

    return GuacSSHUrlRequest(username="u@example.com", connection_name="conn-1", hostname="10.1.5.10")


def _ok_response(auth_token: str = _FAKE_AUTH_TOKEN) -> BytesIO:
    """Build a urlopen()-style context-manager response payload."""
    return BytesIO(json.dumps({"authToken": auth_token}).encode("utf-8"))


def _http_error(code: int, msg: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url="https://guac.example.com/api/tokens", code=code, msg=msg, hdrs=None, fp=None)


@pytest.fixture
def sleeps(monkeypatch):
    """Record (and skip) the backoff sleeps performed by the client."""
    import mission_control.guacamole as guacamole

    recorded: list[float] = []
    monkeypatch.setattr(guacamole.time, "sleep", recorded.append)
    return recorded


class TestGuacamoleClientReadiness:
    """Bounded retry around the Guacamole /api/tokens exchange (issue #395)."""

    def test_first_attempt_success_does_not_sleep(self, sleeps):
        with patch(URLOPEN) as mock_open:
            mock_open.return_value.__enter__.return_value = _ok_response()
            url = _client().create_ssh_url(_req())

        assert "token=token123" in url
        assert mock_open.call_count == 1
        assert sleeps == []

    def test_retries_on_http_503_then_succeeds(self, sleeps):
        with patch(URLOPEN) as mock_open:
            ok = mock_open.return_value
            ok.__enter__.return_value = _ok_response()
            mock_open.side_effect = [_http_error(503, "Service Unavailable"), ok]

            url = _client(retry_attempts=3, retry_base_delay_ms=10).create_ssh_url(_req())

        assert "token=token123" in url
        assert mock_open.call_count == 2
        assert len(sleeps) == 1

    def test_retries_on_urlerror_then_succeeds(self, sleeps):
        with patch(URLOPEN) as mock_open:
            ok = mock_open.return_value
            ok.__enter__.return_value = _ok_response()
            mock_open.side_effect = [urllib.error.URLError("Connection refused"), ok]

            url = _client(retry_attempts=3, retry_base_delay_ms=10).create_ssh_url(_req())

        assert "token=token123" in url
        assert mock_open.call_count == 2

    def test_does_not_retry_on_http_400(self, sleeps):
        # Build client/request outside the raises block so it holds exactly one
        # possibly-throwing invocation (Sonar python:S5778).
        client = _client(retry_attempts=3, retry_base_delay_ms=10)
        req = _req()
        with (
            patch(URLOPEN, side_effect=_http_error(400, "Bad Request")) as mock_open,
            pytest.raises(ValueError, match="Failed to get Guacamole auth token"),
        ):
            client.create_ssh_url(req)

        assert mock_open.call_count == 1
        assert sleeps == []

    def test_raises_after_exhausting_attempts(self, sleeps):
        client = _client(retry_attempts=3, retry_base_delay_ms=5)
        req = _req()
        with (
            patch(URLOPEN, side_effect=urllib.error.URLError("Connection refused")) as mock_open,
            pytest.raises(ValueError, match="Failed to connect to Guacamole"),
        ):
            client.create_ssh_url(req)

        assert mock_open.call_count == 3
        assert len(sleeps) == 2

    def test_exponential_backoff_between_attempts(self, sleeps):
        client = _client(retry_attempts=4, retry_base_delay_ms=200)
        req = _req()
        with (
            patch(URLOPEN, side_effect=urllib.error.URLError("Connection refused")),
            pytest.raises(ValueError),
        ):
            client.create_ssh_url(req)

        assert sleeps == [0.2, 0.4, 0.8]

    def test_config_retry_policy_bounds_attempts(self, sleeps):
        """The retry count comes from client config, not Django settings."""
        client = _client(retry_attempts=2, retry_base_delay_ms=5)
        req = _req()
        with (
            patch(URLOPEN, side_effect=urllib.error.URLError("Connection refused")) as mock_open,
            pytest.raises(ValueError),
        ):
            client.create_ssh_url(req)

        assert mock_open.call_count == 2
        assert len(sleeps) == 1
