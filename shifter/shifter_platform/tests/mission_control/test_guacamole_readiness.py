"""Tests for the first-click readiness retry in get_guacamole_auth_token.

Issue #395: when Guacamole has just minted a JSON-auth session, the very next
client request can race with the token's internal propagation and the browser
gets redirected to the Guacamole login page. The broker retries the token
exchange a bounded number of times for transient classes of failure before
giving up.
"""

import json
import urllib.error
from io import BytesIO
from unittest.mock import patch

_FAKE_AUTH_TOKEN = "token123"


def _ok_response(auth_token: str = _FAKE_AUTH_TOKEN) -> BytesIO:
    """Build a urlopen()-style context-manager response payload."""
    return BytesIO(json.dumps({"authToken": auth_token}).encode("utf-8"))


class TestGetGuacamoleAuthTokenReadiness:
    """Bounded retry around the Guacamole /api/tokens exchange (issue #395)."""

    def test_first_attempt_success_does_not_sleep(self):
        from mission_control.guacamole import get_guacamole_auth_token

        with (
            patch("mission_control.guacamole.urllib.request.urlopen") as mock_open,
            patch("mission_control.guacamole.time.sleep") as mock_sleep,
        ):
            mock_open.return_value.__enter__.return_value = _ok_response()

            token = get_guacamole_auth_token("https://guac.example.com", "encrypted")

        assert token == "token123"
        assert mock_open.call_count == 1
        mock_sleep.assert_not_called()

    def test_retries_on_http_503_then_succeeds(self):
        from mission_control.guacamole import get_guacamole_auth_token

        flaky = urllib.error.HTTPError(
            url="https://guac.example.com/api/tokens",
            code=503,
            msg="Service Unavailable",
            hdrs=None,
            fp=None,
        )

        with (
            patch("mission_control.guacamole.urllib.request.urlopen") as mock_open,
            patch("mission_control.guacamole.time.sleep") as mock_sleep,
        ):
            ok = mock_open.return_value
            ok.__enter__.return_value = _ok_response()
            mock_open.side_effect = [flaky, ok]

            token = get_guacamole_auth_token(
                "https://guac.example.com",
                "encrypted",
                attempts=3,
                base_delay_ms=10,
            )

        assert token == "token123"
        assert mock_open.call_count == 2
        assert mock_sleep.call_count == 1

    def test_retries_on_urlerror_then_succeeds(self):
        from mission_control.guacamole import get_guacamole_auth_token

        with (
            patch("mission_control.guacamole.urllib.request.urlopen") as mock_open,
            patch("mission_control.guacamole.time.sleep"),
        ):
            ok = mock_open.return_value
            ok.__enter__.return_value = _ok_response()
            mock_open.side_effect = [
                urllib.error.URLError("Connection refused"),
                ok,
            ]

            token = get_guacamole_auth_token(
                "https://guac.example.com",
                "encrypted",
                attempts=3,
                base_delay_ms=10,
            )

        assert token == "token123"
        assert mock_open.call_count == 2

    def test_does_not_retry_on_http_400(self):
        import pytest

        from mission_control.guacamole import get_guacamole_auth_token

        non_retryable = urllib.error.HTTPError(
            url="https://guac.example.com/api/tokens",
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=None,
        )

        with (
            patch(
                "mission_control.guacamole.urllib.request.urlopen",
                side_effect=non_retryable,
            ) as mock_open,
            patch("mission_control.guacamole.time.sleep") as mock_sleep,
            pytest.raises(ValueError, match="Failed to get Guacamole auth token"),
        ):
            get_guacamole_auth_token(
                "https://guac.example.com",
                "encrypted",
                attempts=3,
                base_delay_ms=10,
            )

        assert mock_open.call_count == 1
        mock_sleep.assert_not_called()

    def test_raises_after_exhausting_attempts(self):
        import pytest

        from mission_control.guacamole import get_guacamole_auth_token

        with (
            patch(
                "mission_control.guacamole.urllib.request.urlopen",
                side_effect=urllib.error.URLError("Connection refused"),
            ) as mock_open,
            patch("mission_control.guacamole.time.sleep") as mock_sleep,
            pytest.raises(ValueError, match="Failed to connect to Guacamole"),
        ):
            get_guacamole_auth_token(
                "https://guac.example.com",
                "encrypted",
                attempts=3,
                base_delay_ms=5,
            )

        assert mock_open.call_count == 3
        assert mock_sleep.call_count == 2

    def test_exponential_backoff_between_attempts(self):
        import pytest

        from mission_control.guacamole import get_guacamole_auth_token

        with (
            patch(
                "mission_control.guacamole.urllib.request.urlopen",
                side_effect=urllib.error.URLError("Connection refused"),
            ),
            patch("mission_control.guacamole.time.sleep") as mock_sleep,
            pytest.raises(ValueError),
        ):
            get_guacamole_auth_token(
                "https://guac.example.com",
                "encrypted",
                attempts=4,
                base_delay_ms=200,
            )

        delays = [call.args[0] for call in mock_sleep.call_args_list]
        assert delays == [0.2, 0.4, 0.8]

    def test_settings_drive_defaults_when_kwargs_omitted(self, settings):
        import pytest

        from mission_control.guacamole import get_guacamole_auth_token

        settings.GUACAMOLE_TOKEN_RETRY_ATTEMPTS = 2
        settings.GUACAMOLE_TOKEN_RETRY_BASE_DELAY_MS = 5

        with (
            patch(
                "mission_control.guacamole.urllib.request.urlopen",
                side_effect=urllib.error.URLError("Connection refused"),
            ) as mock_open,
            patch("mission_control.guacamole.time.sleep") as mock_sleep,
            pytest.raises(ValueError),
        ):
            get_guacamole_auth_token("https://guac.example.com", "encrypted")

        assert mock_open.call_count == 2
        assert mock_sleep.call_count == 1
