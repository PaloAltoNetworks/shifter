"""Tests for utils.crypto helpers."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestGenerateRdpPassword:
    """generate_rdp_password yields unique, OS-portable passwords (#762)."""

    def test_returns_string_of_default_length(self):
        from utils.crypto import generate_rdp_password

        result = generate_rdp_password()
        assert isinstance(result, str)
        assert len(result) >= 24

    def test_calls_are_unique(self):
        from utils.crypto import generate_rdp_password

        # Two consecutive calls produce different passwords. This is a
        # probabilistic test but the collision odds for a 24+ char
        # alphanumeric password are negligible (~10^-43).
        assert generate_rdp_password() != generate_rdp_password()

    def test_uses_safe_character_set_for_chpasswd_and_net_user(self):
        # Characters excluded by design: backtick, single-quote,
        # double-quote, dollar, backslash, whitespace. These are
        # routinely a shell-escape minefield when piped through
        # ``chpasswd``/``net user`` or expanded inside cloud-init YAML.
        from utils.crypto import generate_rdp_password

        excluded = set("`'\"$\\ \t\n\r")
        # Sample several to reduce flake. With a 64-char alphabet and 24
        # characters, the probability of a single dangerous char appearing
        # would already be zero by construction.
        for _ in range(64):
            password = generate_rdp_password()
            assert not (excluded & set(password)), f"forbidden char in {password!r}"

    def test_honors_explicit_length(self):
        from utils.crypto import generate_rdp_password

        password = generate_rdp_password(length=40)
        assert len(password) == 40

    def test_always_contains_each_character_class(self):
        # Codex review cycle 1: Windows password policy needs all four
        # character classes. With a pure random sample a letters-only
        # or digits-only draw is rare but possible; the generator must
        # guarantee classes rather than sample-and-hope.
        import string

        from utils.crypto import _RDP_PASSWORD_PUNCTUATION, generate_rdp_password

        for _ in range(64):
            password = generate_rdp_password()
            assert any(c in string.ascii_uppercase for c in password), password
            assert any(c in string.ascii_lowercase for c in password), password
            assert any(c in string.digits for c in password), password
            assert any(c in _RDP_PASSWORD_PUNCTUATION for c in password), password

    def test_rejects_length_below_four_classes(self):
        from utils.crypto import generate_rdp_password

        with pytest.raises(ValueError, match="length must be >= 4"):
            generate_rdp_password(length=3)
