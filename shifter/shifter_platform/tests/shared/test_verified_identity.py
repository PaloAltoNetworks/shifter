"""Tests for the provider-neutral verified-identity contract (issue #1521).

``VerifiedIdentity`` is the single seam both production auth providers
(Cognito/OIDC and GCP Identity Platform) converge on before a login may bind
or change bootstrap-admin flags. These tests exercise the constructor
directly (no Django, no provider boundary) to prove the strict validation
rules: non-blank issuer/subject/email, and ``email_verified`` accepted only
as the Python literal ``True`` -- never coerced with ``bool(...)``.
"""

from __future__ import annotations

import pytest

from shared.verified_identity import VerifiedIdentity, VerifiedIdentityError


def _kwargs(**overrides):
    base = {
        "issuer": "https://issuer.example.test",
        "subject": "sub-123",
        "email": "user@example.com",
        "email_verified": True,
    }
    base.update(overrides)
    return base


class TestVerifiedIdentityValidConstruction:
    def test_accepts_fully_verified_evidence(self):
        identity = VerifiedIdentity(**_kwargs())
        assert identity.issuer == "https://issuer.example.test"
        assert identity.subject == "sub-123"
        assert identity.email == "user@example.com"
        assert identity.email_verified is True
        assert identity.source == ""

    def test_source_defaults_to_empty_and_is_settable(self):
        identity = VerifiedIdentity(**_kwargs(source="oidc"))
        assert identity.source == "oidc"

    def test_is_frozen(self):
        identity = VerifiedIdentity(**_kwargs())
        with pytest.raises(AttributeError):
            identity.email = "other@example.com"


class TestVerifiedIdentityRejectsBlankFields:
    @pytest.mark.parametrize("value", [None, "", "   "], ids=["none", "empty", "whitespace"])
    def test_rejects_blank_issuer(self, value):
        kwargs = _kwargs(issuer=value)
        with pytest.raises(VerifiedIdentityError):
            VerifiedIdentity(**kwargs)

    @pytest.mark.parametrize("value", [None, "", "   "], ids=["none", "empty", "whitespace"])
    def test_rejects_blank_subject(self, value):
        kwargs = _kwargs(subject=value)
        with pytest.raises(VerifiedIdentityError):
            VerifiedIdentity(**kwargs)

    @pytest.mark.parametrize("value", [None, "", "   "], ids=["none", "empty", "whitespace"])
    def test_rejects_blank_email(self, value):
        kwargs = _kwargs(email=value)
        with pytest.raises(VerifiedIdentityError):
            VerifiedIdentity(**kwargs)

    def test_rejects_non_string_issuer(self):
        kwargs = _kwargs(issuer=123)
        with pytest.raises(VerifiedIdentityError):
            VerifiedIdentity(**kwargs)


class TestVerifiedIdentityRejectsNonLiteralTrueEmailVerified:
    """Never ``bool(...)`` coerce -- only the literal ``True`` passes."""

    @pytest.mark.parametrize(
        "value",
        [None, False, "false", "true", "True", 0, 1],
        ids=["none", "false", "str-false", "str-true", "str-True", "int-0", "int-1"],
    )
    def test_rejects_non_literal_true(self, value):
        kwargs = _kwargs(email_verified=value)
        with pytest.raises(VerifiedIdentityError):
            VerifiedIdentity(**kwargs)

    def test_verified_identity_error_is_a_value_error(self):
        assert issubclass(VerifiedIdentityError, ValueError)
