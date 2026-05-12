"""Classify provisioner env vars as sensitive vs. non-sensitive.

Issue #1185 — the GCP Kubernetes Job adapter previously serialized
every entry in the provisioner ``env_overrides`` dict as a literal
``V1EnvVar(name=..., value=...)`` on the Job spec. Sensitive values
(database password, field encryption key, AD domain password) were
therefore exposed to anyone with Kubernetes API read access to the Job
or Pod manifests, controller events, or audit logs.

This module is the centralized, provider-neutral policy for
distinguishing sensitive provisioner env vars from harmless config.
The GCP Kubernetes adapter in ``cloud/gcp/task_runner.py`` uses
``split_env`` to route sensitive values through
``valueFrom.secretKeyRef`` (backed by an ephemeral per-Job Secret) and
leaves non-sensitive values as literal env vars. An equivalent AWS
adapter, if introduced, would consume the same classifier.

The classifier is intentionally narrow: an explicit allowlist of
known sensitive names, plus a small set of suffix rules. Pointer
suffixes (``_ID``, ``_REF``, ``_ARN``, ``_NAME``, ``_URL``, ``_FILE``,
``_PATH``, ``_BUCKET``, ``_HOST``, ``_PORT``) take precedence over
sensitive suffixes so identifiers like ``GDC_ACCESS_SECRET_ID`` (a
Secret Manager *id*, not the secret material) are correctly classed
as non-sensitive.

Adding a new sensitive env var means either:

- extending ``SENSITIVE_NAMES`` with the exact key, or
- accepting one of the documented sensitive suffixes
  (``_PASSWORD``, ``_PASSPHRASE``, ``_PRIVATE_KEY``, ``_API_TOKEN``,
  ``_CREDENTIAL``, ``_CREDENTIALS``, ``_SECRET``) as the variable
  name.

Tests in
``shifter/shifter_platform/tests/shared/cloud/test_sensitive_env.py``
pin the classification on every name currently forwarded by the
provisioner contract; that file is the regression backstop when this
allowlist or the suffix rules change.
"""

from __future__ import annotations

# Explicit allowlist of known sensitive provisioner env vars. These
# carry the secret material directly (not a pointer to a managed
# secret store). Keep this short — prefer the suffix rules below for
# new additions when the suffix is canonical.
SENSITIVE_NAMES: frozenset[str] = frozenset(
    {
        "DB_PASSWORD",
        "FIELD_ENCRYPTION_KEY",
        "DC_DOMAIN_PASSWORD",
    }
)

# Suffix rules. A name matching any of these is classed as sensitive
# UNLESS it first matches a pointer suffix below.
SENSITIVE_SUFFIXES: tuple[str, ...] = (
    "_PASSWORD",
    "_PASSPHRASE",
    "_PRIVATE_KEY",
    "_API_TOKEN",
    "_CREDENTIAL",
    "_CREDENTIALS",
    "_SECRET",
)

# Pointer suffixes — these indicate the env var carries an
# identifier or reference, not the secret material. They always win
# over the sensitive-suffix rules, so e.g. ``GDC_ACCESS_SECRET_ID``
# (Secret Manager *id*) and ``DB_HOST`` are correctly classed as
# non-sensitive. Pointer match runs first so suffix order does not
# matter.
POINTER_SUFFIXES: tuple[str, ...] = (
    "_ID",
    "_REF",
    "_ARN",
    "_NAME",
    "_URL",
    "_FILE",
    "_PATH",
    "_BUCKET",
    "_HOST",
    "_PORT",
)


def is_sensitive(name: str) -> bool:
    """Return True if ``name`` carries secret material that must not appear
    as a literal env var value on a Kubernetes Job spec."""
    if name in SENSITIVE_NAMES:
        return True
    if any(name.endswith(suffix) for suffix in POINTER_SUFFIXES):
        return False
    return any(name.endswith(suffix) for suffix in SENSITIVE_SUFFIXES)


def split_env(env: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    """Split a provisioner env dict into ``(sensitive, plain)`` halves.

    Stable ordering within each dict so callers can produce
    byte-deterministic Job specs (the existing ``_build_env`` sorts by
    key when emitting the list of env vars).
    """
    sensitive: dict[str, str] = {}
    plain: dict[str, str] = {}
    for key, value in env.items():
        if is_sensitive(key):
            sensitive[key] = value
        else:
            plain[key] = value
    return sensitive, plain
