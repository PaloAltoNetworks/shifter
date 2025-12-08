"""Unit tests for Cognito pre-signup Lambda trigger."""

import os
import pytest
from unittest.mock import patch

from pre_signup import handler


@pytest.fixture(autouse=True)
def clear_env():
    """Clear environment variables before each test."""
    with patch.dict(os.environ, {}, clear=True):
        yield


def make_event(email):
    """Create a Cognito pre-signup event with the given email."""
    return {
        "request": {
            "userAttributes": {
                "email": email
            }
        }
    }


class TestHappyPath:
    """Tests for successful signups."""

    def test_allowed_domain(self):
        """Email with allowed domain should pass."""
        with patch.dict(os.environ, {"ALLOWED_DOMAINS": "paloaltonetworks.com"}):
            event = make_event("user@paloaltonetworks.com")
            result = handler(event, None)
            assert result == event

    def test_allowed_domain_case_insensitive(self):
        """Domain check should be case insensitive."""
        with patch.dict(os.environ, {"ALLOWED_DOMAINS": "paloaltonetworks.com"}):
            event = make_event("User@PaloAltoNetworks.COM")
            result = handler(event, None)
            assert result == event

    def test_allowed_email_explicit(self):
        """Explicitly allowed email should pass."""
        with patch.dict(os.environ, {"ALLOWED_EMAILS": "external@gmail.com"}):
            event = make_event("external@gmail.com")
            result = handler(event, None)
            assert result == event

    def test_allowed_email_case_insensitive(self):
        """Email allowlist check should be case insensitive."""
        with patch.dict(os.environ, {"ALLOWED_EMAILS": "External@Gmail.com"}):
            event = make_event("external@gmail.com")
            result = handler(event, None)
            assert result == event

    def test_multiple_allowed_domains(self):
        """Should work with multiple allowed domains."""
        with patch.dict(os.environ, {"ALLOWED_DOMAINS": "paloaltonetworks.com,example.com"}):
            event = make_event("user@example.com")
            result = handler(event, None)
            assert result == event

    def test_both_domains_and_emails_configured(self):
        """Should check both domains and explicit emails."""
        with patch.dict(os.environ, {
            "ALLOWED_DOMAINS": "paloaltonetworks.com",
            "ALLOWED_EMAILS": "external@gmail.com"
        }):
            # Domain match
            event1 = make_event("user@paloaltonetworks.com")
            assert handler(event1, None) == event1

            # Explicit email match
            event2 = make_event("external@gmail.com")
            assert handler(event2, None) == event2

    def test_email_with_whitespace_trimmed(self):
        """Leading/trailing whitespace in email should be trimmed."""
        with patch.dict(os.environ, {"ALLOWED_DOMAINS": "paloaltonetworks.com"}):
            event = make_event("  user@paloaltonetworks.com  ")
            result = handler(event, None)
            assert result == event


class TestDomainRejection:
    """Tests for domain-based rejections."""

    def test_disallowed_domain(self):
        """Email with non-allowed domain should be rejected."""
        with patch.dict(os.environ, {"ALLOWED_DOMAINS": "paloaltonetworks.com"}):
            event = make_event("user@gmail.com")
            with pytest.raises(Exception) as exc:
                handler(event, None)
            assert "not allowed" in str(exc.value)

    def test_empty_allowed_lists(self):
        """With no allowed domains/emails, all signups should be rejected."""
        with patch.dict(os.environ, {"ALLOWED_DOMAINS": "", "ALLOWED_EMAILS": ""}):
            event = make_event("user@paloaltonetworks.com")
            with pytest.raises(Exception) as exc:
                handler(event, None)
            assert "not allowed" in str(exc.value)

    def test_no_env_vars_set(self):
        """With no env vars, all signups should be rejected."""
        event = make_event("user@paloaltonetworks.com")
        with pytest.raises(Exception) as exc:
            handler(event, None)
        assert "not allowed" in str(exc.value)

    def test_subdomain_not_matched(self):
        """Subdomain should not match parent domain."""
        with patch.dict(os.environ, {"ALLOWED_DOMAINS": "paloaltonetworks.com"}):
            event = make_event("user@sub.paloaltonetworks.com")
            with pytest.raises(Exception) as exc:
                handler(event, None)
            assert "not allowed" in str(exc.value)


class TestInvalidEmail:
    """Tests for malformed email addresses."""

    def test_empty_email(self):
        """Empty email should be rejected."""
        event = make_event("")
        with pytest.raises(Exception) as exc:
            handler(event, None)
        assert "Invalid email" in str(exc.value)

    def test_no_at_symbol(self):
        """Email without @ should be rejected."""
        event = make_event("userpaloaltonetworks.com")
        with pytest.raises(Exception) as exc:
            handler(event, None)
        assert "Invalid email" in str(exc.value)

    def test_only_at_symbol(self):
        """Just @ should be rejected."""
        event = make_event("@")
        with pytest.raises(Exception) as exc:
            handler(event, None)
        assert "Invalid email" in str(exc.value)

    def test_empty_local_part(self):
        """Email with empty local part should be rejected."""
        event = make_event("@paloaltonetworks.com")
        with pytest.raises(Exception) as exc:
            handler(event, None)
        assert "Invalid email" in str(exc.value)

    def test_empty_domain(self):
        """Email with empty domain should be rejected."""
        event = make_event("user@")
        with pytest.raises(Exception) as exc:
            handler(event, None)
        assert "Invalid email" in str(exc.value)

    def test_multiple_at_symbols(self):
        """Email with multiple @ should be rejected."""
        event = make_event("user@domain@paloaltonetworks.com")
        with pytest.raises(Exception) as exc:
            handler(event, None)
        assert "Invalid email" in str(exc.value)

    def test_whitespace_only(self):
        """Whitespace-only email should be rejected."""
        event = make_event("   ")
        with pytest.raises(Exception) as exc:
            handler(event, None)
        assert "Invalid email" in str(exc.value)


class TestMalformedEvent:
    """Tests for malformed Cognito events."""

    def test_missing_request(self):
        """Event without request key should be handled."""
        event = {}
        with pytest.raises(Exception) as exc:
            handler(event, None)
        assert "Invalid email" in str(exc.value)

    def test_missing_user_attributes(self):
        """Event without userAttributes should be handled."""
        event = {"request": {}}
        with pytest.raises(Exception) as exc:
            handler(event, None)
        assert "Invalid email" in str(exc.value)

    def test_missing_email_attribute(self):
        """Event without email attribute should be handled."""
        event = {"request": {"userAttributes": {}}}
        with pytest.raises(Exception) as exc:
            handler(event, None)
        assert "Invalid email" in str(exc.value)

    def test_none_email(self):
        """None email should be handled."""
        event = {"request": {"userAttributes": {"email": None}}}
        with pytest.raises(Exception) as exc:
            handler(event, None)
        assert "Invalid email" in str(exc.value) or "Signup failed" in str(exc.value)


class TestEnvVarParsing:
    """Tests for environment variable parsing edge cases."""

    def test_whitespace_in_domain_list(self):
        """Whitespace around domains should be trimmed."""
        with patch.dict(os.environ, {"ALLOWED_DOMAINS": " paloaltonetworks.com , example.com "}):
            event = make_event("user@example.com")
            result = handler(event, None)
            assert result == event

    def test_empty_entries_in_list(self):
        """Empty entries in comma-separated list should be ignored."""
        with patch.dict(os.environ, {"ALLOWED_DOMAINS": "paloaltonetworks.com,,example.com,"}):
            event = make_event("user@example.com")
            result = handler(event, None)
            assert result == event

    def test_single_domain_no_comma(self):
        """Single domain without comma should work."""
        with patch.dict(os.environ, {"ALLOWED_DOMAINS": "paloaltonetworks.com"}):
            event = make_event("user@paloaltonetworks.com")
            result = handler(event, None)
            assert result == event
