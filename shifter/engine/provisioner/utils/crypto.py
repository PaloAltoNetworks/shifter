"""Cryptographic utilities for Shifter provisioner."""

import logging

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

logger = logging.getLogger(__name__)


class KeyGenerationError(Exception):
    """Raised when SSH key pair generation fails."""


def generate_ssh_keypair() -> tuple[str, str]:
    """Generate an Ed25519 SSH key pair.

    This is a pure Python operation with no AWS calls, safe to run at any time.

    Returns:
        tuple[str, str]: (private_key_pem, public_key_openssh) where:
            - private_key_pem: PEM-encoded OpenSSH private key
            - public_key_openssh: OpenSSH-format public key (ssh-ed25519 ...)

    Raises:
        KeyGenerationError: If key generation or serialization fails.
    """
    logger.debug("Generating Ed25519 SSH key pair")

    try:
        private_key = ed25519.Ed25519PrivateKey.generate()
    except Exception as e:
        logger.error("Failed to generate Ed25519 private key: %s", e)
        raise KeyGenerationError(f"Failed to generate Ed25519 private key: {e}") from e

    try:
        private_key_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.OpenSSH,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("utf-8")
    except Exception as e:
        logger.error("Failed to serialize private key: %s", e)
        raise KeyGenerationError(f"Failed to serialize private key: {e}") from e

    try:
        public_key_openssh = (
            private_key.public_key()
            .public_bytes(
                encoding=serialization.Encoding.OpenSSH,
                format=serialization.PublicFormat.OpenSSH,
            )
            .decode("utf-8")
        )
    except Exception as e:
        logger.error("Failed to serialize public key: %s", e)
        raise KeyGenerationError(f"Failed to serialize public key: {e}") from e

    # Validate generated keys have expected format
    if not private_key_pem.startswith("-----BEGIN OPENSSH PRIVATE KEY-----"):
        logger.error("Generated private key has unexpected format")
        raise KeyGenerationError("Generated private key has unexpected format")

    if not public_key_openssh.startswith("ssh-ed25519 "):
        logger.error("Generated public key has unexpected format")
        raise KeyGenerationError("Generated public key has unexpected format")

    logger.debug("Successfully generated SSH key pair")
    return private_key_pem, public_key_openssh
