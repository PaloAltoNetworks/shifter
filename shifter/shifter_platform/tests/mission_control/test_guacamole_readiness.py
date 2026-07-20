"""Behavior tests for the first-click readiness retry in get_guacamole_auth_token.

Issue #395: when Guacamole has just minted a JSON-auth session, the very next
client request can race with the token's internal propagation and the browser
gets redirected to the Guacamole login page. The broker retries the token
exchange a bounded number of times for transient classes of failure before
giving up.

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


def _ok_response(auth_token: str = _FAKE_AUTH_TOKEN) -> BytesIO:
    """Build a urlopen()-style context-manager response payload."""
    return BytesIO(json.dumps({"authToken": auth_token}).encode("utf-8"))


def _http_error(code: int, msg: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url="https://guac.example.com/api/tokens", code=code, msg=msg, hdrs=None, fp=None)


@pytest.fixture
def sleeps(monkeypatch):
    """Record (and skip) the backoff sleeps performed by the broker."""
    import mission_control.guacamole as guacamole

    recorded: list[float] = []
    monkeypatch.setattr(guacamole.time, "sleep", recorded.append)
    return recorded


class TestGetGuacamoleAuthTokenReadiness:
    """Bounded retry around the Guacamole /api/tokens exchange (issue #395)."""

    def test_first_attempt_success_does_not_sleep(self, sleeps):
        from mission_control.guacamole import get_guacamole_auth_token

        with patch(URLOPEN) as mock_open:
            mock_open.return_value.__enter__.return_value = _ok_response()
            token = get_guacamole_auth_token("https://guac.example.com", "encrypted")

        assert token == "token123"
        assert mock_open.call_count == 1
        assert sleeps == []

    def test_retries_on_http_503_then_succeeds(self, sleeps):
        from mission_control.guacamole import get_guacamole_auth_token

        with patch(URLOPEN) as mock_open:
            ok = mock_open.return_value
            ok.__enter__.return_value = _ok_response()
            mock_open.side_effect = [_http_error(503, "Service Unavailable"), ok]

            token = get_guacamole_auth_token("https://guac.example.com", "encrypted", attempts=3, base_delay_ms=10)

        assert token == "token123"
        assert mock_open.call_count == 2
        assert len(sleeps) == 1

    def test_retries_on_urlerror_then_succeeds(self, sleeps):
        from mission_control.guacamole import get_guacamole_auth_token

        with patch(URLOPEN) as mock_open:
            ok = mock_open.return_value
            ok.__enter__.return_value = _ok_response()
            mock_open.side_effect = [urllib.error.URLError("Connection refused"), ok]

            token = get_guacamole_auth_token("https://guac.example.com", "encrypted", attempts=3, base_delay_ms=10)

        assert token == "token123"
        assert mock_open.call_count == 2

    def test_does_not_retry_on_http_400(self, sleeps):
        from mission_control.guacamole import get_guacamole_auth_token

        with (
            patch(URLOPEN, side_effect=_http_error(400, "Bad Request")) as mock_open,
            pytest.raises(ValueError, match="Failed to get Guacamole auth token"),
        ):
            get_guacamole_auth_token("https://guac.example.com", "encrypted", attempts=3, base_delay_ms=10)

        assert mock_open.call_count == 1
        assert sleeps == []

    def test_raises_after_exhausting_attempts(self, sleeps):
        from mission_control.guacamole import get_guacamole_auth_token

        with (
            patch(URLOPEN, side_effect=urllib.error.URLError("Connection refused")) as mock_open,
            pytest.raises(ValueError, match="Failed to connect to Guacamole"),
        ):
            get_guacamole_auth_token("https://guac.example.com", "encrypted", attempts=3, base_delay_ms=5)

        assert mock_open.call_count == 3
        assert len(sleeps) == 2

    def test_exponential_backoff_between_attempts(self, sleeps):
        from mission_control.guacamole import get_guacamole_auth_token

        with (
            patch(URLOPEN, side_effect=urllib.error.URLError("Connection refused")),
            pytest.raises(ValueError),
        ):
            get_guacamole_auth_token("https://guac.example.com", "encrypted", attempts=4, base_delay_ms=200)

        assert sleeps == [0.2, 0.4, 0.8]

    def test_settings_drive_defaults_when_kwargs_omitted(self, settings, sleeps):
        from mission_control.guacamole import get_guacamole_auth_token

        settings.GUACAMOLE_TOKEN_RETRY_ATTEMPTS = 2
        settings.GUACAMOLE_TOKEN_RETRY_BASE_DELAY_MS = 5

        with (
            patch(URLOPEN, side_effect=urllib.error.URLError("Connection refused")) as mock_open,
            pytest.raises(ValueError),
        ):
            get_guacamole_auth_token("https://guac.example.com", "encrypted")

        assert mock_open.call_count == 2
        assert len(sleeps) == 1
