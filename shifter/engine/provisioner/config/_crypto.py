"""Crypto/provider primitives: field decryption, presigned URLs, and cloud-provider resolution.

Leaf module: depends only on stdlib, ``cryptography``, and lazy (function-local)
imports of ``installation``/``cloud`` to avoid import-time cost and circular
imports back into this package.
"""

import base64
import logging
import os
import sys
from collections.abc import Mapping
from pathlib import Path

from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

# Invocation names that signal a dev/test/build tooling context (mirrors
# ``config._runtime_env._TOOLING_INVOKERS`` on the Django side).
_DEV_DEFAULT_TOOLING_INVOKERS = frozenset({"pytest", "mypy", "dmypy"})


def _allow_dev_defaults(source: Mapping[str, str]) -> bool:
    """Return True when ``CLOUD_PROVIDER`` may fall back to the historical default.

    Mirrors ``config._runtime_env.runtime_allows_dev_defaults`` on the Django
    side exactly, so the provisioner and Django agree on when a missing
    backend selection may default rather than fail closed, without importing
    Django or duplicating a second policy definition here. Note that
    ``ENVIRONMENT=development``/``dev`` is deliberately NOT one of these
    signals: a deployed dev provisioner must still receive ``CLOUD_PROVIDER``
    explicitly (see docs/architecture/root-configured-backend-bundles.md,
    "Runtime Binding").
    """
    return (
        source.get("TESTING") == "1"
        or Path(sys.argv[0]).name in _DEV_DEFAULT_TOOLING_INVOKERS
        or source.get("ENVIRONMENT", "").strip().lower() == "build"
        or source.get("DJANGO_DEBUG", "").strip().lower() == "true"
    )


def resolve_cloud_provider(env: Mapping[str, str] | None = None) -> str:
    """Return the validated active cloud backend for this process (PLAT-2005).

    ``CLOUD_PROVIDER`` is the deploy-time projection of the selected
    installation backend, delivered to every consuming process role (see
    docs/architecture/root-configured-backend-bundles.md, "Runtime Binding").
    This is the provisioner's single resolution point: normalize to
    lowercase and validate against the ``installation`` registry -- the
    single source of truth for supported backends -- rather than re-reading
    the environment with an implicit ``aws`` default at every call site.

    Fails closed with ``CloudProviderNotImplementedError`` when the value is
    missing in a deployed process (the historical ``aws`` default is allowed
    only under ``_allow_dev_defaults``) or names an unsupported backend, so a
    misconfigured deploy cannot silently behave as AWS.
    """
    # Lazy imports: ``installation.registry`` pulls in pydantic, and
    # ``cloud.exceptions`` would otherwise import this module back (``cloud``
    # resolves its own provider through this function) -- both stay
    # function-local to avoid import-time cost and a circular import.
    from installation.registry import KNOWN_BACKENDS

    from cloud.exceptions import CloudProviderNotImplementedError

    source = env if env is not None else os.environ
    raw = source.get("CLOUD_PROVIDER", "").strip().lower()
    if not raw:
        if not _allow_dev_defaults(source):
            raise CloudProviderNotImplementedError("")
        raw = "aws"
    if raw not in KNOWN_BACKENDS:
        raise CloudProviderNotImplementedError(raw)
    return raw


class FieldDecryptError(RuntimeError):
    """Raised when an encrypted field cannot be decrypted.

    Fail-closed (#1189): the provisioner refuses to continue with
    ciphertext or malformed values silently. Callers that catch this
    error must decide explicitly whether to abort the request or fall
    back to a documented test/local plaintext mode — the function
    itself never returns the raw input on failure.
    """


def decrypt_field(encrypted_value: str) -> str:
    """Decrypt a Fernet-encrypted field value.

    Used for sensitive fields that are encrypted at rest in the Django
    database using django-encrypted-model-fields. Fail-closed: any
    decryption failure raises ``FieldDecryptError`` rather than
    silently returning the input. Exception messages never include
    the input value.

    Args:
        encrypted_value: Base64-url-encoded Fernet ciphertext.

    Returns:
        Decrypted plaintext string. Empty input returns ``""`` as the
        "no field present" sentinel.

    Raises:
        FieldDecryptError: ``FIELD_ENCRYPTION_KEY`` is missing for a
            non-empty input; input is not valid base64-url; the Fernet
            token is malformed; the key is wrong; or any other decrypt
            failure.
    """
    if not encrypted_value:
        return ""

    key = os.environ.get("FIELD_ENCRYPTION_KEY")
    if not key:
        # Drift signal: caller supplied an encrypted-looking value but
        # the encryption key isn't configured. The previous behavior
        # (pass-through) hid mis-configured secret flows; refuse instead.
        raise FieldDecryptError("FIELD_ENCRYPTION_KEY is not set; cannot decrypt provisioner field")

    try:
        fernet = Fernet(key.encode() if isinstance(key, str) else key)
        encrypted_bytes = base64.urlsafe_b64decode(encrypted_value.encode("ascii"))
        return fernet.decrypt(encrypted_bytes).decode("utf-8")
    except Exception as e:
        # Wrap the underlying cryptography / binascii error so callers
        # see one stable exception type. The original exception is
        # chained for diagnostic logs, but the message we surface here
        # never carries the input value.
        logger.warning("Failed to decrypt provisioner field (%s)", type(e).__name__)
        raise FieldDecryptError("failed to decrypt provisioner field") from e


def generate_presigned_url(bucket: str, key: str, expires_in: int = 3600) -> str:
    """Generate a presigned URL for an S3 object.

    Delegates to the cloud abstraction layer's ObjectStorage implementation.

    This is called during config loading (before provisioning), not during
    resource creation. It's safe because it doesn't create any AWS resources.

    Args:
        bucket: S3 bucket name.
        key: S3 object key.
        expires_in: URL expiration time in seconds.

    Returns:
        Presigned URL string.
    """
    from cloud import get_object_storage

    storage = get_object_storage()
    return storage.generate_presigned_download_url(bucket=bucket, key=key, expires_in=expires_in)
