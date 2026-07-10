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


class TestGenerateSshHostKeypair:
    """generate_ssh_host_keypair yields a cloud-init-installable Ed25519 host
    key plus a known_hosts-ready public key (D31)."""

    def test_returns_openssh_ed25519_private_and_public(self):
        from utils.crypto import generate_ssh_host_keypair

        private_key, public_key = generate_ssh_host_keypair()
        assert private_key.startswith("-----BEGIN OPENSSH PRIVATE KEY-----")
        assert private_key.rstrip().endswith("-----END OPENSSH PRIVATE KEY-----")
        assert public_key.startswith("ssh-ed25519 ")

    def test_public_key_matches_private_key(self):
        from cryptography.hazmat.primitives import serialization

        from utils.crypto import generate_ssh_host_keypair

        private_key, public_key = generate_ssh_host_keypair()
        loaded = serialization.load_ssh_private_key(private_key.encode(), password=None)
        derived = (
            loaded.public_key()
            .public_bytes(
                encoding=serialization.Encoding.OpenSSH,
                format=serialization.PublicFormat.OpenSSH,
            )
            .decode()
        )
        assert derived.strip() == public_key.strip()

    def test_calls_are_unique(self):
        from utils.crypto import generate_ssh_host_keypair

        first, _ = generate_ssh_host_keypair()
        second, _ = generate_ssh_host_keypair()
        assert first != second


class TestGenerateSshHostKeypairFailureModes:
    """Defensive error paths in generate_ssh_host_keypair."""

    class _FakePub:
        def __init__(self, pub):
            self._pub = pub

        def public_bytes(self, **_kwargs):
            return self._pub

    class _FakeKey:
        def __init__(self, priv, pub):
            self._priv = priv
            self._pub = pub

        def private_bytes(self, **_kwargs):
            return self._priv

        def public_key(self):
            return TestGenerateSshHostKeypairFailureModes._FakePub(self._pub)

    def test_raises_when_generation_fails(self, monkeypatch):
        import utils.crypto as crypto

        def _boom():
            raise RuntimeError("entropy pool exhausted")

        monkeypatch.setattr(crypto.ed25519.Ed25519PrivateKey, "generate", staticmethod(_boom))
        with pytest.raises(crypto.KeyGenerationError, match="Failed to generate"):
            crypto.generate_ssh_host_keypair()

    def test_raises_on_malformed_private_key(self, monkeypatch):
        import utils.crypto as crypto

        fake = self._FakeKey(b"NOT-A-PEM-KEY", b"ssh-ed25519 AAAApub")
        monkeypatch.setattr(crypto.ed25519.Ed25519PrivateKey, "generate", staticmethod(lambda: fake))
        with pytest.raises(crypto.KeyGenerationError, match="private key has unexpected format"):
            crypto.generate_ssh_host_keypair()

    def test_raises_on_malformed_public_key(self, monkeypatch):
        import utils.crypto as crypto

        fake = self._FakeKey(b"-----BEGIN OPENSSH PRIVATE KEY-----\nx\n", b"NOT-A-PUBKEY")
        monkeypatch.setattr(crypto.ed25519.Ed25519PrivateKey, "generate", staticmethod(lambda: fake))
        with pytest.raises(crypto.KeyGenerationError, match="public key has unexpected format"):
            crypto.generate_ssh_host_keypair()
