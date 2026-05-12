"""Cryptographic utilities for Shifter provisioner."""

import logging
import secrets
import string

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

logger = logging.getLogger(__name__)


# Character set for per-instance RDP passwords (#762). Built from
# ``string.ascii_letters``, ``string.digits``, and a hand-picked
# punctuation subset that round-trips safely through ``chpasswd`` stdin
# on Linux and ``net user <name> <pw>`` on Windows. Excludes backtick,
# single-quote, double-quote, dollar, backslash, and whitespace because
# those are the most common shell- and YAML-parsing minefields and
# provide no entropy benefit. Not itself a credential.
_RDP_PASSWORD_PUNCTUATION = "!#%&*+,-./:;<=>?@[]^_{|}~"  # noqa: S105  # nosec B105  # NOSONAR character set, not a credential
_RDP_PASSWORD_ALPHABET = string.ascii_letters + string.digits + _RDP_PASSWORD_PUNCTUATION


_RDP_PASSWORD_MIN_LENGTH = 4  # one character from each of four classes


def generate_rdp_password(length: int = 24) -> str:
    """Generate a cryptographically random per-instance RDP password.

    Guarantees one character from each of four classes (uppercase,
    lowercase, digit, shell-safe punctuation) before drawing the
    remainder from the full alphabet, so the password always satisfies
    Windows password policy. Used by the GDC VM Runtime provisioner
    (``_ensure_rdp_password_secret``); the AWS path uses Terraform's
    ``random_password`` resource with matching ``min_*`` constraints.
    """
    if length < _RDP_PASSWORD_MIN_LENGTH:
        raise ValueError(f"length must be >= {_RDP_PASSWORD_MIN_LENGTH}")
    required = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        secrets.choice(_RDP_PASSWORD_PUNCTUATION),
    ]
    extra = [secrets.choice(_RDP_PASSWORD_ALPHABET) for _ in range(length - len(required))]
    password_chars = required + extra
    # Cryptographic shuffle so the required characters don't always land
    # in the first four positions. ``random.shuffle`` is not crypto, so
    # build the shuffled order with ``secrets.choice``.
    out: list[str] = []
    remaining = list(password_chars)
    while remaining:
        i = secrets.randbelow(len(remaining))
        out.append(remaining.pop(i))
    return "".join(out)


class KeyGenerationError(Exception):
    """Raised when SSH key pair generation fails."""


def derive_ssh_public_key(private_key_pem: str) -> str:
    """Derive an OpenSSH public key from a PEM-encoded private key."""
    try:
        private_key = serialization.load_pem_private_key(private_key_pem.encode("utf-8"), password=None)
        public_key_openssh = (
            private_key.public_key()
            .public_bytes(
                encoding=serialization.Encoding.OpenSSH,
                format=serialization.PublicFormat.OpenSSH,
            )
            .decode("utf-8")
        )
    except Exception as e:
        logger.error("Failed to derive public key: %s", e)
        raise KeyGenerationError(f"Failed to derive SSH public key: {e}") from e

    if not public_key_openssh.startswith("ssh-rsa "):
        logger.error("Derived public key has unexpected format")
        raise KeyGenerationError("Derived public key has unexpected format")

    return public_key_openssh


def generate_ssh_keypair() -> tuple[str, str]:
    """Generate an RSA 4096-bit SSH key pair.

    Uses RSA for broad compatibility with SSH clients including Guacamole's
    libssh2 which doesn't support Ed25519.

    This is a pure Python operation with no AWS calls, safe to run at any time.

    Returns:
        tuple[str, str]: (private_key_pem, public_key_openssh) where:
            - private_key_pem: PEM-encoded private key
            - public_key_openssh: OpenSSH-format public key (ssh-rsa ...)

    Raises:
        KeyGenerationError: If key generation or serialization fails.
    """
    logger.debug("Generating RSA 4096-bit SSH key pair")

    try:
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=4096,
        )
    except Exception as e:
        logger.error("Failed to generate RSA private key: %s", e)
        raise KeyGenerationError(f"Failed to generate RSA private key: {e}") from e

    try:
        private_key_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("utf-8")
    except Exception as e:
        logger.error("Failed to serialize private key: %s", e)
        raise KeyGenerationError(f"Failed to serialize private key: {e}") from e

    try:
        public_key_openssh = derive_ssh_public_key(private_key_pem)
    except Exception as e:
        logger.error("Failed to serialize public key: %s", e)
        raise KeyGenerationError(f"Failed to serialize public key: {e}") from e

    # Validate generated keys have expected format
    if not private_key_pem.startswith("-----BEGIN RSA PRIVATE KEY-----"):
        logger.error("Generated private key has unexpected format")
        raise KeyGenerationError("Generated private key has unexpected format")

    if not public_key_openssh.startswith("ssh-rsa "):
        logger.error("Generated public key has unexpected format")
        raise KeyGenerationError("Generated public key has unexpected format")

    logger.debug("Successfully generated SSH key pair")
    return private_key_pem, public_key_openssh
