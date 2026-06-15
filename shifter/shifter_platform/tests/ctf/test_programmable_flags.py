"""Tests for programmable and HTTP flag validation (CTF-118).

Tests the validator registry, programmable flag verification,
HTTP flag verification, and mixed flag type scenarios.
"""

from __future__ import annotations

import socket
from unittest.mock import MagicMock, patch

import pytest

from ctf.enums import ChallengeCategory, ChallengeDifficulty
from ctf.exceptions import CTFValidationError
from ctf.models import CTFChallenge, CTFFlag
from ctf.services.challenge import add_flag, verify_flag, verify_single_flag
from ctf.validators import (
    _VALIDATORS,
    get_validator,
    is_blocked_url,
    list_validators,
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


class TestValidatorRegistry:
    """Tests for the validator registry module."""

    def test_builtin_validators_registered(self):
        """Built-in validators are available by default."""
        names = list_validators()
        assert "always_true" in names
        assert "contains_substring" in names

    def test_register_and_get(self):
        """Register a validator and retrieve it."""

        def my_val(flag, params):
            return True

        register_validator("test_my_val", my_val)
        assert get_validator("test_my_val") is my_val
        _VALIDATORS.pop("test_my_val", None)

    def test_get_unknown_returns_none(self):
        """Getting an unregistered name returns None."""
        assert get_validator("nonexistent_validator_xyz") is None

    def test_list_validators_sorted(self):
        """list_validators returns sorted names."""
        names = list_validators()
        assert names == sorted(names)

    def test_always_true_validator(self):
        """The always_true built-in returns True for any input."""
        func = get_validator("always_true")
        assert func("anything", {}) is True
        assert func("", {}) is True

    def test_contains_substring_validator(self):
        """The contains_substring built-in checks for a substring."""
        func = get_validator("contains_substring")
        assert func("FLAG{hello_world}", {"substring": "hello"}) is True
        assert func("FLAG{hello_world}", {"substring": "missing"}) is False
        assert func("FLAG{hello_world}", {"substring": ""}) is False

    def test_contains_substring_case_insensitive(self):
        """contains_substring respects case_sensitive param."""
        func = get_validator("contains_substring")
        assert func("FLAG{Hello}", {"substring": "hello", "case_sensitive": False}) is True
        assert func("FLAG{Hello}", {"substring": "hello", "case_sensitive": True}) is False


class TestProgrammableFlagVerification:
    """Tests for programmable flag type verification."""

    def test_verify_programmable_flag_passes(self, draft_challenge, _custom_validator):
        """Programmable flag returns True when validator passes."""
        flag_obj = CTFFlag.objects.create(
            challenge=draft_challenge,
            flag_hash="programmable",
            flag_type="programmable",
            case_sensitive=True,
            order=0,
            validator_config={
                "validator_name": "test_checker",
                "params": {"expected": "correct_answer"},
            },
        )
        assert verify_single_flag(flag_obj, "correct_answer") is True

    def test_verify_programmable_flag_fails(self, draft_challenge, _custom_validator):
        """Programmable flag returns False when validator rejects."""
        flag_obj = CTFFlag.objects.create(
            challenge=draft_challenge,
            flag_hash="programmable",
            flag_type="programmable",
            case_sensitive=True,
            order=0,
            validator_config={
                "validator_name": "test_checker",
                "params": {"expected": "correct_answer"},
            },
        )
        assert verify_single_flag(flag_obj, "wrong_answer") is False

    def test_verify_programmable_unknown_validator(self, draft_challenge):
        """Programmable flag returns False for unknown validator name."""
        flag_obj = CTFFlag.objects.create(
            challenge=draft_challenge,
            flag_hash="programmable",
            flag_type="programmable",
            case_sensitive=True,
            order=0,
            validator_config={"validator_name": "does_not_exist"},
        )
        assert verify_single_flag(flag_obj, "anything") is False

    def test_verify_programmable_validator_exception(self, draft_challenge, _error_validator):
        """Programmable flag returns False when validator raises."""
        flag_obj = CTFFlag.objects.create(
            challenge=draft_challenge,
            flag_hash="programmable",
            flag_type="programmable",
            case_sensitive=True,
            order=0,
            validator_config={"validator_name": "test_boom"},
        )
        assert verify_single_flag(flag_obj, "anything") is False

    def test_verify_programmable_no_config(self, draft_challenge):
        """Programmable flag returns False when config is None."""
        flag_obj = CTFFlag.objects.create(
            challenge=draft_challenge,
            flag_hash="programmable",
            flag_type="programmable",
            case_sensitive=True,
            order=0,
            validator_config=None,
        )
        assert verify_single_flag(flag_obj, "anything") is False

    def test_verify_flag_challenge_with_programmable(self, draft_challenge):
        """verify_flag works with programmable flags on a challenge."""
        CTFFlag.objects.create(
            challenge=draft_challenge,
            flag_hash="programmable",
            flag_type="programmable",
            case_sensitive=True,
            order=0,
            validator_config={"validator_name": "always_true"},
        )
        assert verify_flag(draft_challenge, "anything") is True

    def test_add_flag_programmable_success(self, draft_challenge, _custom_validator):
        """add_flag creates a programmable flag with valid config."""
        flag_obj = add_flag(
            draft_challenge.id,
            {
                "flag_type": "programmable",
                "validator_config": {
                    "validator_name": "test_checker",
                    "params": {"expected": "answer"},
                },
            },
            actor_id=draft_challenge.event.created_by_id,
        )
        assert flag_obj.flag_type == "programmable"
        assert flag_obj.flag_hash == "programmable"
        assert flag_obj.validator_config["validator_name"] == "test_checker"

    def test_add_flag_programmable_missing_config(self, draft_challenge):
        """add_flag rejects programmable flag without validator_config."""
        with pytest.raises(CTFValidationError, match="validator_config is required"):
            add_flag(draft_challenge.id, {"flag_type": "programmable"}, actor_id=draft_challenge.event.created_by_id)

    def test_add_flag_programmable_missing_name(self, draft_challenge):
        """add_flag rejects programmable flag without validator_name."""
        with pytest.raises(CTFValidationError, match="validator_name is required"):
            add_flag(
                draft_challenge.id,
                {
                    "flag_type": "programmable",
                    "validator_config": {"params": {}},
                },
                actor_id=draft_challenge.event.created_by_id,
            )

    def test_add_flag_programmable_unknown_validator(self, draft_challenge):
        """add_flag rejects programmable flag with unknown validator."""
        with pytest.raises(CTFValidationError, match="Unknown validator"):
            add_flag(
                draft_challenge.id,
                {
                    "flag_type": "programmable",
                    "validator_config": {"validator_name": "no_such_validator"},
                },
                actor_id=draft_challenge.event.created_by_id,
            )


class TestHTTPFlagVerification:
    """Tests for HTTP flag type verification."""

    def test_validate_http_valid_true(self):
        """HTTP validator returns True on 200 with valid=true."""
        patcher, mock_conn = _patch_http_response(status=200, body=b'{"valid": true}')
        with _patch_dns("8.8.8.8"), patcher:
            result = validate_http("my_flag", {"url": "https://example.com/check"}, "challenge-1")

        assert result is True
        mock_conn.request.assert_called_once()

    def test_validate_http_valid_false(self):
        """HTTP validator returns False on 200 with valid=false."""
        patcher, _ = _patch_http_response(status=200, body=b'{"valid": false}')
        with _patch_dns("8.8.8.8"), patcher:
            result = validate_http("my_flag", {"url": "https://example.com/check"}, "challenge-1")

        assert result is False

    def test_validate_http_non_200(self):
        """HTTP validator returns False on non-200 status."""
        patcher, _ = _patch_http_response(status=500, body=b"")
        with _patch_dns("8.8.8.8"), patcher:
            result = validate_http("my_flag", {"url": "https://example.com/check"}, "challenge-1")

        assert result is False

    def test_validate_http_timeout(self):
        """HTTP validator returns False on timeout."""
        with (
            _patch_dns("8.8.8.8"),
            patch(
                "ctf.validators._build_https_connection",
                side_effect=TimeoutError("timed out"),
            ),
        ):
            result = validate_http("my_flag", {"url": "https://example.com/check"}, "challenge-1")

        assert result is False

    def test_validate_http_connection_error(self):
        """HTTP validator returns False on connection error."""
        with (
            _patch_dns("8.8.8.8"),
            patch(
                "ctf.validators._build_https_connection",
                side_effect=OSError("connection refused"),
            ),
        ):
            result = validate_http("my_flag", {"url": "https://example.com/check"}, "challenge-1")

        assert result is False

    def test_validate_http_missing_url(self):
        """HTTP validator returns False when URL is missing."""
        result = validate_http("my_flag", {}, "challenge-1")
        assert result is False

    def test_validate_http_get_method(self):
        """HTTP validator uses GET when configured."""
        patcher, mock_conn = _patch_http_response(status=200, body=b'{"valid": true}')
        with _patch_dns("8.8.8.8"), patcher:
            result = validate_http(
                "my_flag",
                {"url": "https://example.com/check", "method": "GET"},
                "challenge-1",
            )

        assert result is True
        mock_conn.request.assert_called_once()
        method_used = mock_conn.request.call_args.args[0]
        assert method_used == "GET"

    def test_validate_http_custom_headers(self):
        """HTTP validator passes custom headers."""
        patcher, mock_conn = _patch_http_response(status=200, body=b'{"valid": true}')
        with _patch_dns("8.8.8.8"), patcher:
            validate_http(
                "flag",
                {"url": "https://example.com/check", "headers": {"X-Api-Key": "secret"}},
                "c-1",
            )

        headers_sent = mock_conn.request.call_args.kwargs.get("headers", {})
        assert headers_sent.get("X-Api-Key") == "secret"

    def test_validate_http_timeout_capped(self):
        """HTTP validator caps timeout at MAX_HTTP_TIMEOUT."""
        patcher, _ = _patch_http_response(status=200, body=b'{"valid": true}')
        with _patch_dns("8.8.8.8"), patcher as mock_factory:
            validate_http(
                "flag",
                {"url": "https://example.com/check", "timeout": 999},
                "c-1",
            )

        # The factory is called with the (capped) timeout.
        timeout_arg = mock_factory.call_args.kwargs.get("timeout")
        assert timeout_arg == 30

    def test_verify_single_flag_http(self, draft_challenge):
        """verify_single_flag dispatches to HTTP validator."""
        flag_obj = CTFFlag.objects.create(
            challenge=draft_challenge,
            flag_hash="http",
            flag_type="http",
            case_sensitive=True,
            order=0,
            validator_config={"url": "https://example.com/validate"},
        )

        patcher, _ = _patch_http_response(status=200, body=b'{"valid": true}')
        with _patch_dns("8.8.8.8"), patcher:
            assert verify_single_flag(flag_obj, "my_flag") is True

    def test_verify_flag_challenge_with_http(self, draft_challenge):
        """verify_flag works with HTTP flags on a challenge."""
        CTFFlag.objects.create(
            challenge=draft_challenge,
            flag_hash="http",
            flag_type="http",
            case_sensitive=True,
            order=0,
            validator_config={"url": "https://example.com/validate"},
        )

        patcher, _ = _patch_http_response(status=200, body=b'{"valid": false}')
        with _patch_dns("8.8.8.8"), patcher:
            assert verify_flag(draft_challenge, "wrong") is False

    def test_add_flag_http_success(self, draft_challenge):
        """add_flag creates an HTTP flag with valid config."""
        flag_obj = add_flag(
            draft_challenge.id,
            {
                "flag_type": "http",
                "validator_config": {"url": "https://example.com/validate"},
            },
            actor_id=draft_challenge.event.created_by_id,
        )
        assert flag_obj.flag_type == "http"
        assert flag_obj.flag_hash == "http"
        assert flag_obj.validator_config["url"] == "https://example.com/validate"

    def test_add_flag_http_missing_config(self, draft_challenge):
        """add_flag rejects HTTP flag without validator_config."""
        with pytest.raises(CTFValidationError, match="validator_config is required"):
            add_flag(draft_challenge.id, {"flag_type": "http"}, actor_id=draft_challenge.event.created_by_id)

    def test_add_flag_http_missing_url(self, draft_challenge):
        """add_flag rejects HTTP flag without URL."""
        with pytest.raises(CTFValidationError, match="url is required"):
            add_flag(
                draft_challenge.id,
                {"flag_type": "http", "validator_config": {}},
                actor_id=draft_challenge.event.created_by_id,
            )

    def test_add_flag_http_rejects_non_https(self, draft_challenge):
        """add_flag rejects HTTP flag with non-HTTPS URL."""
        with pytest.raises(CTFValidationError, match="must use HTTPS"):
            add_flag(
                draft_challenge.id,
                {"flag_type": "http", "validator_config": {"url": "http://example.com/check"}},
                actor_id=draft_challenge.event.created_by_id,
            )

    def test_add_flag_http_rejects_ftp(self, draft_challenge):
        """add_flag rejects HTTP flag with FTP URL."""
        with pytest.raises(CTFValidationError, match="must use HTTPS"):
            add_flag(
                draft_challenge.id,
                {"flag_type": "http", "validator_config": {"url": "ftp://bad.com"}},
                actor_id=draft_challenge.event.created_by_id,
            )

    def test_add_flag_http_invalid_timeout(self, draft_challenge):
        """add_flag rejects HTTP flag with invalid timeout."""
        with pytest.raises(CTFValidationError, match="timeout must be an integer"):
            add_flag(
                draft_challenge.id,
                {
                    "flag_type": "http",
                    "validator_config": {"url": "https://ok.com", "timeout": 99},
                },
                actor_id=draft_challenge.event.created_by_id,
            )


class TestURLBlocklist:
    """Tests for SSRF protection via URL blocklist."""

    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1/check",
            "http://10.0.0.1/check",
            "http://172.16.0.1/check",
            "http://192.168.1.1/check",
            "http://169.254.169.254/latest/meta-data/",
            "http://localhost/check",
            "http://0.0.0.0/check",
            "http://metadata.google.internal/computeMetadata/v1/",
        ],
    )
    def test_blocked_urls(self, url):
        """Private, loopback, link-local, and metadata URLs are blocked."""
        assert is_blocked_url(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com/validate",
            "https://validator.my-company.com/api/check",
            "http://8.8.8.8/check",
        ],
    )
    def test_allowed_urls(self, url):
        """Public URLs are allowed."""
        assert is_blocked_url(url) is False

    def test_validate_http_blocks_private_url(self):
        """validate_http returns False for blocked URLs without making a request."""
        result = validate_http("flag", {"url": "http://169.254.169.254/"}, "c-1")
        assert result is False


class TestURLBlocklistCreation:
    """Tests for SSRF protection at flag creation time."""

    def test_add_flag_rejects_blocked_url(self, draft_challenge):
        """add_flag rejects HTTP flags targeting private addresses."""
        with pytest.raises(CTFValidationError, match="private or reserved"):
            add_flag(
                draft_challenge.id,
                {
                    "flag_type": "http",
                    "validator_config": {"url": "https://169.254.169.254/latest/"},
                },
                actor_id=draft_challenge.event.created_by_id,
            )
